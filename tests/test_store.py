from __future__ import annotations

import pytest

from sift import db
from sift.domain import (
    Channel,
    Decision,
    FailureKind,
    ItemStatus,
    ItemType,
    Origin,
    ProcessingError,
    Source,
    SourceRef,
    Stage,
)
from sift.inbox import intake
from sift.items import lifecycle, queries, store
from sift.items.lifecycle import UserAction
from sift.models import Item
from sift.runtime import Runtime
from tests.conftest import Clock
from tests.fakes import FakeFetcher, download_error

URL = "https://www.instagram.com/reel/ABC123/?igsh=x"


def _enqueue(clock: Clock, url: str = URL) -> int:
    [result] = intake.submit(url, Origin(Channel.web), clock(), llm_ready=True)
    assert isinstance(result, intake.Queued | intake.Duplicate)
    return result.item.id


def test_dedup_returns_existing_with_status(rt: Runtime, clock: Clock) -> None:
    first = intake.submit(URL, Origin(Channel.web), clock(), llm_ready=True)
    again = intake.submit("https://www.instagram.com/reels/ABC123", Origin(Channel.web), clock(), llm_ready=True)
    assert isinstance(first[0], intake.Queued)
    assert isinstance(again[0], intake.Duplicate)
    assert again[0].item.id == first[0].item.id
    assert "Already saved" in intake.ack_text(again)


SHARE = "https://www.threads.com/share/BAa/"
POST = SourceRef(Source.threads, "De2", "https://www.threads.com/@chef.ana/post/De2")


def _submit_resolving(rt: Runtime, clock: Clock, url: str) -> intake.Submission:
    [result] = intake.submit(url, Origin(Channel.web), clock(), llm_ready=True, resolve=rt.worker.deps.fetchers.resolve)
    return result


def test_a_share_link_to_a_saved_post_is_a_duplicate_at_once(rt: Runtime, clock: Clock, fetcher: FakeFetcher) -> None:
    fetcher.shares["share-BAa"] = POST
    first = _submit_resolving(rt, clock, POST.clean_url)
    again = _submit_resolving(rt, clock, SHARE)
    assert isinstance(first, intake.Queued)
    assert isinstance(again, intake.Duplicate) and again.item.id == first.item.id


def test_a_share_link_that_cannot_be_opened_yet_is_queued_as_is(
    rt: Runtime, clock: Clock, fetcher: FakeFetcher
) -> None:
    fetcher.errors = [download_error()]
    result = _submit_resolving(rt, clock, SHARE)
    assert isinstance(result, intake.Queued)
    with db.read_session() as s:
        row = s.get(Item, result.item.id)
        assert row is not None and row.canonical_id == "share-BAa"


def test_a_share_link_that_does_not_reach_a_post_at_paste_is_kept_for_retry(
    rt: Runtime, clock: Clock, fetcher: FakeFetcher
) -> None:
    fetcher.errors = [ProcessingError(FailureKind.unsupported_url, "Login wall.", retryable=False)]
    assert isinstance(_submit_resolving(rt, clock, SHARE), intake.Queued)


def test_unsupported_urls_are_rejected_not_stored(rt: Runtime, clock: Clock) -> None:
    [r] = intake.submit("https://example.com/x", Origin(Channel.web), clock(), llm_ready=True)
    assert isinstance(r, intake.Rejected)
    assert sum(queries.queue_counts().values()) == 0


def test_claim_counts_the_attempt_and_sets_running(rt: Runtime, clock: Clock) -> None:
    item_id = _enqueue(clock)
    claim = store.claim_next(clock())
    assert claim is not None and claim.item_id == item_id
    item = queries.get_item(item_id, llm_ready=True)
    assert item is not None and item.status is ItemStatus.fetching and item.attempts == 1
    assert store.claim_next(clock()) is None


def test_paced_source_is_skipped_not_slept_on(rt: Runtime, clock: Clock) -> None:
    _enqueue(clock)
    assert store.claim_next(clock(), fetch_blocked={Source.instagram}) is None
    assert store.claim_next(clock(), fetch_blocked={Source.threads}) is not None


def test_backoff_gate(rt: Runtime, clock: Clock) -> None:
    item_id = _enqueue(clock)
    claim = store.claim_next(clock())
    assert claim is not None
    err = ProcessingError(FailureKind.download_failed, "429", retryable=True)
    assert store.record_failure(claim, err, clock()) is None
    assert store.claim_next(clock()) is None
    clock.advance(minutes=1, seconds=1)
    again = store.claim_next(clock())
    assert again is not None and again.item_id == item_id


def test_reset_stuck_requeues_then_fails_a_crash_loop(rt: Runtime, clock: Clock) -> None:
    item_id = _enqueue(clock)
    for _ in range(lifecycle.MAX_ATTEMPTS - 1):
        assert store.claim_next(clock()) is not None
        assert store.reset_stuck(clock()) == (1, 0)
    assert store.claim_next(clock()) is not None
    assert store.reset_stuck(clock()) == (0, 1)
    item = queries.get_item(item_id, llm_ready=True)
    assert item is not None and item.status is ItemStatus.failed
    assert item.failure_kind is FailureKind.download_failed


