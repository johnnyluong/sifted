from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeGuard

from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, and_, case, delete, func, or_
from sqlmodel import Session, col, select

from sift import db, goals
from sift.domain import BriefState, ItemStatus, ItemType, Source
from sift.items.views import Decor, ItemOrganization, ItemRef, TopicRef, card_of, display_title
from sift.llm.schemas import (
    BriefInput,
    BriefPointIn,
    BriefSourceIn,
    OutlineInput,
    PlanPost,
    PlanTopicLine,
    TopicMoveExample,
    TopicOption,
    TopicPlanInput,
)
from sift.models import Goal, Item, Outline, OutlineLabel, Topic, TopicMergeSuggestion
from sift.organize import model
from sift.organize.model import (
    MAX_TOPICS,
    Brief,
    BriefClock,
    ExistingTopic,
    Member,
    NumberedInput,
    ProposedTopic,
    TopicPick,
    Unsorted,
)

MEMBER_STATUSES = (ItemStatus.kept, ItemStatus.done)
OUTLINE_STATUSES = (*MEMBER_STATUSES, ItemStatus.queued, ItemStatus.archived)
ARCHIVED = (ItemStatus.archived,)
TRANSCRIPT_EXCERPT = 6_000
VOCABULARY = 60
MOVE_EXAMPLES = 10
TOP_LABELS = 3
LABEL_CHIPS = 30


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


class GoalRef(BaseModel):
    id: int
    title: str


class TopicSummary(BaseModel):
    id: int
    name: str
    description: str
    goal: GoalRef | None = Field(description="The goal most of its kept posts matched.")
    kept: int = Field(description="Kept and done posts.")
    archived: int
    folded: int = Field(description="Kept posts folded under another post.")
    scores: list[int] = Field(description="Relevance of each kept post, for the strip on the topic row.")
    top_labels: list[str]
    overview: str | None = Field(description="The brief's overview, or null before there is a brief.")
    brief_state: BriefState
    brief_at: datetime | None


class TopicGroup(BaseModel):
    goal: GoalRef | None
    topics: list[TopicSummary]


class MergeSuggestion(BaseModel):
    source: TopicRef
    into: TopicRef


class TopicsView(BaseModel):
    groups: list[TopicGroup] = Field(description="By goal in the Goals page's order; topics with no goal last.")
    suggestions: list[MergeSuggestion] = Field(description="'Merge source into into?'; never applied on its own.")
    options: list[TopicRef] = Field(description="Every live topic by name, for move and merge pickers.")


class CitationView(BaseModel):
    n: int = Field(description="Footnote number; a post keeps its number across the page.")
    item_id: int
    point: str = Field(description="The cited key point as the brief read it.")


class BriefPointView(BaseModel):
    text: str
    cites: list[CitationView]
    corroborated: bool = Field(description="Two or more posts make this point.")


class BriefSectionView(BaseModel):
    heading: str
    points: list[BriefPointView]


class SourceView(BaseModel):
    n: int
    item: ItemRef
    thumbnail_url: str | None
    item_type: ItemType | None
    covered_by: int | None = Field(description="Footnote number of the post that covers this one.")
    current: bool = Field(description="False once the post left the topic, was archived or was reprocessed.")


class BriefView(BaseModel):
    overview: str
    sections: list[BriefSectionView]
    sources: list[SourceView]
    model: str
    written_at: datetime


class BriefFreshness(BaseModel):
    posts: int = Field(description="Kept posts on the topic now.")
    in_brief: int = Field(
        description="Of the posts a brief covers now (the most relevant, up to 60), the ones it read as they are now."
    )


class LabelCount(BaseModel):
    label: str
    count: int


class TopicDetail(TopicSummary):
    brief: BriefView | None
    freshness: BriefFreshness
    labels: list[LabelCount]


class Dissolved(BaseModel):
    rehoming: int = Field(description="Posts the organizer will place on other topics.")


def effective_topic() -> ColumnElement[int | None]:
    return func.coalesce(col(Outline.topic_override_id), col(Outline.topic_id))


def fresh_outline() -> ColumnElement[bool]:
    return and_(col(Outline.item_id) == col(Item.id), col(Outline.extracted_at) == col(Item.extracted_at))


def _live() -> ColumnElement[bool]:
    return and_(col(Topic.merged_into_id).is_(None), col(Topic.dissolved_at).is_(None))


def _is_live(t: Topic | None) -> TypeGuard[Topic]:
    return t is not None and t.merged_into_id is None and t.dissolved_at is None


def _ref(t: Topic) -> TopicRef:
    assert t.id is not None
    return TopicRef(id=t.id, name=t.name)


def _item_ref(row: Item) -> ItemRef:
    assert row.id is not None
    return ItemRef(id=row.id, title=display_title(row.title, row.author_handle, row.source))


def _brief(t: Topic) -> Brief | None:
    return Brief.model_validate(t.brief) if t.brief else None


