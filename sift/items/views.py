from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field

from sift.domain import RUNNING, Channel, Decision, FailureKind, ItemStatus, ItemType, MediaKind, Source, Stage
from sift.items.lifecycle import HINTS, UserAction, allowed_actions, next_stage
from sift.llm.schemas import Card, parse_card
from sift.models import Item

WaitingFor = Literal["llm", "goals"]


@dataclass(frozen=True, slots=True)
class Readiness:
    llm: bool
    goals: bool


def display_title(title: str | None, author_handle: str | None, source: Source) -> str:
    if title:
        return title
    who = f"@{author_handle}" if author_handle else source.value.title()
    return f"{who} post"


class TopicRef(BaseModel):
    id: int
    name: str


class ItemRef(BaseModel):
    id: int
    title: str


class ItemOrganization(BaseModel):
    gist: str
    key_points: list[str]
    labels: list[str]
    topic: TopicRef | None = Field(description="The topic the post is on: your move if you made one, else Sift's pick.")
    sift_topic: TopicRef | None = Field(description="Sift's own pick, shown as the default in the topic picker.")
    topic_chosen_by: Literal["sift", "you"] | None
    covered_by: ItemRef | None = Field(description="The post that says everything this one does, per the brief.")
    covers: list[ItemRef]
    cited_in: int = Field(description="Points of the topic's brief that cite this post.")


@dataclass(frozen=True, slots=True)
class Decor:
    gist: str | None
    labels: tuple[str, ...]
    topic: TopicRef | None
    covered_by: ItemRef | None


NO_DECOR = Decor(None, (), None, None)


class ItemSummary(BaseModel):
    id: int
    source: Source
    url: str
    origin_channel: Channel
    status: ItemStatus
    state_label: str
    waiting_for: WaitingFor | None
    status_reason: str | None
    received_at: datetime
    author_handle: str | None
    thumbnail_url: str | None
    media_kind: MediaKind | None
    item_type: ItemType | None
    title: str | None
    summary: str | None
    next_action: str | None
    relevance_score: int | None
    matched_goal_id: int | None
    matched_goal_title: str | None
    user_override: Decision | None
    threshold_decision: Decision | None
    stage: Stage | None
    failure_kind: FailureKind | None
    failure_hint: str | None
    next_attempt_at: datetime | None
    last_error: str | None
    actions: list[UserAction]

    in_motion: bool

    gist: str | None = Field(description="One-line takeaway; null until the post is organized.")
    labels: list[str]
    topic: TopicRef | None
    covered_by: ItemRef | None = Field(
        description="Set whenever another post covers this one; the SPA nests the row only when the cover is listed."
    )

    @computed_field
    @property
    def display_title(self) -> str:
        return display_title(self.title, self.author_handle, self.source)


class ItemDetail(ItemSummary):
    card: Card | None
    relevance_reason: str | None
    model_decision: Decision | None
    caption: str | None
    post_text: str | None
    transcript: str | None
    ocr_text: str | None
    attempts: int
    extract_model: str | None
    score_model: str | None
    processed_at: datetime | None
    done_at: datetime | None
    organization: ItemOrganization | None


class KeptOutcome(BaseModel):
    kind: Literal["kept"] = "kept"
    item_id: int
    origin_channel: Channel
    origin_reply_to: dict[str, Any] | None
    title: str
    item_type: ItemType
    matched_goal_title: str | None
    next_action: str | None


class ArchivedOutcome(BaseModel):
    kind: Literal["archived"] = "archived"
    item_id: int
    origin_channel: Channel
    origin_reply_to: dict[str, Any] | None
    title: str
    reason: str


class FailedOutcome(BaseModel):
    kind: Literal["failed"] = "failed"
    item_id: int
    origin_channel: Channel
    origin_reply_to: dict[str, Any] | None
    url: str
    failure_kind: FailureKind
    reason: str
    hint: str


ItemOutcome = KeptOutcome | ArchivedOutcome | FailedOutcome


_WAITING_LABELS: dict[WaitingFor, str] = {"llm": "Waiting for LLM", "goals": "Waiting for goals"}


def waiting_for(row: Item, ready: Readiness) -> WaitingFor | None:
    if row.status is not ItemStatus.queued or row.next_attempt_at is not None:
        return None
    match next_stage(row):
        case Stage.extract | Stage.score if not ready.llm:
            return "llm"
        case Stage.score if not ready.goals:
            return "goals"
        case _:
            return None


