from __future__ import annotations

from collections import Counter
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import false, func, or_
from sqlmodel import Session, col, select

from sift import db
from sift.domain import SHOWN_ROLES, Decision, ItemStatus, ItemType
from sift.items.views import NO_DECOR, ItemDetail, ItemSummary, Readiness, to_detail, to_summary
from sift.llm.schemas import OverrideExample
from sift.models import Digest, DigestEntry, Goal, Import, Item, Outline, OutlineLabel
from sift.organize import model
from sift.organize import store as organize
from sift.organize.store import OrganizeActivity

PENDING = frozenset({ItemStatus.queued, ItemStatus.fetching, ItemStatus.processing})
INBOX = PENDING | {ItemStatus.failed}
KEPT = frozenset({ItemStatus.kept, ItemStatus.done})
ARCHIVED = frozenset({ItemStatus.archived})


@dataclass(frozen=True, slots=True)
class ItemFilter:
    statuses: frozenset[ItemStatus]
    goal_id: int | None = None
    item_type: ItemType | None = None
    q: str | None = None
    topic_id: int | None = None
    label: str | None = None
    ids: frozenset[int] | None = None
    limit: int = 200


def readiness(s: Session, *, llm_ready: bool) -> Readiness:
    return Readiness(llm=llm_ready, goals=_active_goals(s) > 0)


def _active_goals(s: Session) -> int:
    return s.exec(select(func.count()).select_from(Goal).where(col(Goal.active))).one()


def list_items(f: ItemFilter, *, llm_ready: bool) -> list[ItemSummary]:
    with db.read_session() as s:
        ready = readiness(s, llm_ready=llm_ready)
        q = (
            select(Item, Goal.title, Outline)
            .outerjoin(Goal, col(Item.matched_goal_id) == col(Goal.id))
            .outerjoin(Outline, organize.fresh_outline())
            .where(col(Item.status).in_(list(f.statuses)))
        )
        if f.ids is not None:
            q = q.where(col(Item.id).in_(list(f.ids)))
        if f.goal_id is not None:
            q = q.where(Item.matched_goal_id == f.goal_id)
        if f.item_type is not None:
            q = q.where(Item.item_type == f.item_type)
        if f.topic_id is not None:
            q = q.where(organize.effective_topic() == f.topic_id)
        if f.label:
            label = model.label(f.label)
            labelled = select(OutlineLabel.item_id).where(OutlineLabel.label == label)
            q = q.where(col(Outline.item_id).in_(labelled) if label else false())
        if f.q and f.q.strip():
            for term in f.q.split():
                pattern = f"%{term}%"
                q = q.where(
                    or_(
                        *(
                            col(c).ilike(pattern)
                            for c in (
                                Item.title,
                                Item.summary,
                                Item.transcript,
                                Item.caption,
                                Item.post_text,
                                Item.ocr_text,
                                Outline.gist,
                            )
                        )
                    )
                )
        q = q.order_by(col(Item.received_at).desc(), col(Item.id).desc()).limit(f.limit)
        rows = s.exec(q).all()
        decor = organize.decor(s, [(row, outline) for row, _, outline in rows])
        return [to_summary(row, title, ready, decor.get(row.id or 0, NO_DECOR)) for row, title, _ in rows]


def get_item(item_id: int, *, llm_ready: bool) -> ItemDetail | None:
    with db.read_session() as s:
        row = s.get(Item, item_id)
        if row is None:
            return None
        return detail_in(s, row, readiness(s, llm_ready=llm_ready))


def detail_in(s: Session, row: Item, ready: Readiness) -> ItemDetail:
    goal = s.get(Goal, row.matched_goal_id) if row.matched_goal_id else None
    return to_detail(row, goal.title if goal else None, ready, organize.organization(s, row))


def summary_in(s: Session, row: Item, ready: Readiness) -> ItemSummary:
    goal = s.get(Goal, row.matched_goal_id) if row.matched_goal_id else None
    decor = organize.decor(s, [(row, organize.fresh_outline_of(s, row))]).get(row.id or 0, NO_DECOR)
    return to_summary(row, goal.title if goal else None, ready, decor)


def thumbnail_path(item_id: int) -> str | None:
    with db.read_session() as s:
        row = s.get(Item, item_id)
        return row.thumbnail_path if row else None


def queue_counts() -> dict[ItemStatus, int]:
    with db.read_session() as s:
        return _counts(s)