def _clock(t: Topic, change: dict[str, Any]) -> BriefClock:
    def v(name: str) -> Any:
        return change.get(name, getattr(t, name))

    return BriefClock(
        v("brief_basis"),
        v("pending_basis"),
        v("pending_since"),
        v("dirty_since"),
        v("brief_requested_at"),
        v("brief_at"),
    )


def topic_of(o: Outline) -> int | None:
    return o.topic_override_id if o.topic_override_id is not None else o.topic_id


@dataclass(frozen=True, slots=True)
class _Kept:
    item_id: int
    outlined_at: datetime
    relevance: int
    received_at: datetime
    matched_goal_id: int | None
    labels: tuple[str, ...]


def _members(s: Session, topic_ids: Iterable[int]) -> dict[int, list[_Kept]]:
    ids = list(set(topic_ids))
    out: dict[int, list[_Kept]] = defaultdict(list)
    if not ids:
        return out
    rows = s.exec(
        select(Outline, Item.relevance_score, Item.received_at, Item.matched_goal_id)
        .select_from(Item)
        .join(Outline, fresh_outline())
        .where(col(Item.status).in_(MEMBER_STATUSES), effective_topic().in_(ids))
    ).all()
    for o, relevance, received_at, goal_id in rows:
        if (topic_id := topic_of(o)) is not None:
            out[topic_id].append(_Kept(o.item_id, o.outlined_at, relevance or 0, received_at, goal_id, tuple(o.labels)))
    return out


@dataclass(frozen=True, slots=True)
class _Folds:
    cover_of: dict[int, int]
    current: set[int]
    cited: Counter[int]


_NO_FOLDS = _Folds({}, set(), Counter())


def _folds(t: Topic, kept: Sequence[_Kept]) -> _Folds:
    brief = _brief(t)
    if brief is None:
        return _NO_FOLDS
    current = model.current_sources(brief, {k.item_id: k.outlined_at for k in kept})
    ranks = {k.item_id: k for k in kept if k.item_id in current}
    cited = Counter(i for p in brief.points() for i in {c.item_id for c in p.cites} if i in current)
    return _Folds(model.derive_folds(brief, ranks), current, cited)


def _folds_by_topic(s: Session, topics: Iterable[Topic]) -> dict[int, _Folds]:
    briefed = {t.id: t for t in topics if t.id is not None and t.brief}
    members = _members(s, briefed)
    return {tid: _folds(t, members.get(tid, [])) for tid, t in briefed.items()}


def _item_refs(s: Session, ids: Iterable[int]) -> dict[int, ItemRef]:
    wanted = list(set(ids))
    if not wanted:
        return {}
    rows = s.exec(select(Item.id, Item.title, Item.author_handle, Item.source).where(col(Item.id).in_(wanted))).all()
    return {
        i: ItemRef(id=i, title=display_title(title, handle, Source(source))) for i, title, handle, source in rows if i
    }


def _state(t: Topic, kept: Sequence[_Kept]) -> BriefState:
    if model.requested(_clock(t, {})):
        return BriefState.writing
    if t.brief is None:
        return BriefState.none
    return BriefState.fresh if t.brief_basis == model.basis(kept) else BriefState.stale


def fresh_outline_of(s: Session, row: Item) -> Outline | None:
    outline = s.get(Outline, row.id)
    return outline if outline is not None and outline.extracted_at == row.extracted_at else None


def decor(s: Session, rows: Sequence[tuple[Item, Outline | None]]) -> dict[int, Decor]:
    topic_ids = {tid for _, o in rows if o is not None and (tid := topic_of(o)) is not None}
    topics = {t.id: t for t in s.exec(select(Topic).where(col(Topic.id).in_(topic_ids))).all()} if topic_ids else {}
    cover_of = {i: c for f in _folds_by_topic(s, topics.values()).values() for i, c in f.cover_of.items()}
    refs = _item_refs(s, (cover_of[item.id] for item, _ in rows if item.id in cover_of))
    out: dict[int, Decor] = {}
    for item, o in rows:
        if o is None or item.id is None:
            continue
        t = topics.get(topic_of(o))
        cover = cover_of.get(item.id)
        out[item.id] = Decor(o.gist, tuple(o.labels), _ref(t) if t else None, refs.get(cover) if cover else None)
    return out


