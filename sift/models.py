from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Column, Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from sift.db import UTCDateTime
from sift.domain import (
    Channel,
    Decision,
    DigestRole,
    FailureKind,
    GoalCategory,
    ItemStatus,
    ItemType,
    LinkState,
    MediaKind,
    PauseReason,
    Source,
)

PROFILE_ID = 1


def _ts(*, nullable: bool = True) -> Any:
    return Field(default=None, sa_column=Column(UTCDateTime(), nullable=nullable))


def _json(*, nullable: bool = True) -> Any:
    return Field(default=None, sa_column=Column(JSON, nullable=nullable))


def _json_or_null(*, nullable: bool = True) -> Any:
    # Plain JSON stores Python None as the text 'null', which IS NULL checks cannot see.
    return Field(default=None, sa_column=Column(JSON(none_as_null=True), nullable=nullable))


class Item(SQLModel, table=True):
    __tablename__ = "items"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("source", "canonical_id", name="uq_items_source_canonical"),
        Index("ix_items_claim", "status", "next_attempt_at", "received_at"),
        CheckConstraint(
            "status NOT IN ('fetching','processing') OR claim_token IS NOT NULL",
            name="ck_running_has_claim",
        ),
        CheckConstraint("status != 'failed' OR failure_kind IS NOT NULL", name="ck_failed_has_kind"),
        CheckConstraint(
            "extracted_at IS NULL OR (item_type IS NOT NULL AND title IS NOT NULL AND details IS NOT NULL)",
            name="ck_extract_complete",
        ),
        CheckConstraint(
            "scored_at IS NULL OR (relevance_score IS NOT NULL AND threshold_decision IS NOT NULL)",
            name="ck_score_complete",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)

    source: Source
    canonical_id: str
    url: str
    clean_url: str
    origin_channel: Channel
    origin_reply_to: dict[str, Any] | None = _json()
    received_at: datetime = _ts(nullable=False)

    status: ItemStatus = ItemStatus.queued
    status_reason: str | None = None
    failure_kind: FailureKind | None = None
    attempts: int = 0
    next_attempt_at: datetime | None = _ts()
    last_error: str | None = None
    claim_token: str | None = None
    claimed_at: datetime | None = _ts()

    fetched_at: datetime | None = _ts()
    media_kind: MediaKind | None = None
    author_handle: str | None = None
    caption: str | None = None
    post_text: str | None = None
    raw_metadata: dict[str, Any] | None = _json()
    media_path: str | None = None
    thumbnail_path: str | None = None
    slide_paths: list[str] | None = _json_or_null()
    fetch_notes: list[str] | None = _json()

    media_processed_at: datetime | None = _ts()
    transcript: str | None = None
    frame_paths: list[str] | None = _json()

    extracted_at: datetime | None = _ts()
    extract_model: str | None = None
    item_type: ItemType | None = None
    title: str | None = None
    summary: str | None = None
    details: dict[str, Any] | None = _json()
    next_action: str | None = None
    ocr_text: str | None = None

    scored_at: datetime | None = _ts()
    score_model: str | None = None
    relevance_score: int | None = None
    matched_goal_id: int | None = Field(default=None, foreign_key="goals.id")
    relevance_reason: str | None = None
    model_decision: Decision | None = None
    threshold_decision: Decision | None = None

    user_override: Decision | None = None
    overridden_at: datetime | None = _ts()
    last_interacted_at: datetime | None = _ts()
    decided_at: datetime | None = _ts()
    processed_at: datetime | None = _ts()
    done_at: datetime | None = _ts()


class Goal(SQLModel, table=True):
    __tablename__ = "goals"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    title: str
    description: str = ""
    category: GoalCategory = GoalCategory.other
    active: bool = True
    created_at: datetime = _ts(nullable=False)
    updated_at: datetime = _ts(nullable=False)


class Profile(SQLModel, table=True):
    __tablename__ = "profile"  # pyright: ignore[reportAssignmentType]

    id: int = Field(default=PROFILE_ID, primary_key=True)
    values_text: str = ""
    setup_answers: list[dict[str, Any]] | None = _json_or_null()
    setup_at: datetime | None = _ts()
    updated_at: datetime = _ts(nullable=False)


class Digest(SQLModel, table=True):
    __tablename__ = "digests"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    period_start: datetime = _ts(nullable=False)
    period_end: datetime = _ts(nullable=False)
    created_at: datetime = _ts(nullable=False)
    opening: str | None = None
    model: str
    sent_at: datetime | None = _ts()