def test_stale_claim_cannot_write(rt: Runtime, clock: Clock) -> None:
    _enqueue(clock)
    claim = store.claim_next(clock())
    assert claim is not None
    store.reset_stuck(clock())
    with pytest.raises(store.ClaimLost):
        store.load(claim)


def test_user_actions_follow_the_transition_table(rt: Runtime, clock: Clock) -> None:
    item_id = _enqueue(clock)
    with pytest.raises(store.InvalidTransition):
        store.apply_action(item_id, UserAction.archive, clock(), llm_ready=True)
    with pytest.raises(store.ItemNotFound):
        store.apply_action(9999, UserAction.keep, clock(), llm_ready=True)


def _set(item_id: int, **fields: object) -> None:
    from sift import db
    from sift.models import Item

    with db.write_session() as s:
        row = s.get(Item, item_id)
        assert row is not None
        for k, v in fields.items():
            setattr(row, k, v)


def _scored(clock: Clock, item_id: int, title: str) -> None:
    now = clock()
    _set(
        item_id,
        status=ItemStatus.archived,
        fetched_at=now,
        media_processed_at=now,
        extracted_at=now,
        scored_at=now,
        item_type=ItemType.other,
        title=title,
        summary="s",
        details={"key_points": []},
        relevance_score=20,
        threshold_decision=Decision.archive,
    )


def test_llm_work_waits_without_an_llm(rt: Runtime, clock: Clock) -> None:
    item_id = _enqueue(clock)
    _set(item_id, fetched_at=clock(), media_processed_at=clock())
    assert store.claim_next(clock(), llm_ready=False) is None
    assert store.claim_next(clock(), llm_ready=True) is not None


def test_an_extracted_item_without_an_llm_waits_for_the_llm(rt: Runtime, clock: Clock, goal: int) -> None:
    item_id = _enqueue(clock)
    now = clock()
    _set(
        item_id,
        fetched_at=now,
        media_processed_at=now,
        extracted_at=now,
        item_type=ItemType.other,
        title="t",
        details={"key_points": []},
    )
    waiting = queries.get_item(item_id, llm_ready=False)
    assert waiting is not None and waiting.waiting_for == "llm" and waiting.state_label == "Waiting for LLM"
    assert not waiting.in_motion
    ready = queries.get_item(item_id, llm_ready=True)
    assert ready is not None and ready.waiting_for is None and ready.in_motion


def test_scoring_waits_without_goals(rt: Runtime, clock: Clock) -> None:
    item_id = _enqueue(clock)
    now = clock()
    _set(
        item_id,
        fetched_at=now,
        media_processed_at=now,
        extracted_at=now,
        item_type=ItemType.other,
        title="t",
        details={"key_points": []},
    )
    assert store.claim_next(clock(), goals_ready=False) is None
    assert store.claim_next(clock(), goals_ready=True) is not None


def test_override_examples_only_count_disagreements(rt: Runtime, clock: Clock) -> None:
    ids = [_enqueue(clock, f"https://www.instagram.com/reel/R{i}/") for i in range(3)]
    for i, item_id in enumerate(ids):
        _scored(clock, item_id, f"T{i}")
    store.apply_action(ids[0], UserAction.keep, clock.advance(minutes=1), llm_ready=True)
    store.apply_action(ids[1], UserAction.keep, clock.advance(minutes=1), llm_ready=True)
    store.apply_action(ids[1], UserAction.archive, clock.advance(minutes=1), llm_ready=True)
    examples = queries.recent_override_examples()
    assert [e.title for e in examples] == ["T0"]
    assert examples[0].user_decision is Decision.keep


def test_keep_then_done_then_undone(rt: Runtime, clock: Clock) -> None:
    item_id = _enqueue(clock)
    _scored(clock, item_id, "T")
    assert store.apply_action(item_id, UserAction.keep, clock(), llm_ready=True).status is ItemStatus.kept
    assert store.apply_action(item_id, UserAction.done, clock(), llm_ready=True).status is ItemStatus.done
    detail = store.apply_action(item_id, UserAction.undone, clock(), llm_ready=True)
    assert detail.status is ItemStatus.kept and detail.user_override is Decision.keep


def test_reprocess_keeps_media_and_override(rt: Runtime, clock: Clock) -> None:
    item_id = _enqueue(clock)
    _scored(clock, item_id, "T")
    store.apply_action(item_id, UserAction.keep, clock(), llm_ready=True)
    detail = store.apply_action(item_id, UserAction.reprocess, clock(), llm_ready=True)
    assert detail.status is ItemStatus.queued and detail.card is None
    assert detail.user_override is Decision.keep
    claim = store.claim_next(clock())
    assert claim is not None
    assert lifecycle.next_stage(store.load(claim)) is Stage.extract