def organization(s: Session, row: Item) -> ItemOrganization | None:
    outline = fresh_outline_of(s, row)
    if outline is None or row.id is None:
        return None
    effective = topic_of(outline)
    topic = s.get(Topic, effective) if effective is not None else None
    pick = s.get(Topic, outline.topic_id) if outline.topic_id is not None else None
    folds = _folds_by_topic(s, [topic] if topic else []).get(effective or 0, _NO_FOLDS)
    cover = folds.cover_of.get(row.id)
    covered = [i for i, c in folds.cover_of.items() if c == row.id]
    refs = _item_refs(s, [*covered, *([cover] if cover else [])])
    return ItemOrganization(
        gist=outline.gist,
        key_points=list(outline.key_points),
        labels=list(outline.labels),
        topic=_ref(topic) if topic else None,
        sift_topic=_ref(pick) if pick else None,
        topic_chosen_by=None if topic is None else ("you" if outline.topic_override_id else "sift"),
        covered_by=refs.get(cover) if cover else None,
        covers=[refs[i] for i in covered if i in refs],
        cited_in=folds.cited[row.id],
    )


def covered_items(s: Session) -> dict[int, int]:
    topics = s.exec(select(Topic).where(_live(), col(Topic.brief).is_not(None))).all()
    return {i: c for f in _folds_by_topic(s, topics).values() for i, c in f.cover_of.items()}


@dataclass(frozen=True, slots=True)
class OutlineTarget:
    item_id: int
    extracted_at: datetime
    # Set on an unsorted post's retry, so each later taxonomy change makes it a new target with fresh attempts.
    taxonomy_at: datetime | None = None


def taxonomy_changed_at(s: Session) -> datetime | None:
    return s.exec(select(func.max(Topic.updated_at))).one()


def _outline_targets(s: Session, *where: ColumnElement[bool], limit: int | None = None) -> list[OutlineTarget]:
    changed = taxonomy_changed_at(s)
    since = [col(Outline.outlined_at) < col(Item.decided_at)]
    if changed is not None:
        since.append(col(Outline.outlined_at) < changed)
    unsorted_retry = and_(
        col(Item.status).in_(MEMBER_STATUSES),
        col(Outline.extracted_at) == col(Item.extracted_at),
        col(Outline.topic_id).is_(None),
        col(Outline.topic_override_id).is_(None),
        or_(*since),
    )
    kept_first = case((col(Item.status).in_(MEMBER_STATUSES), 0), (col(Item.status) == ItemStatus.queued, 1), else_=2)
    rows = s.exec(
        select(Item.id, Item.extracted_at, unsorted_retry)
        .outerjoin(Outline, col(Outline.item_id) == col(Item.id))
        .where(
            col(Item.extracted_at).is_not(None),
            col(Item.status).in_(OUTLINE_STATUSES),
            or_(
                col(Outline.item_id).is_(None),
                col(Outline.extracted_at) != col(Item.extracted_at),
                col(Outline.needs_topic),
                unsorted_retry,
            ),
            *where,
        )
        .order_by(kept_first, col(Item.extracted_at).desc(), col(Item.id).desc())
        .limit(limit)
    ).all()
    return [
        OutlineTarget(item_id, extracted_at, changed if retry else None)
        for item_id, extracted_at, retry in rows
        if item_id and extracted_at
    ]


def next_outline_targets(limit: int) -> list[OutlineTarget]:
    with db.read_session() as s:
        return _outline_targets(s, limit=limit)


def pending_outlines(targets: Iterable[OutlineTarget]) -> set[OutlineTarget]:
    wanted = set(targets)
    with db.read_session() as s:
        return wanted & set(_outline_targets(s, col(Item.id).in_({t.item_id for t in wanted})))


def _topic_counts(s: Session, statuses: Sequence[ItemStatus]) -> dict[int, int]:
    rows = s.exec(
        select(effective_topic(), func.count())
        .select_from(Item)
        .join(Outline, fresh_outline())
        .where(col(Item.status).in_(statuses))
        .group_by(effective_topic())
    ).all()
    return {tid: n for tid, n in rows if tid is not None}


def _live_topics(s: Session) -> list[Topic]:
    return list(s.exec(select(Topic).where(_live()).order_by(col(Topic.name))).all())


def _vocabulary(s: Session) -> list[str]:
    rows = s.exec(
        select(OutlineLabel.label, func.count())
        .join(Outline, col(Outline.item_id) == col(OutlineLabel.item_id))
        .join(Item, fresh_outline())
        .where(col(Item.status).in_(MEMBER_STATUSES))
        .group_by(col(OutlineLabel.label))
        .order_by(func.count().desc(), col(OutlineLabel.label))
        .limit(VOCABULARY)
    ).all()
    return [label for label, _ in rows]


def _moves(s: Session) -> list[TopicMoveExample]:
    rows = s.exec(
        select(Item, Outline)
        .join(Outline, col(Outline.item_id) == col(Item.id))
        .where(
            col(Outline.topic_override_id).is_not(None),
            or_(col(Outline.topic_id).is_(None), col(Outline.topic_id) != col(Outline.topic_override_id)),
        )
        .order_by(col(Outline.moved_at).desc())
        .limit(MOVE_EXAMPLES)
    ).all()
    names = {t.id: t.name for t in s.exec(select(Topic)).all()}
    return [
        TopicMoveExample(
            title=display_title(item.title, item.author_handle, item.source),
            from_topic=names.get(o.topic_id) if o.topic_id else None,
            to_topic=names.get(o.topic_override_id, ""),
        )
        for item, o in rows
    ]


