from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import blake2b
from typing import Protocol

from pydantic import BaseModel

from sift.domain import PointRef
from sift.llm.schemas import BriefDraft, OutlineDraft, TopicPlanDraft

GIST_MAX = 100
POINT_MAX = 200
BRIEF_POINT_MAX = 240
HEADING_MAX = 60
MAX_POINTS = 5
MAX_LABELS = 5
LABEL_MAX = 32
LABEL_WORDS = 3
TOPIC_NAME_MAX = 40
TOPIC_DESCRIPTION_MAX = 200
MAX_TOPICS = 40
BRIEF_MIN_SOURCES = 2
BRIEF_MAX_SOURCES = 60
BRIEF_SETTLE = timedelta(minutes=30)
BRIEF_MAX_WAIT = timedelta(hours=24)
SEED_MIN_POSTS = 6
SEED_MAX_POSTS = 25
MAX_MERGES = 2

_SPACES = re.compile(r"\s+")
_NON_WORD = re.compile(r"[\W_]+")


def _squash(text: str) -> str:
    return _SPACES.sub(" ", text).strip()


def cut(text: str, limit: int) -> str:
    text = _squash(text)
    if len(text) <= limit:
        return text
    head = text[: limit - 1]
    space = head.rfind(" ")
    return (head[:space] if space > limit // 2 else head).rstrip(" ,;:.-") + "…"


def slug(name: str) -> str:
    words = _NON_WORD.sub(" ", name.casefold()).split()
    if len(words) > 1 and words[0] == "the":
        words = words[1:]
    return " ".join(words)


@dataclass(frozen=True, slots=True)
class ExistingTopic:
    id: int


@dataclass(frozen=True, slots=True)
class ProposedTopic:
    name: str
    slug: str
    description: str


@dataclass(frozen=True, slots=True)
class Unsorted:
    pass


TopicPick = ExistingTopic | ProposedTopic | Unsorted


@dataclass(frozen=True, slots=True)
class Outline:
    gist: str
    key_points: tuple[str, ...]
    labels: tuple[str, ...]
    topic: TopicPick


def label(raw: str) -> str | None:
    text = _squash(raw.casefold().replace("#", " ")).strip(" .,;:!?-")
    if not text or len(text) > LABEL_MAX or len(text.split()) > LABEL_WORDS:
        return None
    return text


def _unique(values: Iterable[str | None], limit: int) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for v in values:
        if v and v.casefold() not in seen:
            seen.add(v.casefold())
            out.append(v)
    return tuple(out[:limit])


def proposed(name: str, description: str) -> ProposedTopic | None:
    name = cut(name, TOPIC_NAME_MAX)
    s = slug(name)
    return ProposedTopic(name, s, cut(description, TOPIC_DESCRIPTION_MAX)) if s else None


def normalize_outline(draft: OutlineDraft, offered: Iterable[int]) -> Outline:
    points = _unique((cut(p, POINT_MAX) for p in draft.key_points), MAX_POINTS)
    gist = cut(draft.gist, GIST_MAX) or (points[0] if points else "")
    if not points and gist:
        points = (gist,)
    labels = _unique((label(lb) for lb in draft.labels), MAX_LABELS)
    pick: TopicPick = Unsorted()
    if draft.topic_id is not None and draft.topic_id in set(offered):
        pick = ExistingTopic(draft.topic_id)
    elif draft.new_topic is not None:
        pick = proposed(draft.new_topic.name, draft.new_topic.description) or Unsorted()
    return Outline(gist, points, labels, pick)


class BriefCitation(BaseModel):
    item_id: int
    index: int
    text: str


class BriefPoint(BaseModel):
    text: str
    cites: list[BriefCitation]


class BriefSection(BaseModel):
    heading: str
    points: list[BriefPoint]


class BriefSource(BaseModel):
    item_id: int
    outlined_at: datetime
    points: int


class Brief(BaseModel):
    overview: str
    sections: list[BriefSection]
    sources: list[BriefSource]

    def points(self) -> list[BriefPoint]:
        return [p for s in self.sections for p in s.points]

    def previous_points(self) -> list[str]:
        return [p.text for p in self.points()]


class Ranked(Protocol):
    @property
    def item_id(self) -> int: ...
    @property
    def relevance(self) -> int: ...
    @property
    def received_at(self) -> datetime: ...
    @property
    def outlined_at(self) -> datetime: ...


def covered[R: Ranked](members: Iterable[R]) -> list[R]:
    return sorted(members, key=lambda m: (-m.relevance, -m.received_at.timestamp(), m.item_id))[:BRIEF_MAX_SOURCES]


@dataclass(frozen=True, slots=True)
class Member:
    item_id: int
    title: str
    gist: str
    item_type: str
    points: tuple[str, ...]
    relevance: int
    received_at: datetime
    outlined_at: datetime


@dataclass(frozen=True, slots=True)
class NumberedInput:
    by_number: dict[int, PointRef]
    members: list[Member]


def number_points(members: Iterable[Member]) -> NumberedInput:
    ranked = covered(members)
    by_number: dict[int, PointRef] = {}
    for m in ranked:
        for i in range(len(m.points)):
            by_number[len(by_number) + 1] = PointRef(m.item_id, i)
    return NumberedInput(by_number, ranked)


def parse_brief(draft: BriefDraft, numbered: NumberedInput) -> Brief:
    texts = {(m.item_id, i): p for m in numbered.members for i, p in enumerate(m.points)}
    sections: list[BriefSection] = []
    for sec in draft.sections:
        points: list[BriefPoint] = []
        for pt in sec.points:
            refs = list(dict.fromkeys(numbered.by_number[n] for n in pt.sources if n in numbered.by_number))
            text = cut(pt.text, BRIEF_POINT_MAX)
            if refs and text:
                cites = [
                    BriefCitation(item_id=r.item_id, index=r.index, text=texts[(r.item_id, r.index)]) for r in refs
                ]
                points.append(BriefPoint(text=text, cites=cites))
        if points:
            sections.append(BriefSection(heading=cut(sec.heading, HEADING_MAX), points=points))
    sources = [
        BriefSource(item_id=m.item_id, outlined_at=m.outlined_at, points=len(m.points)) for m in numbered.members
    ]
    return Brief(overview=_squash(draft.overview), sections=sections, sources=sources)


def current_sources(brief: Brief, kept_outlined_at: Mapping[int, datetime]) -> set[int]:
    return {s.item_id for s in brief.sources if kept_outlined_at.get(s.item_id) == s.outlined_at}


def derive_folds(brief: Brief, ranks: Mapping[int, Ranked]) -> dict[int, int]:
    points = brief.points()
    sizes = {s.item_id: s.points for s in brief.sources if s.item_id in ranks}
    cited = {(c.item_id, c.index) for p in points for c in p.cites if c.item_id in sizes}
    hits = {m: frozenset(i for i, p in enumerate(points) if any(c.item_id == m for c in p.cites)) for m in sizes}

    def cover_rank(m: int) -> tuple[int, int, int, float, int]:
        r = ranks[m]
        return (len(hits[m]), sizes[m], r.relevance, -r.received_at.timestamp(), -m)

    def every_point_cited(m: int) -> bool:
        return sizes[m] > 0 and all((m, i) in cited for i in range(sizes[m]))

    out: dict[int, int] = {}
    for b in sizes:
        if not hits[b] or not every_point_cited(b):
            continue
        covers = [a for a in sizes if a != b and hits[a] >= hits[b] and cover_rank(a) > cover_rank(b)]
        if covers:
            out[b] = max(covers, key=cover_rank)
    return out


def citation_numbers(brief: Brief) -> dict[int, int]:
    order = [c.item_id for p in brief.points() for c in p.cites] + [s.item_id for s in brief.sources]
    return {item_id: n for n, item_id in enumerate(dict.fromkeys(order), 1)}


def basis(members: Iterable[Ranked]) -> str:
    text = ";".join(
        f"{m.item_id}@{m.outlined_at.isoformat()}" for m in sorted(covered(members), key=lambda m: m.item_id)
    )
    return blake2b(text.encode(), digest_size=12).hexdigest()


@dataclass(frozen=True, slots=True)
class BriefClock:
    brief_basis: str | None
    pending_basis: str | None
    pending_since: datetime | None
    dirty_since: datetime | None
    requested_at: datetime | None
    brief_at: datetime | None


def requested(clock: BriefClock) -> bool:
    return clock.requested_at is not None and (clock.brief_at is None or clock.requested_at > clock.brief_at)


def brief_due(clock: BriefClock, current: str, now: datetime, *, import_running: bool) -> bool:
    if requested(clock):
        return True
    if current == clock.brief_basis:
        return False
    if clock.dirty_since is not None and now - clock.dirty_since >= BRIEF_MAX_WAIT:
        return True
    if import_running or clock.pending_basis != current or clock.pending_since is None:
        return False
    return now - clock.pending_since >= BRIEF_SETTLE


@dataclass(frozen=True, slots=True)
class Plan:
    new_topics: tuple[ProposedTopic, ...]
    merges: tuple[tuple[int, int], ...]


def normalize_plan(draft: TopicPlanDraft, live_post_counts: Mapping[int, int], dismissed: set[frozenset[int]]) -> Plan:
    topics = {t.slug: t for t in (proposed(n.name, n.description) for n in draft.new_topics) if t}
    merges: list[tuple[int, int]] = []
    used: set[int] = set()
    for m in draft.merges:
        a, b = m.from_id, m.into_id
        if a == b or a not in live_post_counts or b not in live_post_counts or a in used or b in used:
            continue
        if live_post_counts[a] > live_post_counts[b]:
            a, b = b, a
        if frozenset((a, b)) in dismissed:
            continue
        merges.append((a, b))
        used |= {a, b}
    return Plan(tuple(topics.values()), tuple(merges[:MAX_MERGES]))
