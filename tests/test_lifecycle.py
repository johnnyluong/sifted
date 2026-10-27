from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sift.domain import Decision, FailureKind, ItemStatus, ProcessingError, Stage
from sift.items import lifecycle
from sift.items.lifecycle import GiveUp, RetryAt, UserAction

NOW = datetime(2026, 10, 18, tzinfo=UTC)


@dataclass
class _row:
    fetched_at: datetime | None = None
    media_processed_at: datetime | None = None
    extracted_at: datetime | None = None
    scored_at: datetime | None = None


def test_next_stage_follows_checkpoints() -> None:
    assert lifecycle.next_stage(_row()) is Stage.fetch
    assert lifecycle.next_stage(_row(fetched_at=NOW)) is Stage.media
    assert lifecycle.next_stage(_row(fetched_at=NOW, media_processed_at=NOW)) is Stage.extract
    assert lifecycle.next_stage(_row(fetched_at=NOW, media_processed_at=NOW, extracted_at=NOW)) is Stage.score
    assert lifecycle.next_stage(_row(fetched_at=NOW, media_processed_at=NOW, extracted_at=NOW, scored_at=NOW)) is None


def test_failure_verdict_backs_off_then_gives_up() -> None:
    err = ProcessingError(FailureKind.download_failed, "429", retryable=True)
    assert lifecycle.failure_verdict(err, 1, NOW) == RetryAt(NOW + timedelta(minutes=1))
    assert lifecycle.failure_verdict(err, 2, NOW) == RetryAt(NOW + timedelta(minutes=5))
    assert lifecycle.failure_verdict(err, 3, NOW) == RetryAt(NOW + timedelta(minutes=25))
    assert lifecycle.failure_verdict(err, 4, NOW) == GiveUp()


def test_non_retryable_gives_up_at_once() -> None:
    err = ProcessingError(FailureKind.unsupported_url, "private", retryable=False)
    assert lifecycle.failure_verdict(err, 1, NOW) == GiveUp()


def test_threshold_is_inclusive() -> None:
    assert lifecycle.threshold_decision(60, 60) is Decision.keep
    assert lifecycle.threshold_decision(59, 60) is Decision.archive


def test_override_beats_threshold() -> None:
    assert lifecycle.disposition(Decision.archive, None) is ItemStatus.archived
    assert lifecycle.disposition(Decision.archive, Decision.keep) is ItemStatus.kept
    assert lifecycle.disposition(Decision.keep, Decision.archive) is ItemStatus.archived


def test_running_items_accept_no_action() -> None:
    for status in (ItemStatus.queued, ItemStatus.fetching, ItemStatus.processing):
        assert lifecycle.allowed_actions(status, scored=False) == []
    assert UserAction.keep in lifecycle.allowed_actions(ItemStatus.archived, scored=True)
    assert lifecycle.allowed_actions(ItemStatus.failed, scored=False) == [UserAction.archive, UserAction.retry]


def test_an_archived_post_that_was_never_scored_can_only_be_reprocessed() -> None:
    assert lifecycle.allowed_actions(ItemStatus.archived, scored=False) == [UserAction.reprocess]


def test_every_failure_kind_has_a_hint() -> None:
    assert set(lifecycle.HINTS) == set(FailureKind)