def outline_input(target: OutlineTarget) -> OutlineInput | None:
    with db.read_session() as s:
        row = s.get(Item, target.item_id)
        if row is None or row.extracted_at != target.extracted_at:
            return None
        card = card_of(row)
        if card is None:
            return None
        live = _live_topics(s)
        sizes = _topic_counts(s, OUTLINE_STATUSES)
        transcript = (row.transcript or "")[:TRANSCRIPT_EXCERPT] or None
        return OutlineInput(
            source=row.source,
            card=card,
            caption=row.caption or row.post_text,
            on_screen_text=row.ocr_text,
            transcript_excerpt=transcript,
            topics=[
                TopicOption(id=t.id, name=t.name, description=t.description, size=sizes.get(t.id, 0))
                for t in sorted(live, key=lambda t: -sizes.get(t.id or 0, 0))
                if t.id is not None
            ],
            may_create_topic=_may_create_topic(s, row),
            label_vocabulary=_vocabulary(s),
            moves=_moves(s),
        )


def _survivor(s: Session, topic: Topic | None) -> Topic | None:
    seen: set[int] = set()
    while topic is not None and topic.merged_into_id is not None and topic.id not in seen:
        seen.add(topic.id or 0)
        topic = s.get(Topic, topic.merged_into_id)
    return topic if _is_live(topic) else None


def _may_create_topic(s: Session, row: Item) -> bool:
    if row.status not in MEMBER_STATUSES:
        return False
    return s.exec(select(func.count()).select_from(Topic).where(_live())).one() < MAX_TOPICS


def _kept_topic_count(s: Session) -> int:
    return s.exec(
        select(func.count(func.distinct(effective_topic())))
        .select_from(Item)
        .join(Outline, fresh_outline())
        .where(col(Item.status).in_(MEMBER_STATUSES))
    ).one()


def _create(s: Session, p: ProposedTopic, now: datetime) -> Topic:
    t = Topic(name=p.name, slug=p.slug, description=p.description, created_at=now, updated_at=now)
    s.add(t)
    s.flush()
    return t


@dataclass(frozen=True, slots=True)
class _Placement:
    topic_id: int | None
    needs_topic: bool


_UNSORTED = _Placement(None, needs_topic=False)
_REHOME = _Placement(None, needs_topic=True)


def _resolve(s: Session, item: Item, pick: TopicPick, now: datetime) -> _Placement:
    match pick:
        case ExistingTopic(id=tid):
            survivor = _survivor(s, s.get(Topic, tid))
            return _Placement(survivor.id, needs_topic=False) if survivor else _REHOME
        case ProposedTopic(slug=slug):
            same = s.exec(select(Topic).where(Topic.slug == slug)).first()
            if same is not None:
                survivor = _survivor(s, same)
                return _Placement(survivor.id, needs_topic=False) if survivor else _UNSORTED
            if not _may_create_topic(s, item):
                return _UNSORTED
            return _Placement(_create(s, pick, now).id, needs_topic=False)
        case Unsorted():
            return _UNSORTED


def record_outline(target: OutlineTarget, outline: model.Outline, model_name: str, now: datetime) -> bool:
    with db.write_session() as s:
        item = s.get(Item, target.item_id)
        if item is None or item.extracted_at != target.extracted_at:
            return False
        placement = _resolve(s, item, outline.topic, now)
        fields: dict[str, Any] = {
            "extracted_at": target.extracted_at,
            "outlined_at": now,
            "model": model_name,
            "gist": outline.gist,
            "key_points": list(outline.key_points),
            "labels": list(outline.labels),
            "topic_id": placement.topic_id,
            "needs_topic": placement.needs_topic,
        }
        row = s.get(Outline, target.item_id)
        if row is None:
            s.add(Outline(item_id=target.item_id, **fields))
        else:
            for k, v in fields.items():
                setattr(row, k, v)
        s.flush()
        s.exec(delete(OutlineLabel).where(col(OutlineLabel.item_id) == target.item_id))
        for label in outline.labels:
            s.add(OutlineLabel(item_id=target.item_id, label=label))
        return True


@dataclass(frozen=True, slots=True)
class BriefTarget:
    topic_id: int
    requested_at: datetime | None


def _settle(t: Topic, kept: Sequence[_Kept], now: datetime) -> dict[str, Any]:
    if len(kept) < model.BRIEF_MIN_SOURCES:
        if t.brief is not None or t.brief_requested_at is not None or t.dirty_since is not None:
            return _cleared_brief()
        return {}
    current = model.basis(kept)
    if current == t.brief_basis:
        if t.dirty_since is not None or t.pending_basis is not None:
            return {"dirty_since": None, "pending_basis": None, "pending_since": None}
        return {}
    change: dict[str, Any] = {}
    if t.dirty_since is None:
        change["dirty_since"] = now
    if t.pending_basis != current:
        change |= {"pending_basis": current, "pending_since": now}
    return change


