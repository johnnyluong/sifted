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
    processed_at: datetime | None = None
    wishlist: bool = False


def test_next_stage_follows_checkpoints() -> None:
    assert lifecycle.next_stage(_row()) is Stage.fetch
    assert lifecycle.next_stage(_row(fetched_at=NOW)) is Stage.media
    assert lifecycle.next_stage(_row(fetched_at=NOW, media_processed_at=NOW)) is Stage.extract
    assert lifecycle.next_stage(_row(fetched_at=NOW, media_processed_at=NOW, extracted_at=NOW)) is Stage.score
    assert lifecycle.next_stage(_row(fetched_at=NOW, media_processed_at=NOW, extracted_at=NOW, scored_at=NOW)) is None


def test_a_wishlist_post_is_finished_once_extracted_and_never_waits_to_be_scored() -> None:
    read = _row(fetched_at=NOW, media_processed_at=NOW, wishlist=True)
    assert lifecycle.next_stage(read) is Stage.extract
    read.extracted_at = NOW
    assert lifecycle.next_stage(read) is None and lifecycle.finished(read)
    read.wishlist = False
    assert lifecycle.next_stage(read) is Stage.score, "off the wishlist before it settles, it goes on to scoring"


def test_a_settled_post_is_finished_whether_or_not_it_has_a_score() -> None:
    settled = _row(fetched_at=NOW, media_processed_at=NOW, extracted_at=NOW, processed_at=NOW)
    assert lifecycle.next_stage(settled) is None and lifecycle.finished(settled)
    settled.processed_at = None
    assert lifecycle.next_stage(settled) is Stage.score, "Reprocess and Retry clear the mark"


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


def _status(threshold: Decision, override: Decision | None, wishlist: bool, by_hand: bool | None) -> ItemStatus:
    return lifecycle.disposition(threshold, override, wishlist=wishlist, wishlist_override=by_hand)


def test_override_beats_threshold() -> None:
    assert _status(Decision.archive, None, False, None) is ItemStatus.archived
    assert _status(Decision.archive, Decision.keep, False, None) is ItemStatus.kept
    assert _status(Decision.keep, Decision.archive, False, None) is ItemStatus.archived


def test_your_add_to_the_wishlist_beats_your_archive() -> None:
    assert _status(Decision.keep, Decision.archive, True, True) is ItemStatus.kept
    assert _status(Decision.archive, None, True, True) is ItemStatus.kept


def test_your_archive_beats_the_extracted_wishlist_flag() -> None:
    assert _status(Decision.keep, Decision.archive, True, None) is ItemStatus.archived
    assert _status(Decision.archive, None, True, None) is ItemStatus.kept, "the flag still beats the threshold"


def test_removing_from_the_wishlist_falls_back_to_your_choice_then_the_threshold() -> None:
    assert _status(Decision.keep, Decision.archive, False, False) is ItemStatus.archived
    assert _status(Decision.archive, Decision.keep, False, False) is ItemStatus.kept
    assert _status(Decision.archive, None, False, False) is ItemStatus.archived
    assert _status(Decision.keep, None, False, False) is ItemStatus.kept


def test_a_hand_removal_decides_like_no_flag_at_all() -> None:
    for threshold in Decision:
        for override in (None, *Decision):
            assert _status(threshold, override, False, False) is _status(threshold, override, False, None)


def test_only_extracted_kept_or_archived_posts_move_on_or_off_the_wishlist() -> None:
    movable = {s for s in ItemStatus if lifecycle.can_set_wishlist(s, extracted=True)}
    assert movable == {ItemStatus.kept, ItemStatus.archived}
    assert not lifecycle.can_set_wishlist(ItemStatus.archived, extracted=False)


def test_running_items_accept_no_action() -> None:
    for status in (ItemStatus.queued, ItemStatus.fetching, ItemStatus.processing):
        assert lifecycle.allowed_actions(status, finished=False) == []
    assert UserAction.keep in lifecycle.allowed_actions(ItemStatus.archived, finished=True)
    assert lifecycle.allowed_actions(ItemStatus.failed, finished=False) == [UserAction.archive, UserAction.retry]


def test_an_archived_post_sift_never_finished_can_only_be_reprocessed() -> None:
    assert lifecycle.allowed_actions(ItemStatus.archived, finished=False) == [UserAction.reprocess]


def test_every_failure_kind_has_a_hint() -> None:
    assert set(lifecycle.HINTS) == set(FailureKind)
