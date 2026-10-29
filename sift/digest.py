from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal, NamedTuple
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import col, select

from sift import db, goals
from sift.domain import SHOWN_ROLES, DigestRole, ItemStatus, ItemType
from sift.items import queries
from sift.items.queries import DigestCandidate, ItemFilter
from sift.items.views import ItemSummary, TopicRef
from sift.llm.client import LLM
from sift.llm.schemas import DigestDraft, DigestInput, DigestItemBrief
from sift.models import Digest, DigestEntry
from sift.organize import store as organize

if TYPE_CHECKING:
    from sift.inbox.notify import Notifier

REPEAT_LIMIT = 3
TOP_PICKS = 3
CARRYOVER_POOL = 10
WISHLIST_PICKS = 2
OTHER = "Other"
ELSEWHERE = "Elsewhere"


class DigestPick(BaseModel):
    item: ItemSummary
    why: str | None
    next_action: str | None
    refill: bool = Field(
        description="Not one of the digest's own picks; in `top`, it moved up into a place a pick left."
    )


class DigestLine(BaseModel):
    item: ItemSummary
    line: str


class DigestGroup(BaseModel):
    kind: Literal["goal", "places"]
    heading: str
    lines: list[DigestLine]


class DigestView(BaseModel):
    id: int
    period_start: datetime
    period_end: datetime
    created_at: datetime
    model: str
    sent_at: datetime | None
    opening: str | None
    top: list[DigestPick] = Field(
        description="Up to 3 kept posts to act on, in the digest's order. A done or archived pick gives its place "
        "to the next."
    )
    done: list[DigestPick] = Field(
        description="Every done post the digest showed (picks and new posts), in its order, and done carryovers "
        "that had moved up into the top."
    )
    groups: list[DigestGroup] = Field(
        description="The digest's other new posts still kept, by goal and then by place. Done posts are under `done`."
    )
    wishlist: list[ItemSummary] = Field(
        description="Up to 2 kept posts on your wishlist, chosen by code: never shown first, then the longest since "
        "shown. One bought or taken off the wishlist drops out."
    )
    item_ids: list[int] = Field(description="The posts the digest showed when it was written, in its order.")


class DigestHeader(BaseModel):
    id: int
    period_start: datetime
    period_end: datetime
    created_at: datetime
    shown: int = Field(description="Posts the digest showed when it was written.")


class TopicDigestTab(BaseModel):
    topic: TopicRef
    open: int = Field(description="Posts on the topic still kept, not done.")


class TopicDigestView(BaseModel):
    topic: TopicRef
    overview: str = Field(description="The brief's overview, else the topic's description.")
    next: list[DigestPick] = Field(
        description="Up to 3 kept posts on the topic to act on, highest score first; a post not yet in a digest "
        "wins a tie."
    )
    new: list[DigestLine] = Field(description="The topic's other new kept posts, new as the weekly digest counts it.")


class DigestsView(BaseModel):
    latest: DigestView | None
    earlier: list[DigestHeader]
    topics: list[TopicDigestTab] = Field(description="Topics with a kept post, the most kept first.")