def _brief_pass(
    s: Session, now: datetime, import_running: bool
) -> tuple[list[BriefTarget], list[tuple[Topic, dict[str, Any]]]]:
    topics = _live_topics(s)
    members = _members(s, [t.id for t in topics if t.id is not None])
    changes: list[tuple[Topic, dict[str, Any]]] = []
    requested: list[BriefTarget] = []
    due: list[BriefTarget] = []
    for t in topics:
        assert t.id is not None
        kept = members.get(t.id, [])
        if change := _settle(t, kept, now):
            changes.append((t, change))
        if len(kept) < model.BRIEF_MIN_SOURCES:
            continue
        clock = _clock(t, change)
        if model.requested(clock):
            requested.append(BriefTarget(t.id, clock.requested_at))
        elif model.brief_due(clock, model.basis(kept), now, import_running=import_running):
            due.append(BriefTarget(t.id, None))
    return requested + due, changes


def brief_targets(now: datetime, *, import_running: bool) -> list[BriefTarget]:
    with db.read_session() as s:
        targets, changes = _brief_pass(s, now, import_running)
    if not changes:
        return targets
    # Decided again under the write lock, so a request or move that landed since the read is not overwritten.
    with db.write_session() as s:
        targets, changes = _brief_pass(s, now, import_running)
        for t, change in changes:
            for k, v in change.items():
                setattr(t, k, v)
    return targets


def _cleared_brief() -> dict[str, Any]:
    return {
        "brief": None,
        "brief_at": None,
        "brief_model": None,
        "brief_basis": None,
        "pending_basis": None,
        "pending_since": None,
        "dirty_since": None,
        "brief_requested_at": None,
    }


@dataclass(frozen=True, slots=True)
class PreparedBrief:
    inp: BriefInput
    numbered: NumberedInput
    basis: str


def brief_input(topic_id: int) -> PreparedBrief | None:
    with db.read_session() as s:
        topic = s.get(Topic, topic_id)
        if not _is_live(topic):
            return None
        kept = _members(s, [topic_id])[topic_id]
        if len(kept) < model.BRIEF_MIN_SOURCES:
            return None
        chosen = model.covered(kept)
        ids = [k.item_id for k in chosen]
        refs = _item_refs(s, ids)
        outlines = {
            o.item_id: (o, item_type)
            for o, item_type in s.exec(
                select(Outline, Item.item_type)
                .join(Item, col(Item.id) == col(Outline.item_id))
                .where(col(Outline.item_id).in_(ids))
            ).all()
        }
        previous = _brief(topic)
    members: list[Member] = []
    for k in chosen:
        o, item_type = outlines[k.item_id]
        members.append(
            Member(
                item_id=k.item_id,
                title=refs[k.item_id].title,
                gist=o.gist,
                item_type=ItemType(item_type or ItemType.other).value,
                points=tuple(o.key_points),
                relevance=k.relevance,
                received_at=k.received_at,
                outlined_at=k.outlined_at,
            )
        )
    numbered = model.number_points(members)
    number_of = {ref: n for n, ref in numbered.by_number.items()}
    sources = [
        BriefSourceIn(
            title=m.title,
            item_type=ItemType(m.item_type),
            gist=m.gist,
            points=[BriefPointIn(n=number_of[model.PointRef(m.item_id, i)], text=p) for i, p in enumerate(m.points)],
        )
        for m in numbered.members
    ]
    _, active = goals.scoring_context()
    inp = BriefInput(
        topic=topic.name,
        topic_description=topic.description,
        goals=active,
        sources=sources,
        previous_points=previous.previous_points() if previous else [],
    )
    return PreparedBrief(inp, numbered, model.basis(kept))


def record_brief(target: BriefTarget, basis: str, brief: Brief, model_name: str, read_at: datetime) -> bool:
    """`read_at` is when the input was read; a request made after it stays standing."""
    with db.write_session() as s:
        row = s.get(Topic, target.topic_id)
        if not _is_live(row):
            return False
        row.brief = brief.model_dump(mode="json")
        row.brief_at = read_at
        row.brief_model = model_name
        row.brief_basis = basis
        row.pending_basis = row.pending_since = row.dirty_since = None
        if row.brief_requested_at is not None and row.brief_requested_at <= read_at:
            row.brief_requested_at = None
        return True


def drop_request(target: BriefTarget) -> None:
    if target.requested_at is None:
        return
    with db.write_session() as s:
        row = s.get(Topic, target.topic_id)
        if row is not None and row.brief_requested_at == target.requested_at:
            row.brief_requested_at = None


