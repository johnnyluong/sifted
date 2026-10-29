from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, computed_field

from sift.domain import RUNNING, Channel, Decision, FailureKind, ItemStatus, ItemType, MediaKind, Source, Stage
from sift.items.lifecycle import (
    HINTS,
    UserAction,
    allowed_actions,
    can_delete,
    can_set_wishlist,
    finished,
    next_stage,
    on_wishlist_shelf,
    takes_keep_reason,
)
from sift.llm.schemas import Card, ProductCard, parse_card
from sift.models import Item
from sift.sources import image

log = logging.getLogger(__name__)

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


class ProductFacts(BaseModel):
    name: str
    price: str | None
    link: str | None


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
    can_delete: bool = Field(description="Delete applies now: only an archived post can be deleted.")
    wishlist: bool = Field(
        description="On the Wishlist shelf: kept even when it serves no goal, and Done reads Bought."
    )
    wishlist_post: bool = Field(
        description="On the wishlist by the extracted flag or your add, in any status; done, it reads Bought."
    )
    product: ProductFacts | None = Field(description="Name, price and link from a product card.")

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


class KeepReason(BaseModel):
    goal_id: int | None = Field(description="The goal you kept it for; null when it fits none of your goals.")
    goal_title: str | None
    note: str | None
    at: datetime


def keep_reason_of(row: Item, goal_title: str | None) -> KeepReason | None:
    if row.keep_reason_at is None:
        return None
    return KeepReason(goal_id=row.keep_goal_id, goal_title=goal_title, note=row.keep_note, at=row.keep_reason_at)


def keep_reason_text(goal_title: str | None, note: str | None) -> str:
    fit = f'it serves their goal "{goal_title}"' if goal_title else "it fits none of their goals"
    return f'{fit}; in their words, "{note}"' if note else fit


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
    can_wishlist: bool = Field(description="Add to wishlist or Remove from wishlist applies now.")
    wishlist_override: bool | None = Field(
        description="Your hand choice: true added, false removed, null follows the extracted flag."
    )
    asks_keep_reason: bool = Field(description="You kept it after the filter archived it, so it takes a reason.")
    keep_reason: KeepReason | None = Field(description="Why you kept a post the filter archived, once you say.")
    images: list[str] = Field(description="An image post's stored images in reading order; empty for other posts.")


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
_RUNNING_LABELS: dict[Stage | None, str] = {
    Stage.fetch: "Downloading",
    Stage.media: "Transcribing",
    Stage.extract: "Extracting",
    Stage.score: "Scoring",
    None: "Saving",
}


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
        case ItemStatus.fetching | ItemStatus.processing:
            return _RUNNING_LABELS[next_stage(row)]
        case ItemStatus.kept if row.wishlist:
            return "On wishlist"
        case ItemStatus.kept:
            return "Kept"
        case ItemStatus.archived:
            return "Archived"
        case ItemStatus.done if row.wishlist:
            return "Bought"
        case ItemStatus.done:
            return "Done"
        case ItemStatus.failed:
            return "Failed"


def _summary_fields(
    row: Item, goal_title: str | None, ready: Readiness, decor: Decor, product: ProductFacts | None
) -> dict[str, Any]:
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
        "actions": allowed_actions(row.status, finished=finished(row)),
        "can_delete": can_delete(row.status),
        "wishlist": on_wishlist_shelf(row.status, wishlist=row.wishlist),
        "wishlist_post": row.wishlist,
        "product": product,
        "gist": decor.gist,
        "labels": list(decor.labels),
        "topic": decor.topic,
        "covered_by": decor.covered_by,
    }


def to_summary(row: Item, goal_title: str | None, ready: Readiness, decor: Decor) -> ItemSummary:
    return ItemSummary(**_summary_fields(row, goal_title, ready, decor, product_facts(row)))


def card_of(row: Item) -> Card | None:
    if row.extracted_at is None or row.item_type is None or row.title is None or row.details is None:
        return None
    return parse_card(row.item_type, row.title, row.summary, row.next_action, row.details)


def _facts(card: Card | None) -> ProductFacts | None:
    if not isinstance(card, ProductCard):
        return None
    return ProductFacts(name=card.details.name, price=card.details.price, link=card.details.link)


def stored_card(row: Item) -> Card | None:
    try:
        return card_of(row)
    except ValidationError:
        # One stale stored card must not fail every list or action that touches its row.
        log.debug("item %s has a card that no longer parses", row.id)
        return None


def product_facts(row: Item) -> ProductFacts | None:
    return _facts(stored_card(row)) if row.item_type is ItemType.product else None


def to_detail(
    row: Item,
    goal_title: str | None,
    ready: Readiness,
    organization: ItemOrganization | None,
    keep_reason: KeepReason | None,
) -> ItemDetail:
    o = organization
    decor = Decor(o.gist, tuple(o.labels), o.topic, o.covered_by) if o else NO_DECOR
    card = stored_card(row)
    return ItemDetail(
        **_summary_fields(row, goal_title, ready, decor, _facts(card)),
        card=card,
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
        can_wishlist=can_set_wishlist(row.status, extracted=row.extracted_at is not None),
        wishlist_override=row.wishlist_override,
        asks_keep_reason=takes_keep_reason(row.user_override, row.threshold_decision),
        keep_reason=keep_reason,
        images=[image.UPLOADS_PATH + name for name in image.upload_names(row.clean_url)]
        if row.source is Source.image
        else [],
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
    return ArchivedOutcome(**base, title=title, reason=row.status_reason or "Not relevant to your goals")