class DigestEntry(SQLModel, table=True):
    __tablename__ = "digest_entries"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        Index("ix_digest_entries_item", "item_id"),
        UniqueConstraint("digest_id", "position", name="uq_digest_entries_position"),
    )

    digest_id: int = Field(foreign_key="digests.id", primary_key=True)
    item_id: int = Field(foreign_key="items.id", primary_key=True)
    position: int
    role: DigestRole
    why: str | None = None
    next_action: str | None = None
    line: str | None = None


class Import(SQLModel, table=True):
    __tablename__ = "imports"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    filename: str
    created_at: datetime = _ts(nullable=False)
    updated_at: datetime = _ts(nullable=False)
    files_read: list[str] = _json(nullable=False)
    files_skipped_large: list[str] = _json(nullable=False)
    files_skipped_budget: list[str] = _json(nullable=False)
    unsupported: list[str] = _json(nullable=False)
    unsupported_count: int = 0
    max_posts: int | None = None
    started_at: datetime | None = _ts()
    paused_at: datetime | None = _ts()
    pause_reason: PauseReason | None = None
    resumed_at: datetime | None = _ts()
    cancelled_at: datetime | None = _ts()
    next_release_at: datetime | None = _ts()


class ImportLink(SQLModel, table=True):
    __tablename__ = "import_links"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("import_id", "source", "canonical_id", name="uq_import_links_ref"),
        Index("ix_import_links_drip", "state", "import_id", "saved_at"),
        Index("ix_import_links_released", "released_at"),
        CheckConstraint(
            "state != 'released' OR (item_id IS NOT NULL AND released_at IS NOT NULL)", name="ck_released_has_item"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    import_id: int = Field(foreign_key="imports.id")
    source: Source
    canonical_id: str
    clean_url: str
    url: str
    saved_at: datetime | None = _ts()
    state: LinkState = LinkState.found
    item_id: int | None = Field(default=None, foreign_key="items.id")
    released_at: datetime | None = _ts()


class Topic(SQLModel, table=True):
    __tablename__ = "topics"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("slug", name="uq_topics_slug"),
        CheckConstraint("merged_into_id IS NULL OR dissolved_at IS NULL", name="ck_one_tombstone"),
        CheckConstraint(
            "brief IS NULL OR (brief_at IS NOT NULL AND brief_basis IS NOT NULL AND brief_model IS NOT NULL)",
            name="ck_brief_whole",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    name: str
    slug: str
    description: str = ""
    created_at: datetime = _ts(nullable=False)
    updated_at: datetime = _ts(nullable=False)
    merged_into_id: int | None = Field(default=None, foreign_key="topics.id")
    dissolved_at: datetime | None = _ts()

    brief: dict[str, Any] | None = _json_or_null()
    brief_at: datetime | None = _ts()
    brief_model: str | None = None
    brief_basis: str | None = None
    pending_basis: str | None = None
    pending_since: datetime | None = _ts()
    dirty_since: datetime | None = _ts()
    brief_requested_at: datetime | None = _ts()


class Outline(SQLModel, table=True):
    __tablename__ = "outlines"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        Index("ix_outlines_topic", "topic_id"),
        Index("ix_outlines_override", "topic_override_id"),
    )

    item_id: int = Field(foreign_key="items.id", primary_key=True)
    extracted_at: datetime = _ts(nullable=False)
    outlined_at: datetime = _ts(nullable=False)
    model: str
    gist: str
    key_points: list[str] = _json_or_null(nullable=False)
    labels: list[str] = _json_or_null(nullable=False)
    topic_id: int | None = Field(default=None, foreign_key="topics.id")
    needs_topic: bool = False
    topic_override_id: int | None = Field(default=None, foreign_key="topics.id")
    moved_at: datetime | None = _ts()


class OutlineLabel(SQLModel, table=True):
    __tablename__ = "outline_labels"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (Index("ix_outline_labels_label", "label"),)

    item_id: int = Field(foreign_key="outlines.item_id", primary_key=True)
    label: str = Field(primary_key=True)


class TopicMergeSuggestion(SQLModel, table=True):
    __tablename__ = "topic_merge_suggestions"  # pyright: ignore[reportAssignmentType]

    source_id: int = Field(foreign_key="topics.id", primary_key=True)
    into_id: int = Field(foreign_key="topics.id", primary_key=True)
    suggested_at: datetime = _ts(nullable=False)
    dismissed_at: datetime | None = _ts()