def _plan_posts(s: Session, targets: Sequence[OutlineTarget]) -> list[PlanPost]:
    rows = s.exec(select(Item).where(col(Item.id).in_([t.item_id for t in targets]))).all()
    return [
        PlanPost(title=r.title or "Untitled", item_type=r.item_type or ItemType.other, summary=r.summary or "")
        for r in rows
    ]


def seed_input() -> TopicPlanInput | None:
    with db.read_session() as s:
        if s.exec(select(Topic.id).limit(1)).first() is not None:
            return None
    targets = next_outline_targets(model.SEED_MAX_POSTS)
    if len(targets) < model.SEED_MIN_POSTS:
        return None
    with db.read_session() as s:
        posts = _plan_posts(s, targets)
    _, active = goals.scoring_context()
    return TopicPlanInput(goals=active, topics=[], retired=[], posts=posts)


def record_seed(topics: Sequence[ProposedTopic], now: datetime) -> int:
    with db.write_session() as s:
        if s.exec(select(Topic.id).limit(1)).first() is not None:
            return 0
        for p in topics[:MAX_TOPICS]:
            _create(s, p, now)
        return min(len(topics), MAX_TOPICS)


@dataclass(frozen=True, slots=True)
class MergeCheck:
    inp: TopicPlanInput
    live_post_counts: dict[int, int]
    dismissed: set[frozenset[int]]
    changed_at: datetime


def merge_check(*, since: datetime | None) -> MergeCheck | None:
    with db.read_session() as s:
        changed = taxonomy_changed_at(s)
        if changed is None or (since is not None and changed <= since):
            return None
        live = _live_topics(s)
        if len(live) < 2:
            return None
        sizes = _topic_counts(s, OUTLINE_STATUSES)
        retired = s.exec(select(Topic.name).where(col(Topic.dissolved_at).is_not(None))).all()
        dismissed = s.exec(
            select(TopicMergeSuggestion.source_id, TopicMergeSuggestion.into_id).where(
                col(TopicMergeSuggestion.dismissed_at).is_not(None)
            )
        ).all()
    _, active = goals.scoring_context()
    lines = [
        PlanTopicLine(id=t.id, name=t.name, description=t.description, posts=sizes.get(t.id, 0))
        for t in live
        if t.id is not None
    ]
    return MergeCheck(
        inp=TopicPlanInput(goals=active, topics=lines, retired=list(retired), posts=[]),
        live_post_counts={line.id: line.posts for line in lines},
        dismissed={frozenset(pair) for pair in dismissed},
        changed_at=changed,
    )


def record_suggestions(merges: Iterable[tuple[int, int]], now: datetime) -> None:
    with db.write_session() as s:
        for source_id, into_id in merges:
            pair = (source_id, into_id)
            either_way = col(TopicMergeSuggestion.source_id).in_(pair), col(TopicMergeSuggestion.into_id).in_(pair)
            if s.exec(select(TopicMergeSuggestion.source_id).where(*either_way)).first() is not None:
                continue
            if _is_live(s.get(Topic, source_id)) and _is_live(s.get(Topic, into_id)):
                s.add(TopicMergeSuggestion(source_id=source_id, into_id=into_id, suggested_at=now))


def _goal_of(kept: Sequence[_Kept], goal_refs: dict[int, GoalRef]) -> GoalRef | None:
    counts = Counter(k.matched_goal_id for k in kept if k.matched_goal_id in goal_refs)
    if not counts:
        return None
    best = max(counts.items(), key=lambda kv: (kv[1], -(kv[0] or 0)))[0]
    return goal_refs.get(best or 0)


def _summary(t: Topic, kept: Sequence[_Kept], archived: int, goal_refs: dict[int, GoalRef]) -> TopicSummary:
    assert t.id is not None
    brief = _brief(t)
    label_counts = Counter(label for k in kept for label in k.labels)
    return TopicSummary(
        id=t.id,
        name=t.name,
        description=t.description,
        goal=_goal_of(kept, goal_refs),
        kept=len(kept),
        archived=archived,
        folded=len(_folds(t, kept).cover_of),
        scores=sorted((k.relevance for k in kept), reverse=True),
        top_labels=[label for label, _ in label_counts.most_common(TOP_LABELS)],
        overview=brief.overview if brief else None,
        brief_state=_state(t, kept),
        brief_at=t.brief_at,
    )


def _goal_refs(s: Session) -> tuple[list[int], dict[int, GoalRef]]:
    rows = s.exec(select(Goal).order_by(col(Goal.active).desc(), col(Goal.created_at))).all()
    return [g.id for g in rows if g.id is not None], {g.id: GoalRef(id=g.id, title=g.title) for g in rows if g.id}


