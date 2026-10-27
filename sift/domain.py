from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Source(StrEnum):
    instagram = "instagram"
    threads = "threads"


class ItemStatus(StrEnum):
    queued = "queued"
    fetching = "fetching"
    processing = "processing"
    kept = "kept"
    archived = "archived"
    done = "done"
    failed = "failed"


RUNNING: frozenset[ItemStatus] = frozenset({ItemStatus.fetching, ItemStatus.processing})


class Stage(StrEnum):
    fetch = "fetch"
    media = "media"
    extract = "extract"
    score = "score"


class FailureKind(StrEnum):
    download_failed = "download_failed"
    post_unavailable = "post_unavailable"
    transcription_failed = "transcription_failed"
    llm_failed = "llm_failed"
    unsupported_url = "unsupported_url"


class Decision(StrEnum):
    keep = "keep"
    archive = "archive"


class MediaKind(StrEnum):
    video = "video"
    image = "image"
    text = "text"


class ItemType(StrEnum):
    place = "place"
    recipe = "recipe"
    playbook = "playbook"
    idea = "idea"
    product = "product"
    other = "other"


class GoalCategory(StrEnum):
    personal = "personal"
    professional = "professional"
    entrepreneurial = "entrepreneurial"
    other = "other"


class DigestRole(StrEnum):
    pick = "pick"
    new = "new"
    carryover = "carryover"


SHOWN_ROLES: frozenset[DigestRole] = frozenset({DigestRole.pick, DigestRole.new})


class Channel(StrEnum):
    web = "web"
    cli = "cli"
    api = "api"
    telegram = "telegram"
    export = "export"


QUIET_CHANNELS: frozenset[Channel] = frozenset({Channel.export})


class LinkState(StrEnum):
    found = "found"
    waiting = "waiting"
    released = "released"
    duplicate = "duplicate"
    skipped = "skipped"


class ImportAction(StrEnum):
    start = "start"
    pause = "pause"
    resume = "resume"
    cancel = "cancel"


class ImportPhase(StrEnum):
    preview = "preview"
    running = "running"
    paused = "paused"
    finished = "finished"
    cancelled = "cancelled"


class PauseReason(StrEnum):
    user = "user"
    download_failures = "download_failures"


class Hold(StrEnum):
    """Why a running import is not releasing a post right now. The SPA owns the wording."""

    in_flight = "in_flight"
    daily_cap = "daily_cap"
    gap = "gap"


class BriefState(StrEnum):
    none = "none"
    fresh = "fresh"
    stale = "stale"
    writing = "writing"


@dataclass(frozen=True, slots=True)
class PointRef:
    item_id: int
    index: int


@dataclass(frozen=True, slots=True)
class Origin:
    channel: Channel
    reply_to: dict[str, Any] | None = None


SHARE_PREFIX = "share-"


@dataclass(frozen=True, slots=True)
class SourceRef:
    source: Source
    canonical_id: str
    clean_url: str

    @property
    def is_share(self) -> bool:
        return self.canonical_id.startswith(SHARE_PREFIX)


class ProcessingError(Exception):
    def __init__(self, kind: FailureKind, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class Notes:
    lines: tuple[str, ...] = field(default=())