def _counts(s: Session) -> dict[ItemStatus, int]:
    rows = s.exec(select(Item.status, func.count()).group_by(col(Item.status))).all()
    counts = Counter({status: n for status, n in rows})
    return {status: counts.get(status, 0) for status in ItemStatus}


@dataclass(frozen=True, slots=True)
class Activity:
    counts: dict[ItemStatus, int]
    moving: list[ItemSummary]
    last_interaction_at: datetime | None
    last_digest_at: datetime | None
    last_goal_change_at: datetime | None
    last_import_change_at: datetime | None
    active_goals: int
    organize: OrganizeActivity


def activity(*, llm_ready: bool) -> Activity:
    with db.read_session() as s:
        active_goals = _active_goals(s)
        ready = Readiness(llm=llm_ready, goals=active_goals > 0)
        unsettled = s.exec(select(Item).where(col(Item.status).in_(list(PENDING))).order_by(col(Item.id))).all()
        summaries = (to_summary(row, None, ready, NO_DECOR) for row in unsettled)
        return Activity(
            counts=_counts(s),
            moving=[summary for summary in summaries if summary.in_motion],
            last_interaction_at=s.exec(select(func.max(Item.last_interacted_at))).one(),
            last_digest_at=s.exec(select(func.max(Digest.created_at))).one(),
            last_goal_change_at=s.exec(select(func.max(Goal.updated_at))).one(),
            last_import_change_at=s.exec(select(func.max(Import.updated_at))).one(),
            active_goals=active_goals,
            organize=organize.activity(s),
        )


def recent_override_examples(limit: int = 10) -> list[OverrideExample]:
    with db.read_session() as s:
        rows = s.exec(
            select(Item)
            .where(
                col(Item.user_override).is_not(None),
                col(Item.threshold_decision).is_not(None),
                col(Item.user_override) != col(Item.threshold_decision),
                col(Item.extracted_at).is_not(None),
            )
            .order_by(col(Item.overridden_at).desc())
            .limit(limit)
        ).all()
        return [
            OverrideExample(
                title=r.title or "",
                item_type=r.item_type or ItemType.other,
                summary=r.summary or "",
                system_decision=r.threshold_decision or Decision.archive,
                user_decision=r.user_override or Decision.keep,
            )
            for r in rows
        ]


@dataclass(frozen=True, slots=True)
class DigestCandidate:
    id: int
    title: str
    item_type: ItemType
    summary: str
    next_action: str | None
    relevance_reason: str | None
    matched_goal_id: int | None
    relevance_score: int
    decided_at: datetime | None
    times_surfaced: int
    times_surfaced_since_interaction: int
    covered_by: int | None = None


def digest_candidates() -> list[DigestCandidate]:
    with db.read_session() as s:
        items = s.exec(select(Item).where(Item.status == ItemStatus.kept)).all()
        appearances = s.exec(
            select(DigestEntry.item_id, Digest.created_at)
            .join(Digest, col(Digest.id) == col(DigestEntry.digest_id))
            .where(col(DigestEntry.role).in_(list(SHOWN_ROLES)))
        ).all()
        covered = organize.covered_items(s)
    shown: dict[int, list[datetime]] = {}
    for item_id, created_at in appearances:
        shown.setdefault(item_id, []).append(created_at)
    out: list[DigestCandidate] = []
    for r in items:
        assert r.id is not None
        when = shown.get(r.id, [])
        since = [t for t in when if r.last_interacted_at is None or t > r.last_interacted_at]
        out.append(
            DigestCandidate(
                id=r.id,
                title=r.title or "Untitled",
                item_type=r.item_type or ItemType.other,
                summary=r.summary or "",
                next_action=r.next_action,
                relevance_reason=r.relevance_reason,
                matched_goal_id=r.matched_goal_id,
                relevance_score=r.relevance_score or 0,
                decided_at=r.decided_at,
                times_surfaced=len(when),
                times_surfaced_since_interaction=len(since),
                covered_by=covered.get(r.id),
            )
        )
    return out


def place_areas(ids: Collection[int]) -> dict[int, str]:
    with db.read_session() as s:
        rows = s.exec(
            select(Item.id, Item.details).where(col(Item.id).in_(list(ids)), Item.item_type == ItemType.place)
        ).all()
    areas = {i: ", ".join(x for x in ((d or {}).get("neighborhood"), (d or {}).get("city")) if x) for i, d in rows}
    return {i: area for i, area in areas.items() if i is not None and area}