def list_topics() -> TopicsView:
    with db.read_session() as s:
        live = _live_topics(s)
        members = _members(s, [t.id for t in live if t.id is not None])
        archived = _topic_counts(s, ARCHIVED)
        order, goal_refs = _goal_refs(s)
        names = {t.id: t for t in live}
        suggestions = [
            MergeSuggestion(source=_ref(names[g.source_id]), into=_ref(names[g.into_id]))
            for g in s.exec(
                select(TopicMergeSuggestion)
                .where(col(TopicMergeSuggestion.dismissed_at).is_(None))
                .order_by(col(TopicMergeSuggestion.suggested_at))
            ).all()
            if g.source_id in names and g.into_id in names
        ]
    summaries = [_summary(t, members.get(t.id or 0, []), archived.get(t.id or 0, 0), goal_refs) for t in live]
    grouped: dict[int | None, list[TopicSummary]] = defaultdict(list)
    for summary in summaries:
        if summary.kept:
            grouped[summary.goal.id if summary.goal else None].append(summary)
    keys: list[int | None] = [g for g in order if g in grouped]
    if None in grouped:
        keys.append(None)
    return TopicsView(
        groups=[
            TopicGroup(
                goal=goal_refs.get(k) if k is not None else None,
                topics=sorted(grouped[k], key=lambda t: (-t.kept, t.name.casefold())),
            )
            for k in keys
        ],
        suggestions=suggestions,
        options=[_ref(t) for t in live],
    )


def _brief_view(s: Session, t: Topic, kept: Sequence[_Kept]) -> BriefView | None:
    brief = _brief(t)
    if brief is None or t.brief_at is None or t.brief_model is None:
        return None
    numbers = model.citation_numbers(brief)
    folds = _folds(t, kept)
    items = {r.id: r for r in s.exec(select(Item).where(col(Item.id).in_(list(numbers)))).all()}
    sections = [
        BriefSectionView(
            heading=sec.heading,
            points=[
                BriefPointView(
                    text=p.text,
                    cites=[CitationView(n=numbers[c.item_id], item_id=c.item_id, point=c.text) for c in p.cites],
                    corroborated=len({c.item_id for c in p.cites}) >= 2,
                )
                for p in sec.points
            ],
        )
        for sec in brief.sections
    ]
    sources = [
        SourceView(
            n=n,
            item=_item_ref(items[item_id]),
            thumbnail_url=f"/api/items/{item_id}/thumbnail" if items[item_id].thumbnail_path else None,
            item_type=items[item_id].item_type,
            covered_by=numbers.get(folds.cover_of[item_id]) if item_id in folds.cover_of else None,
            current=item_id in folds.current,
        )
        for item_id, n in sorted(numbers.items(), key=lambda kv: kv[1])
        if item_id in items
    ]
    return BriefView(
        overview=brief.overview, sections=sections, sources=sources, model=t.brief_model, written_at=t.brief_at
    )


def _labels(label_lists: Iterable[Iterable[str]]) -> list[LabelCount]:
    counts = Counter(label for labels in label_lists for label in labels)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:LABEL_CHIPS]
    return [LabelCount(label=label, count=n) for label, n in ranked]


def get_topic(topic_id: int) -> TopicDetail | None:
    with db.read_session() as s:
        t = _survivor(s, s.get(Topic, topic_id))
        if t is None or t.id is None:
            return None
        kept = _members(s, [t.id])[t.id]
        _, goal_refs = _goal_refs(s)
        summary = _summary(t, kept, _topic_counts(s, ARCHIVED).get(t.id, 0), goal_refs)
        brief_view = _brief_view(s, t, kept)
        in_brief = len(_folds(t, kept).current & {k.item_id for k in model.covered(kept)})
    return TopicDetail(
        **summary.model_dump(),
        brief=brief_view,
        freshness=BriefFreshness(posts=len(kept), in_brief=in_brief),
        labels=_labels(k.labels for k in kept),
    )


def labels(topic_id: int | None = None) -> list[LabelCount]:
    with db.read_session() as s:
        q = (
            select(Outline.labels)
            .select_from(Item)
            .join(Outline, fresh_outline())
            .where(col(Item.status).in_(MEMBER_STATUSES))
        )
        if topic_id is not None:
            q = q.where(effective_topic() == topic_id)
        return _labels(s.exec(q).all())


def _live_topic(s: Session, topic_id: int) -> Topic:
    t = s.get(Topic, topic_id)
    if not _is_live(t):
        raise NotFound("Topic not found")
    return t


def _free_tombstone_slug(tombstone: Topic) -> None:
    tombstone.slug = f"{tombstone.slug}~{tombstone.id}"


def rename_topic(topic_id: int, name: str | None, description: str | None, now: datetime) -> TopicDetail:
    with db.write_session() as s:
        t = _live_topic(s, topic_id)
        if name is not None:
            new = model.proposed(name, "")
            if new is None:
                raise Conflict("A topic name needs a letter or a digit.")
            other = s.exec(select(Topic).where(Topic.slug == new.slug, Topic.id != topic_id)).first()
            if _is_live(other):
                raise Conflict(f'"{other.name}" is already a topic. Merge into it instead.')
            if other is not None:
                _free_tombstone_slug(other)
                s.flush()
            t.name, t.slug = new.name, new.slug
        if description is not None:
            t.description = model.cut(description, model.TOPIC_DESCRIPTION_MAX)
        t.updated_at = now
    return _detail(topic_id)