def state_label(row: Item, ready: Readiness) -> str:
    if (waiting := waiting_for(row, ready)) is not None:
        return _WAITING_LABELS[waiting]
    match row.status:
        case ItemStatus.queued if row.next_attempt_at is not None:
            return "Retrying soon"
        case ItemStatus.queued:
            return "Queued"
        case ItemStatus.fetching:
            return "Downloading" if row.fetched_at is None else "Transcribing"
        case ItemStatus.processing:
            return "Extracting" if row.extracted_at is None else "Scoring"
        case ItemStatus.kept:
            return "Kept"
        case ItemStatus.archived:
            return "Archived"
        case ItemStatus.done:
            return "Done"
        case ItemStatus.failed:
            return "Failed"


def _summary_fields(row: Item, goal_title: str | None, ready: Readiness, decor: Decor) -> dict[str, Any]:
    assert row.id is not None
    waiting = waiting_for(row, ready)
    return {
        "id": row.id,
        "source": row.source,
        "url": row.url,
        "origin_channel": row.origin_channel,
        "status": row.status,
        "state_label": state_label(row, ready),
        "waiting_for": waiting,
        "in_motion": row.status in RUNNING or (row.status is ItemStatus.queued and waiting is None),
        "status_reason": row.status_reason,
        "received_at": row.received_at,
        "author_handle": row.author_handle,
        "thumbnail_url": f"/api/items/{row.id}/thumbnail" if row.thumbnail_path else None,
        "media_kind": row.media_kind,
        "item_type": row.item_type,
        "title": row.title,
        "summary": row.summary,
        "next_action": row.next_action,
        "relevance_score": row.relevance_score,
        "matched_goal_id": row.matched_goal_id,
        "matched_goal_title": goal_title,
        "user_override": row.user_override,
        "threshold_decision": row.threshold_decision,
        "stage": next_stage(row),
        "failure_kind": row.failure_kind if row.status is ItemStatus.failed else None,
        "failure_hint": HINTS[row.failure_kind] if row.status is ItemStatus.failed and row.failure_kind else None,
        "next_attempt_at": row.next_attempt_at,
        "last_error": row.last_error,
        "actions": allowed_actions(row.status, scored=row.scored_at is not None),
        "gist": decor.gist,
        "labels": list(decor.labels),
        "topic": decor.topic,
        "covered_by": decor.covered_by,
    }


def to_summary(row: Item, goal_title: str | None, ready: Readiness, decor: Decor) -> ItemSummary:
    return ItemSummary(**_summary_fields(row, goal_title, ready, decor))


def card_of(row: Item) -> Card | None:
    if row.extracted_at is None or row.item_type is None or row.title is None or row.details is None:
        return None
    return parse_card(row.item_type, row.title, row.summary, row.next_action, row.details)


def to_detail(row: Item, goal_title: str | None, ready: Readiness, organization: ItemOrganization | None) -> ItemDetail:
    o = organization
    decor = Decor(o.gist, tuple(o.labels), o.topic, o.covered_by) if o else NO_DECOR
    return ItemDetail(
        **_summary_fields(row, goal_title, ready, decor),
        card=card_of(row),
        relevance_reason=row.relevance_reason,
        model_decision=row.model_decision,
        caption=row.caption,
        post_text=row.post_text,
        transcript=row.transcript,
        ocr_text=row.ocr_text,
        attempts=row.attempts,
        extract_model=row.extract_model,
        score_model=row.score_model,
        processed_at=row.processed_at,
        done_at=row.done_at,
        organization=organization,
    )


def to_outcome(row: Item, goal_title: str | None) -> ItemOutcome:
    assert row.id is not None
    base: dict[str, Any] = {
        "item_id": row.id,
        "origin_channel": row.origin_channel,
        "origin_reply_to": row.origin_reply_to,
    }
    if row.status is ItemStatus.failed:
        kind = row.failure_kind
        assert kind is not None, "ck_failed_has_kind"
        return FailedOutcome(
            **base, url=row.url, failure_kind=kind, reason=row.status_reason or "Failed", hint=HINTS[kind]
        )
    title = row.title or "Untitled"
    if row.status is ItemStatus.kept:
        return KeptOutcome(
            **base,
            title=title,
            item_type=row.item_type or ItemType.other,
            matched_goal_title=goal_title,
            next_action=row.next_action,
        )
    return ArchivedOutcome(**base, title=title, reason=row.relevance_reason or "Not relevant to your goals")
