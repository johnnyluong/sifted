from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sift.llm.client import LLM
from sift.llm.schemas import TopicPlanInput
from sift.organize import model, store

log = logging.getLogger(__name__)

FAILURE_BACKOFF = timedelta(minutes=30)
OUTLINE_ATTEMPTS = 3

Key = tuple[str, Hashable]


@dataclass
class Organizer:
    clock: Callable[[], datetime]
    _failed_at: dict[Key, datetime] = field(default_factory=dict)
    _outline_failures: Counter[store.OutlineTarget] = field(default_factory=Counter)
    _merges_checked_at: datetime | None = None
    _seeded: bool = False

    def _ready(self, key: Key, asked_at: datetime | None = None) -> bool:
        failed = self._failed_at.get(key)
        return failed is None or (asked_at is not None and asked_at > failed)

    def _forget(self, now: datetime) -> None:
        self._failed_at = {k: at for k, at in self._failed_at.items() if at + FAILURE_BACKOFF > now}
        if self._outline_failures:
            pending = store.pending_outlines(self._outline_failures)
            self._outline_failures = Counter({t: n for t, n in self._outline_failures.items() if t in pending})

    def _blocked_outlines(self) -> set[Hashable]:
        backing_off = {t for kind, t in self._failed_at if kind == "outline"}
        spent = {t for t, n in self._outline_failures.items() if n >= OUTLINE_ATTEMPTS}
        return backing_off | spent

    def step(self, llm: LLM | None, *, import_running: bool) -> bool:
        if llm is None:
            return False
        now = self.clock()
        self._forget(now)
        due = store.brief_targets(now, import_running=import_running)
        briefs = [t for t in due if self._ready(("brief", t.topic_id), t.requested_at)]
        if briefs and briefs[0].requested_at is not None:
            return self._run(("brief", briefs[0].topic_id), lambda: self._brief(llm, briefs[0]))
        if not self._seeded and self._ready(("seed", 0)) and (seed := store.seed_input()) is not None:
            return self._run(("seed", 0), lambda: self._seed(llm, seed))
        blocked = self._blocked_outlines()
        outline = next((t for t in store.next_outline_targets(len(blocked) + 1) if t not in blocked), None)
        if outline is not None:
            return self._run(("outline", outline), lambda: self._outline(llm, outline))
        if self._ready(("merges", 0)) and (check := store.merge_check(since=self._merges_checked_at)) is not None:
            return self._run(("merges", 0), lambda: self._merges(llm, check))
        if briefs:
            return self._run(("brief", briefs[0].topic_id), lambda: self._brief(llm, briefs[0]))
        return False

    def _run(self, key: Key, job: Callable[[], None]) -> bool:
        try:
            job()
        except Exception as e:
            log.warning("organizer %s %s failed: %s", key[0], key[1], e)
            self._failed_at[key] = self.clock()
        else:
            self._failed_at.pop(key, None)
        return True

    def _outline(self, llm: LLM, target: store.OutlineTarget) -> None:
        try:
            inp = store.outline_input(target)
            if inp is None:
                raise ValueError("item changed or has no card")
            draft, model_name = llm.outline(inp)
            outline = model.normalize_outline(draft, (t.id for t in inp.topics))
            if not store.record_outline(target, outline, model_name, self.clock()):
                log.info("item %s changed while outlining; dropped", target.item_id)
        except Exception:
            self._outline_failures[target] += 1
            raise

    def _brief(self, llm: LLM, target: store.BriefTarget) -> None:
        try:
            read_at = self.clock()
            prepared = store.brief_input(target.topic_id)
            if prepared is None:
                store.drop_request(target)
                return
            draft, model_name = llm.compose_brief(prepared.inp)
            brief = model.parse_brief(draft, prepared.numbered)
            if not store.record_brief(target, prepared.basis, brief, model_name, read_at):
                log.info("topic %s was merged or dissolved while its brief was written; dropped", target.topic_id)
        except Exception:
            try:
                store.drop_request(target)
            except Exception:
                log.exception("organizer could not drop the brief request for topic %s", target.topic_id)
            raise

    def _seed(self, llm: LLM, inp: TopicPlanInput) -> None:
        draft, _ = llm.plan_topics(inp)
        created = store.record_seed(model.normalize_plan(draft, {}, set()).new_topics, self.clock())
        self._seeded = True
        log.info("organizer: created %d first topics from %d posts", created, len(inp.posts))

    def _merges(self, llm: LLM, check: store.MergeCheck) -> None:
        draft, _ = llm.plan_topics(check.inp)
        plan = model.normalize_plan(draft, check.live_post_counts, check.dismissed)
        store.record_suggestions(plan.merges, self.clock())
        self._merges_checked_at = check.changed_at