def _detail(topic_id: int) -> TopicDetail:
    detail = get_topic(topic_id)
    if detail is None:
        raise NotFound("Topic not found")
    return detail


def merge_topics(source_id: int, into_id: int, now: datetime) -> TopicDetail:
    with db.write_session() as s:
        source = s.get(Topic, source_id)
        target = _survivor(s, s.get(Topic, into_id))
        if source is None or target is None or target.id is None:
            raise NotFound("Topic not found")
        if source.id == target.id:
            raise Conflict("A topic cannot merge into itself.")
        if source.merged_into_id is not None and _survivor(s, source) is target:
            return _detail(target.id)
        if not _is_live(source):
            raise NotFound("Topic not found")
        for row in s.exec(select(Outline).where(Outline.topic_id == source_id)).all():
            row.topic_id = target.id
        for row in s.exec(select(Outline).where(Outline.topic_override_id == source_id)).all():
            row.topic_override_id = target.id
        for alias in s.exec(select(Topic).where(Topic.merged_into_id == source_id)).all():
            alias.merged_into_id = target.id
        source.merged_into_id = target.id
        for k, v in _cleared_brief().items():
            setattr(source, k, v)
        source.updated_at = target.updated_at = now
        target_id = target.id
    return _detail(target_id)


def dissolve_topic(topic_id: int, now: datetime) -> Dissolved:
    with db.write_session() as s:
        t = _live_topic(s, topic_id)
        rehoming = 0
        for row in s.exec(select(Outline).where(Outline.topic_id == topic_id)).all():
            row.topic_id = None
            row.needs_topic = True
            rehoming += 1
        for row in s.exec(select(Outline).where(Outline.topic_override_id == topic_id)).all():
            row.topic_override_id = None
            row.moved_at = None
        for k, v in _cleared_brief().items():
            setattr(t, k, v)
        t.dissolved_at = now
        t.updated_at = now
    return Dissolved(rehoming=rehoming)


def move_item(item_id: int, topic_id: int | None, now: datetime) -> ItemOrganization:
    with db.write_session() as s:
        item = s.get(Item, item_id)
        if item is None:
            raise NotFound("Item not found")
        row = s.get(Outline, item_id)
        if row is None or row.extracted_at != item.extracted_at:
            raise Conflict("This post is not organized yet.")
        if topic_id is None:
            row.topic_override_id = None
        else:
            target = _survivor(s, s.get(Topic, topic_id))
            if target is None:
                raise NotFound("Topic not found")
            row.topic_override_id = target.id
        row.moved_at = now
    with db.read_session() as s:
        item = s.get(Item, item_id)
        assert item is not None
        org = organization(s, item)
    assert org is not None
    return org


def request_brief(topic_id: int, now: datetime) -> TopicDetail:
    with db.write_session() as s:
        t = _live_topic(s, topic_id)
        if len(_members(s, [topic_id])[topic_id]) < model.BRIEF_MIN_SOURCES:
            raise Conflict(f"A brief needs at least {model.BRIEF_MIN_SOURCES} kept posts on the topic.")
        t.brief_requested_at = now
    return _detail(topic_id)


def dismiss_suggestion(source_id: int, into_id: int, now: datetime) -> TopicsView:
    with db.write_session() as s:
        row = s.get(TopicMergeSuggestion, (source_id, into_id))
        if row is None:
            raise NotFound("Suggestion not found")
        row.dismissed_at = row.dismissed_at or now
    return list_topics()


@dataclass(frozen=True, slots=True)
class OrganizeActivity:
    last_change_at: datetime | None
    writing_brief: bool
    topics: int


def activity(s: Session) -> OrganizeActivity:
    stamps = [
        s.exec(select(func.max(Outline.outlined_at))).one(),
        s.exec(select(func.max(Outline.moved_at))).one(),
        s.exec(select(func.max(Topic.updated_at))).one(),
        s.exec(select(func.max(Topic.brief_at))).one(),
        s.exec(select(func.max(TopicMergeSuggestion.suggested_at))).one(),
        s.exec(select(func.max(TopicMergeSuggestion.dismissed_at))).one(),
    ]
    writing = s.exec(
        select(Topic.id)
        .where(
            _live(),
            col(Topic.brief_requested_at).is_not(None),
            or_(col(Topic.brief_at).is_(None), col(Topic.brief_requested_at) > col(Topic.brief_at)),
        )
        .limit(1)
    ).first()
    topics = _kept_topic_count(s)
    present = [t for t in stamps if t is not None]
    return OrganizeActivity(max(present) if present else None, writing is not None, topics)
