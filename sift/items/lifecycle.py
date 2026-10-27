from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal, Protocol

from sift.domain import Decision, FailureKind, ItemStatus, ProcessingError, Stage

MAX_ATTEMPTS = 4
BACKOFF_BASE = timedelta(minutes=1)
BACKOFF_FACTOR = 5


class UserAction(StrEnum):
    keep = "keep"
    archive = "archive"
    done = "done"
    undone = "undone"
    retry = "retry"
    reprocess = "reprocess"


ALLOWED_FROM: dict[UserAction, frozenset[ItemStatus]] = {
    UserAction.keep: frozenset({ItemStatus.archived}),
    UserAction.archive: frozenset({ItemStatus.kept, ItemStatus.failed}),
    UserAction.done: frozenset({ItemStatus.kept, ItemStatus.archived}),
    UserAction.undone: frozenset({ItemStatus.done}),
    UserAction.retry: frozenset({ItemStatus.failed}),
    UserAction.reprocess: frozenset({ItemStatus.kept, ItemStatus.archived, ItemStatus.done}),
}


NEEDS_SCORE: frozenset[UserAction] = frozenset({UserAction.keep, UserAction.done})


def allowed_actions(status: ItemStatus, *, scored: bool) -> list[UserAction]:
    return [a for a, froms in ALLOWED_FROM.items() if status in froms and (scored or a not in NEEDS_SCORE)]


class Checkpoints(Protocol):
    @property
    def fetched_at(self) -> datetime | None: ...
    @property
    def media_processed_at(self) -> datetime | None: ...
    @property
    def extracted_at(self) -> datetime | None: ...
    @property
    def scored_at(self) -> datetime | None: ...


def next_stage(item: Checkpoints) -> Stage | None:
    if item.fetched_at is None:
        return Stage.fetch
    if item.media_processed_at is None:
        return Stage.media
    if item.extracted_at is None:
        return Stage.extract
    if item.scored_at is None:
        return Stage.score
    return None


def running_status(stage: Stage) -> ItemStatus:
    return ItemStatus.fetching if stage in (Stage.fetch, Stage.media) else ItemStatus.processing


STAGE_FAILURE: dict[Stage, FailureKind] = {
    Stage.fetch: FailureKind.download_failed,
    Stage.media: FailureKind.transcription_failed,
    Stage.extract: FailureKind.llm_failed,
    Stage.score: FailureKind.llm_failed,
}

HINTS: dict[FailureKind, str] = {
    FailureKind.download_failed: (
        "If the post was deleted or is private, archive it. Otherwise yt-dlp may need updating "
        "(uv run sift update-tools), or the secondary account's browser cookies may have expired (uv run sift doctor)."
    ),
    FailureKind.post_unavailable: "The post was deleted, or is private to the secondary account. Archive it.",
    FailureKind.transcription_failed: "Check that ffmpeg is installed (uv run sift doctor).",
    FailureKind.llm_failed: "See the reason above. uv run sift doctor checks the API key.",
    FailureKind.unsupported_url: "This kind of post is not supported yet.",
}


@dataclass(frozen=True, slots=True)
class RetryAt:
    at: datetime


@dataclass(frozen=True, slots=True)
class GiveUp:
    pass


FailureVerdict = RetryAt | GiveUp


def failure_verdict(err: ProcessingError, attempts: int, now: datetime) -> FailureVerdict:
    if not err.retryable or attempts >= MAX_ATTEMPTS:
        return GiveUp()
    return RetryAt(now + BACKOFF_BASE * BACKOFF_FACTOR ** max(0, attempts - 1))


def threshold_decision(score: int, threshold: int) -> Decision:
    return Decision.keep if score >= threshold else Decision.archive


def disposition(threshold_dec: Decision, override: Decision | None) -> Literal[ItemStatus.kept, ItemStatus.archived]:
    return ItemStatus.kept if (override or threshold_dec) is Decision.keep else ItemStatus.archived