class DigestUnavailable(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Selection:
    new: list[DigestCandidate]
    carryover: list[DigestCandidate]

    @property
    def empty(self) -> bool:
        return not self.new and not self.carryover


def by_score(c: DigestCandidate) -> tuple[bool, int]:
    return c.relevance_score is None, -(c.relevance_score or 0)


def select_items(cands: list[DigestCandidate], last_digest_at: datetime | None) -> Selection:
    eligible = [c for c in cands if c.times_surfaced_since_interaction < REPEAT_LIMIT]
    ids = {c.id for c in eligible}
    eligible = [c for c in eligible if c.covered_by not in ids]

    def is_new(c: DigestCandidate) -> bool:
        if c.times_surfaced == 0:
            return True
        return last_digest_at is not None and c.decided_at is not None and c.decided_at > last_digest_at

    new = sorted((c for c in eligible if is_new(c)), key=by_score)
    rest = sorted((c for c in eligible if not is_new(c)), key=by_score)
    return Selection(new=new, carryover=rest[:CARRYOVER_POOL])


@dataclass(frozen=True, slots=True)
class QueueEntry:
    item_id: int
    role: DigestRole
    why: str | None
    next_action: str | None
    line: str | None


@dataclass(frozen=True, slots=True)
class Plan:
    opening: str | None
    queue: tuple[QueueEntry, ...]


def plan(sel: Selection, draft: DigestDraft) -> Plan:
    by_id = {c.id: c for c in (*sel.new, *sel.carryover)}
    picks: dict[int, QueueEntry] = {}
    for p in draft.top:
        c = by_id.get(p.item_id)
        if c is not None and c.id not in picks and len(picks) < TOP_PICKS:
            why, action = p.why.strip() or c.relevance_reason, p.next_action.strip() or c.next_action
            picks[c.id] = QueueEntry(c.id, DigestRole.pick, why, action, None)
    if not picks:
        for c in sorted(by_id.values(), key=by_score)[:TOP_PICKS]:
            picks[c.id] = QueueEntry(c.id, DigestRole.pick, c.relevance_reason, c.next_action, None)
    lines = {g.item_id: g.line.strip() for g in draft.by_goal}
    new = [
        QueueEntry(c.id, DigestRole.new, c.relevance_reason, c.next_action, lines.get(c.id) or c.summary or None)
        for c in sel.new
        if c.id not in picks
    ]
    bench = [
        QueueEntry(c.id, DigestRole.carryover, c.relevance_reason, c.next_action, None)
        for c in sel.carryover
        if c.id not in picks
    ]
    return Plan(opening=(draft.opening or "").strip() or None, queue=(*picks.values(), *new, *bench))


class Layout(NamedTuple):
    top: list[DigestPick]
    done: list[DigestPick]
    groups: list[DigestGroup]
    wishlist: list[ItemSummary]


def _top_and_done(
    queue: Sequence[QueueEntry], items: Mapping[int, ItemSummary]
) -> tuple[list[DigestPick], list[DigestPick]]:
    top: list[DigestPick] = []
    done: list[DigestPick] = []
    for e in queue:
        item = items.get(e.item_id)
        room = len(top) < TOP_PICKS
        if item is None or e.role is DigestRole.wishlist:
            continue
        if item.status is ItemStatus.kept and room:
            into = top
        elif item.status is ItemStatus.done and (e.role in SHOWN_ROLES or room):
            into = done
        else:
            continue
        into.append(DigestPick(item=item, why=e.why, next_action=e.next_action, refill=e.role is not DigestRole.pick))
    return top, done


def layout(queue: Sequence[QueueEntry], items: Mapping[int, ItemSummary], areas: Mapping[int, str]) -> Layout:
    top, done = _top_and_done(queue, items)
    on_top = {p.item.id for p in top}
    by_goal: dict[str, list[DigestLine]] = defaultdict(list)
    by_area: dict[str, list[DigestLine]] = defaultdict(list)
    for e in queue:
        item = items.get(e.item_id)
        if e.role is not DigestRole.new or item is None or item.id in on_top or item.status is not ItemStatus.kept:
            continue
        line = DigestLine(item=item, line=e.line or item.summary or "")
        if item.item_type is ItemType.place:
            by_area[areas.get(item.id, ELSEWHERE)].append(line)
        else:
            by_goal[item.matched_goal_title or OTHER].append(line)
    groups = [
        *(
            DigestGroup(kind="goal", heading=h, lines=by_goal[h])
            for h in sorted(by_goal, key=lambda h: (h == OTHER, h))
        ),
        *(
            DigestGroup(kind="places", heading=h, lines=by_area[h])
            for h in sorted(by_area, key=lambda h: (h == ELSEWHERE, h))
        ),
    ]
    wishlist = [
        item
        for e in queue
        if e.role is DigestRole.wishlist
        and (item := items.get(e.item_id)) is not None
        and item.status is ItemStatus.kept
        and item.wishlist
    ]
    return Layout(top, done, groups, wishlist)


def _latest() -> Digest | None:
    with db.read_session() as s:
        return s.exec(select(Digest).order_by(col(Digest.created_at).desc()).limit(1)).first()


def compose(now: datetime, llm: LLM | None) -> DigestView | None:
    last = _latest()
    sel = select_items(queries.digest_candidates(), last.created_at if last else None)
    if sel.empty:
        return None
    if llm is None:
        raise DigestUnavailable("Set ANTHROPIC_API_KEY (or LLM_BACKEND=fake) to generate digests.")
    # An item in both the queue and the rotation would break digest_entries' primary key.
    queued = [c.id for c in (*sel.new, *sel.carryover)]
    rotation = queries.wishlist_rotation(WISHLIST_PICKS, exclude=queued)
    values, active = goals.scoring_context()
    groups: tuple[tuple[Literal["new", "carryover"], list[DigestCandidate]], ...] = (
        ("new", sel.new),
        ("carryover", sel.carryover),
    )
    briefs = [
        DigestItemBrief(
            item_id=c.id,
            title=c.title,
            item_type=c.item_type,
            summary=c.summary,
            next_action=c.next_action,
            goal_id=c.matched_goal_id,
            relevance_score=c.relevance_score,
            status=status,
        )
        for status, group in groups
        for c in group
    ]
    draft, model = llm.compose_digest(DigestInput(values_text=values, goals=active, items=briefs))
    queue = plan(sel, draft)
    wishlist = [QueueEntry(i, DigestRole.wishlist, None, None, None) for i in rotation]
    start = (
        last.created_at
        if last
        else min((c.decided_at for c in sel.new if c.decided_at), default=now - timedelta(days=7))
    )
    with db.write_session() as s:
        row = Digest(period_start=start, period_end=now, created_at=now, opening=queue.opening, model=model)
        s.add(row)
        s.flush()
        assert row.id is not None
        digest_id = row.id
        for position, e in enumerate((*queue.queue, *wishlist), 1):
            s.add(
                DigestEntry(
                    digest_id=digest_id,
                    item_id=e.item_id,
                    position=position,
                    role=e.role,
                    why=e.why,
                    next_action=e.next_action,
                    line=e.line,
                )
            )
    view = get_digest(digest_id, llm_ready=True)
    assert view is not None
    return view


_lock = asyncio.Lock()


async def deliver_digest(now: datetime, llm: LLM | None, notifier: Notifier) -> DigestView | None:
    async with _lock:
        view = await asyncio.to_thread(compose, now, llm)
        if view is not None and await notifier.digest_ready(view):
            await asyncio.to_thread(_mark_sent, view.id, now)
        return view


def _mark_sent(digest_id: int, now: datetime) -> None:
    with db.write_session() as s:
        row = s.get(Digest, digest_id)
        if row is not None:
            row.sent_at = now


def last_fire_before(cron: str, tz: str, now: datetime) -> datetime | None:
    trigger = CronTrigger.from_crontab(cron, timezone=ZoneInfo(tz))
    fire = trigger.get_next_fire_time(None, now - timedelta(days=8))
    last = None
    while fire is not None and fire <= now:
        last = fire
        fire = trigger.get_next_fire_time(fire, fire + timedelta(seconds=1))
    return last


def due_on_startup(last_created_at: datetime | None, cron: str, tz: str, now: datetime) -> bool:
    fire = last_fire_before(cron, tz, now)
    return fire is not None and (last_created_at is None or last_created_at < fire)


def latest_created_at() -> datetime | None:
    last = _latest()
    return last.created_at if last else None


def get_digest(digest_id: int, *, llm_ready: bool) -> DigestView | None:
    with db.read_session() as s:
        row = s.get(Digest, digest_id)
        entries = s.exec(
            select(DigestEntry).where(DigestEntry.digest_id == digest_id).order_by(col(DigestEntry.position))
        ).all()
    if row is None or row.id is None:
        return None
    queue = [QueueEntry(e.item_id, e.role, e.why, e.next_action, e.line) for e in entries]
    ids = frozenset(e.item_id for e in queue)
    rows = queries.list_items(ItemFilter(frozenset(ItemStatus), ids=ids, limit=len(ids)), llm_ready=llm_ready)
    top, done, groups, wishlist = layout(queue, {i.id: i for i in rows}, queries.place_areas(ids))
    return DigestView(
        id=row.id,
        period_start=row.period_start,
        period_end=row.period_end,
        created_at=row.created_at,
        model=row.model,
        sent_at=row.sent_at,
        opening=row.opening,
        top=top,
        done=done,
        groups=groups,
        wishlist=wishlist,
        item_ids=[e.item_id for e in queue if e.role in SHOWN_ROLES],
    )


def list_digests(*, llm_ready: bool) -> DigestsView:
    with db.read_session() as s:
        rows = s.exec(select(Digest).order_by(col(Digest.created_at).desc())).all()
        counts = s.exec(
            select(DigestEntry.digest_id, func.count())
            .where(col(DigestEntry.role).in_(list(SHOWN_ROLES)))
            .group_by(col(DigestEntry.digest_id))
        ).all()
    shown = dict(counts)
    latest = rows[0].id if rows else None
    return DigestsView(
        latest=get_digest(latest, llm_ready=llm_ready) if latest is not None else None,
        earlier=[
            DigestHeader(
                id=r.id,
                period_start=r.period_start,
                period_end=r.period_end,
                created_at=r.created_at,
                shown=shown.get(r.id, 0),
            )
            for r in rows[1:]
            if r.id is not None
        ],
        topics=topic_tabs(),
    )


def topic_tabs() -> list[TopicDigestTab]:
    counts = sorted(organize.kept_counts(), key=lambda tn: (-tn[1], tn[0].name.casefold()))
    return [TopicDigestTab(topic=t, open=n) for t, n in counts]


def topic_digest(topic_id: int, *, llm_ready: bool) -> TopicDigestView | None:
    members = organize.topic_members(topic_id)
    if members is None:
        return None
    last = latest_created_at()
    sel = select_items([c for c in queries.digest_candidates() if c.id in members.item_ids], last)
    unseen = {c.id for c in sel.new}
    ranked = sorted([*sel.new, *sel.carryover], key=lambda c: (*by_score(c), c.id not in unseen))
    picks = ranked[:TOP_PICKS]
    on_top = {c.id for c in picks}
    fresh = [c for c in sel.new if c.id not in on_top]
    ids = frozenset(c.id for c in (*picks, *fresh))
    rows = queries.list_items(ItemFilter(frozenset({ItemStatus.kept}), ids=ids, limit=len(ids)), llm_ready=llm_ready)
    items = {i.id: i for i in rows}
    return TopicDigestView(
        topic=members.topic,
        overview=members.overview,
        next=[
            DigestPick(item=items[c.id], why=c.relevance_reason, next_action=c.next_action, refill=False)
            for c in picks
            if c.id in items
        ],
        new=[DigestLine(item=items[c.id], line=items[c.id].gist or c.summary) for c in fresh if c.id in items],
    )


def to_text(view: DigestView) -> str:
    out = [view.opening, ""] if view.opening else []
    out.append("To act on this week")
    for i, p in enumerate(view.top, 1):
        out.append(f"{i}. {p.item.display_title} (#{p.item.id})")
        out += [f"   {p.why}"] if p.why else []
        out += [f"   Next: {p.next_action}"] if p.next_action else []
    if view.done:
        out += ["", "Done", *(f"- {p.item.display_title} (#{p.item.id})" for p in view.done)]
    for g in view.groups:
        out += ["", g.heading, *(f"- {x.item.display_title} (#{x.item.id}): {x.line}" for x in g.lines)]
    if view.wishlist:
        out += ["", "On your wishlist", *(f"- {i.display_title} (#{i.id})" for i in view.wishlist)]
    return "\n".join(out)
