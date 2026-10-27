from __future__ import annotations

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import assert_never

from sqlalchemy import and_, not_, or_
from sqlmodel import Session, col, select

from sift import db
from sift.domain import (
    RUNNING,
    Decision,
    ItemStatus,
    LinkState,
    MediaKind,
    Origin,
    ProcessingError,
    Source,
    SourceRef,
    Stage,
)
from sift.items import lifecycle, queries
from sift.items.lifecycle import ALLOWED_FROM, GiveUp, RetryAt, UserAction
from sift.items.views import NO_DECOR, ItemDetail, ItemOutcome, ItemSummary, card_of, to_outcome, to_summary
from sift.llm.schemas import Card, ExtractOutput, ScoreOutput
from sift.media import MediaResult
from sift.models import Goal, ImportLink, Item
from sift.sources.base import FetchResult

_ERROR_LIMIT = 2000


class InvalidTransition(Exception):
    pass


class ClaimLost(Exception):
    pass


class ItemNotFound(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Claim:
    item_id: int
    token: str
    source: Source


@dataclass(frozen=True, slots=True)
class Created:
    item: ItemSummary


@dataclass(frozen=True, slots=True)
class Existing:
    item: ItemSummary


EnqueueResult = Created | Existing


@dataclass(frozen=True, slots=True)
class WorkItem:
    id: int
    source: Source
    canonical_id: str
    clean_url: str
    fetched_at: datetime | None
    media_processed_at: datetime | None
    extracted_at: datetime | None
    scored_at: datetime | None
    media_kind: MediaKind | None
    author_handle: str | None
    caption: str | None
    post_text: str | None
    media_path: Path | None
    thumbnail_path: Path | None
    slide_paths: tuple[Path, ...]
    transcript: str | None
    frame_paths: tuple[Path, ...]
    notes: tuple[str, ...]
    card: Card | None

    @property
    def ref(self) -> SourceRef:
        return SourceRef(self.source, self.canonical_id, self.clean_url)


def _goal_title(s: Session, goal_id: int | None) -> str | None:
    if goal_id is None:
        return None
    goal = s.get(Goal, goal_id)
    return goal.title if goal else None


def _get(s: Session, item_id: int) -> Item:
    row = s.get(Item, item_id)
    if row is None:
        raise ItemNotFound(item_id)
    return row


def _claimed(s: Session, claim: Claim) -> Item:
    row = s.get(Item, claim.item_id)
    if row is None or row.claim_token != claim.token or row.status not in RUNNING:
        raise ClaimLost(claim.item_id)
    return row


def _rel(path: Path | None) -> str | None:
    return None if path is None else str(path)


def enqueue(ref: SourceRef, raw_url: str, origin: Origin, now: datetime, *, llm_ready: bool) -> EnqueueResult:
    with db.write_session() as s:
        return enqueue_in(s, ref, raw_url, origin, now, llm_ready=llm_ready)


def enqueue_in(
    s: Session, ref: SourceRef, raw_url: str, origin: Origin, now: datetime, *, llm_ready: bool
) -> EnqueueResult:
    ready = queries.readiness(s, llm_ready=llm_ready)
    existing = s.exec(select(Item).where(Item.source == ref.source, Item.canonical_id == ref.canonical_id)).first()
    if existing is not None:
        return Existing(queries.summary_in(s, existing, ready))
    row = Item(
        source=ref.source,
        canonical_id=ref.canonical_id,
        url=raw_url,
        clean_url=ref.clean_url,
        origin_channel=origin.channel,
        origin_reply_to=origin.reply_to,
        received_at=now,
    )
    s.add(row)
    s.flush()
    return Created(to_summary(row, None, ready, NO_DECOR))


def claim_next(
    now: datetime,
    *,
    fetch_blocked: Collection[Source] = (),
    llm_ready: bool = True,
    goals_ready: bool = True,
    only: int | None = None,
) -> Claim | None:
    with db.write_session() as s:
        q = select(Item).where(
            Item.status == ItemStatus.queued,
            or_(col(Item.next_attempt_at).is_(None), col(Item.next_attempt_at) <= now),
        )
        if fetch_blocked:
            q = q.where(not_(and_(col(Item.fetched_at).is_(None), col(Item.source).in_(list(fetch_blocked)))))
        if not llm_ready:
            q = q.where(col(Item.media_processed_at).is_(None))
        if not goals_ready:
            q = q.where(col(Item.extracted_at).is_(None))
        if only is not None:
            q = q.where(Item.id == only)
        row = s.exec(q.order_by(col(Item.received_at), col(Item.id)).limit(1)).first()
        if row is None:
            return None
        stage = lifecycle.next_stage(row)
        assert stage is not None, "queued item with nothing left to do"
        assert row.id is not None
        row.status = lifecycle.running_status(stage)
        row.claim_token = uuid.uuid4().hex
        row.claimed_at = now
        row.attempts += 1
        row.next_attempt_at = None
        return Claim(row.id, row.claim_token, row.source)


def load(claim: Claim) -> WorkItem:
    with db.read_session() as s:
        row = _claimed(s, claim)
        assert row.id is not None
        return WorkItem(
            id=row.id,
            source=row.source,
            canonical_id=row.canonical_id,
            clean_url=row.clean_url,
            fetched_at=row.fetched_at,
            media_processed_at=row.media_processed_at,
            extracted_at=row.extracted_at,
            scored_at=row.scored_at,
            media_kind=row.media_kind,
            author_handle=row.author_handle,
            caption=row.caption,
            post_text=row.post_text,
            media_path=Path(row.media_path) if row.media_path else None,
            thumbnail_path=Path(row.thumbnail_path) if row.thumbnail_path else None,
            slide_paths=tuple(Path(p) for p in row.slide_paths or []),
            transcript=row.transcript,
            frame_paths=tuple(Path(p) for p in row.frame_paths or []),
            notes=tuple(row.fetch_notes or []),
            card=card_of(row),
        )


def _advance(row: Item) -> None:
    row.attempts = 1
    row.last_error = None


@dataclass(frozen=True, slots=True)
class RemovedAsDuplicateOf:
    item_id: int


def rekey(claim: Claim, ref: SourceRef) -> RemovedAsDuplicateOf | None:
    with db.write_session() as s:
        row = _claimed(s, claim)
        existing = s.exec(
            select(Item.id).where(Item.source == ref.source, Item.canonical_id == ref.canonical_id)
        ).first()
        if existing is None:
            row.canonical_id = ref.canonical_id
            row.clean_url = ref.clean_url
            return None
        for link in s.exec(select(ImportLink).where(ImportLink.item_id == row.id)):
            link.item_id = existing
            link.state = LinkState.duplicate
        s.delete(row)
        return RemovedAsDuplicateOf(existing)


def record_fetch(claim: Claim, result: FetchResult, now: datetime) -> None:
    with db.write_session() as s:
        row = _claimed(s, claim)
        row.media_kind = result.media_kind
        row.author_handle = result.author_handle
        row.caption = result.caption
        row.post_text = result.post_text
        row.raw_metadata = result.raw_metadata
        row.media_path = _rel(result.video_path)
        row.thumbnail_path = _rel(result.thumbnail_path)
        row.slide_paths = [str(p) for p in result.slide_paths] or None
        row.fetch_notes = list(result.notes.lines)
        row.status_reason = " ".join(result.notes.lines) or None
        row.fetched_at = now
        _advance(row)


def record_media(claim: Claim, result: MediaResult, now: datetime, *, media_deleted: bool) -> None:
    with db.write_session() as s:
        row = _claimed(s, claim)
        row.transcript = result.transcript
        row.frame_paths = [str(p) for p in result.frame_paths]
        row.media_processed_at = now
        if media_deleted:
            row.media_path = None
        row.status = ItemStatus.processing
        _advance(row)


def record_extraction(claim: Claim, out: ExtractOutput, model: str, now: datetime) -> None:
    with db.write_session() as s:
        row = _claimed(s, claim)
        card = out.card
        row.item_type = card.item_type
        row.title = card.title
        row.summary = card.summary
        row.next_action = card.next_action
        row.details = card.details.model_dump(mode="json")
        row.ocr_text = out.on_screen_text
        row.extract_model = model
        row.extracted_at = now
        _advance(row)


def record_score(claim: Claim, out: ScoreOutput, model: str, threshold: int, now: datetime) -> ItemOutcome:
    with db.write_session() as s:
        row = _claimed(s, claim)
        verdict = lifecycle.threshold_decision(out.relevance_score, threshold)
        row.relevance_score = out.relevance_score
        row.matched_goal_id = out.matched_goal_id
        row.relevance_reason = out.relevance_reason
        row.model_decision = out.decision
        row.threshold_decision = verdict
        row.score_model = model
        row.scored_at = now
        row.status = lifecycle.disposition(verdict, row.user_override)
        notes = " ".join(row.fetch_notes or [])
        row.status_reason = (out.relevance_reason if row.status is ItemStatus.archived else notes) or None
        row.decided_at = now
        row.processed_at = row.processed_at or now
        row.claim_token = None
        row.failure_kind = None
        row.last_error = None
        row.attempts = 0
        return to_outcome(row, _goal_title(s, row.matched_goal_id))


def record_failure(
    claim: Claim, err: ProcessingError, now: datetime, *, detail: str | None = None
) -> ItemOutcome | None:
    with db.write_session() as s:
        row = _claimed(s, claim)
        row.claim_token = None
        row.last_error = (detail or err.message)[:_ERROR_LIMIT]
        match lifecycle.failure_verdict(err, row.attempts, now):
            case RetryAt(at=at):
                row.status = ItemStatus.queued
                row.next_attempt_at = at
                return None
            case GiveUp():
                row.status = ItemStatus.failed
                row.failure_kind = err.kind
                row.status_reason = err.message
                return to_outcome(row, None)


def release(claim: Claim) -> None:
    with db.write_session() as s:
        row = _claimed(s, claim)
        row.status = ItemStatus.queued
        row.claim_token = None
        row.attempts = 0


def reset_stuck(now: datetime) -> tuple[int, int]:
    requeued = failed = 0
    with db.write_session() as s:
        for row in s.exec(select(Item).where(col(Item.status).in_(list(RUNNING)))).all():
            row.claim_token = None
            stage = lifecycle.next_stage(row) or Stage.score
            if row.attempts >= lifecycle.MAX_ATTEMPTS:
                row.status = ItemStatus.failed
                row.failure_kind = lifecycle.STAGE_FAILURE[stage]
                row.status_reason = f"The {stage} stage was interrupted {row.attempts} times."
                failed += 1
            else:
                row.status = ItemStatus.queued
                requeued += 1
    return requeued, failed


def _clear_analysis(row: Item) -> None:
    for name in (
        "extracted_at",
        "extract_model",
        "item_type",
        "title",
        "summary",
        "details",
        "next_action",
        "ocr_text",
        "scored_at",
        "score_model",
        "relevance_score",
        "matched_goal_id",
        "relevance_reason",
        "model_decision",
        "threshold_decision",
    ):
        setattr(row, name, None)


def apply_action(item_id: int, action: UserAction, now: datetime, *, llm_ready: bool) -> ItemDetail:
    with db.write_session() as s:
        row = _get(s, item_id)
        if action not in lifecycle.allowed_actions(row.status, scored=row.scored_at is not None):
            if row.status in ALLOWED_FROM[action]:
                raise InvalidTransition(f"cannot {action} an item that was never scored; use Reprocess")
            raise InvalidTransition(f"cannot {action} an item that is {row.status}")
        match action:
            case UserAction.archive if row.status is ItemStatus.failed:
                row.status = ItemStatus.archived
                row.decided_at = now
            case UserAction.keep | UserAction.archive:
                row.user_override = Decision(action.value)
                row.overridden_at = now
                row.status = lifecycle.disposition(row.threshold_decision or Decision.archive, row.user_override)
                row.status_reason = None if row.status is ItemStatus.kept else "Archived by you"
                row.decided_at = now
            case UserAction.done:
                row.status = ItemStatus.done
                row.done_at = now
            case UserAction.undone:
                row.status = lifecycle.disposition(row.threshold_decision or Decision.archive, row.user_override)
                row.done_at = None
            case UserAction.retry:
                row.status = ItemStatus.queued
                row.attempts = 0
                row.failure_kind = None
                row.last_error = None
                row.next_attempt_at = None
                row.status_reason = None
            case UserAction.reprocess:
                _clear_analysis(row)
                row.status = ItemStatus.queued
                row.attempts = 0
                row.done_at = None
                row.failure_kind = None
                row.last_error = None
                row.status_reason = None
            case _:
                assert_never(action)
        row.last_interacted_at = now
        s.flush()
        return queries.detail_in(s, row, queries.readiness(s, llm_ready=llm_ready))
