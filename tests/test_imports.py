from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlmodel import col, select

from sift import db
from sift.config import Settings
from sift.domain import (
    Channel,
    FailureKind,
    Hold,
    ImportAction,
    ImportPhase,
    ItemStatus,
    LinkState,
    Origin,
    PauseReason,
    ProcessingError,
    Source,
    SourceRef,
)
from sift.inbox import imports, intake
from sift.inbox.export import ExportScan, FoundLink
from sift.inbox.imports import AutoPause, DripState, Pace, Release, Wait
from sift.items import lifecycle, store
from sift.llm import pricing
from sift.models import ImportLink, Item
from sift.runtime import Runtime
from tests.conftest import Clock
from tests.fakes import FakeFetcher, download_error

GAP = timedelta(seconds=180)
T0 = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


def _pace(settings: Settings, *, cap: int = 100, gap: timedelta = GAP) -> Pace:
    return Pace(gap=gap, daily_cap=cap, cost=pricing.item_cost(settings))


def _link(code: str, days_ago: int | None, source: Source = Source.instagram) -> FoundLink:
    url = (
        f"https://www.instagram.com/reel/{code}/" if source is Source.instagram else f"https://www.threads.com/t/{code}"
    )
    ref = SourceRef(source, code, url)
    return FoundLink(ref, url, None if days_ago is None else T0 - timedelta(days=days_ago))


def _scan(*links: FoundLink, unsupported: tuple[str, ...] = ()) -> ExportScan:
    return ExportScan(list(links), list(unsupported), ["saved/saved_posts.json"], [], [])


def _stage(rt: Runtime, clock: Clock, pace: Pace, *links: FoundLink) -> int:
    return imports.stage(_scan(*links), "export.zip", clock(), pace, llm_ready=rt.llm_ready).id


def _start(rt: Runtime, clock: Clock, pace: Pace, import_id: int, limit: int | None = None) -> imports.ImportView:
    return imports.apply(import_id, ImportAction.start, clock(), pace, llm_ready=rt.llm_ready, limit=limit)


def _view(rt: Runtime, clock: Clock, pace: Pace, import_id: int) -> imports.ImportView:
    view = imports.get_import(import_id, clock(), pace, llm_ready=rt.llm_ready)
    assert view is not None
    return view


def _export_items() -> list[Item]:
    with db.read_session() as s:
        return list(s.exec(select(Item).where(Item.origin_channel == Channel.export).order_by(col(Item.id))).all())


def _states(import_id: int) -> dict[str, LinkState]:
    with db.read_session() as s:
        return {x.canonical_id: x.state for x in s.exec(select(ImportLink).where(ImportLink.import_id == import_id))}


def test_preview_counts_dedup_and_prices(rt: Runtime, clock: Clock, settings: Settings) -> None:
    intake.submit("https://www.instagram.com/reel/HAVE/", Origin(Channel.web), clock(), llm_ready=True)
    priced = Pace(GAP, 100, pricing.item_cost(settings.model_copy(update={"llm_backend": "anthropic"})))
    scan = _scan(
        _link("HAVE", 9),
        _link("A", 1),
        _link("B", 2),
        _link("C", 3),
        unsupported=("https://www.instagram.com/stories/x/1/",),
    )
    view = imports.stage(scan, "meta.zip", clock(), priced, llm_ready=True)

    assert view.phase is ImportPhase.preview
    assert (view.counts.links, view.counts.found, view.counts.duplicate) == (4, 3, 1)
    assert view.unsupported_count == 1
    assert view.per_post.usd == pytest.approx(0.0238 + 0.00083)
    [everything] = view.options
    assert everything.limit is None and everything.estimate.posts == 3
    assert everything.estimate.usd == pytest.approx(0.07)
    assert everything.estimate.seconds == 3 * 180
    assert view.actions == [ImportAction.start, ImportAction.cancel]
    assert _export_items() == [], "a preview sends nothing to the pipeline"


def test_options_offer_newest_50_and_100_and_count_the_daily_cap(rt: Runtime, clock: Clock, settings: Settings) -> None:
    options = imports.queue_options(370, _pace(settings))
    assert [o.limit for o in options] == [50, 100, None]
    assert options[1].estimate.seconds == 100 * 180
    assert options[2].estimate.seconds == 3 * 24 * 3600 + 70 * 180, "100 a day, then whole days"
    assert [o.limit for o in imports.queue_options(80, _pace(settings))] == [50, None]


async def test_cancelling_an_import_leaves_its_posts_to_an_overlapping_one(
    rt: Runtime, clock: Clock, settings: Settings, goal: int
) -> None:
    pace = _pace(settings)
    first = _stage(rt, clock, pace, _link("A", 1))
    _start(rt, clock, pace, first)
    second = imports.stage(_scan(_link("A", 1), _link("B", 2)), "again.zip", clock(), pace, llm_ready=True)
    assert (second.counts.found, second.counts.duplicate) == (2, 0), "only posts already in Sift are duplicates"

    imports.apply(first, ImportAction.cancel, clock(), pace, llm_ready=True)
    _start(rt, clock, pace, second.id)
    for _ in range(2):
        assert isinstance(imports.release_next(clock(), pace, llm_ready=True), Release)
        item_id = _export_items()[-1].id
        assert item_id is not None
        await rt.worker.run_item(item_id)
        clock.advance(seconds=250)
    assert _states(second.id) == {"A": LinkState.released, "B": LinkState.released}
    assert [i.canonical_id for i in _export_items()] == ["A", "B"]


async def test_a_post_waiting_in_two_imports_is_released_once(
    rt: Runtime, clock: Clock, settings: Settings, goal: int
) -> None:
    pace = _pace(settings)
    first = _stage(rt, clock, pace, _link("A", 1))
    second = _stage(rt, clock, pace, _link("A", 1))
    _start(rt, clock, pace, first)
    _start(rt, clock, pace, second)
    assert isinstance(imports.release_next(clock(), pace, llm_ready=True), Release)
    [a] = _export_items()
    assert a.id is not None
    await rt.worker.run_item(a.id)
    clock.advance(seconds=250)
    assert isinstance(imports.release_next(clock(), pace, llm_ready=True), Release)
    assert (_states(first), _states(second)) == ({"A": LinkState.released}, {"A": LinkState.duplicate})
    assert len(_export_items()) == 1


async def test_an_imported_share_link_to_a_saved_post_becomes_a_duplicate(
    rt: Runtime, clock: Clock, settings: Settings, goal: int, fetcher: FakeFetcher
) -> None:
    post = SourceRef(Source.instagram, "HAVE", "https://www.instagram.com/reel/HAVE/")
    intake.submit(post.clean_url, Origin(Channel.web), clock(), llm_ready=True)
    share_url = "https://www.instagram.com/share/reel/Ab/"
    pace = _pace(settings)
    import_id = _stage(rt, clock, pace, FoundLink(SourceRef(Source.instagram, "share-Ab", share_url), share_url, T0))
    _start(rt, clock, pace, import_id)
    assert isinstance(imports.release_next(clock(), pace, llm_ready=True), Release)
    [item] = _export_items()
    assert item.id is not None
    fetcher.shares["share-Ab"] = post
    await rt.worker.run_item(item.id)
    assert _export_items() == []
    assert _states(import_id) == {"share-Ab": LinkState.duplicate}


def test_an_export_with_nothing_new_cannot_start(rt: Runtime, clock: Clock, settings: Settings) -> None:
    intake.submit("https://www.instagram.com/reel/HAVE/", Origin(Channel.web), clock(), llm_ready=True)
    pace = _pace(settings)
    import_id = _stage(rt, clock, pace, _link("HAVE", 1))
    assert _view(rt, clock, pace, import_id).actions == [ImportAction.cancel]
    with pytest.raises(imports.InvalidImportAction):
        _start(rt, clock, pace, import_id)


def test_start_takes_the_newest_n_by_saved_time(rt: Runtime, clock: Clock, settings: Settings) -> None:
    pace = _pace(settings)
    import_id = _stage(rt, clock, pace, _link("OLD", 30), _link("UNDATED", None), _link("NEW", 1), _link("MID", 5))
    view = _start(rt, clock, pace, import_id, limit=2)
    assert view.phase is ImportPhase.running and view.max_posts == 2
    assert _states(import_id) == {
        "NEW": LinkState.waiting,
        "MID": LinkState.waiting,
        "OLD": LinkState.skipped,
        "UNDATED": LinkState.skipped,
    }
    assert view.remaining is not None and view.remaining.posts == 2


def test_actions_follow_the_phase_table(rt: Runtime, clock: Clock, settings: Settings) -> None:
    pace = _pace(settings)
    import_id = _stage(rt, clock, pace, _link("A", 1), _link("B", 2))
    with pytest.raises(imports.InvalidImportAction, match="cannot pause an import that is preview"):
        imports.apply(import_id, ImportAction.pause, clock(), pace, llm_ready=True)
    _start(rt, clock, pace, import_id)
    paused = imports.apply(import_id, ImportAction.pause, clock(), pace, llm_ready=True)
    assert paused.phase is ImportPhase.paused and paused.pause_reason is PauseReason.user
    assert paused.actions == [ImportAction.resume, ImportAction.cancel]
    assert imports.release_next(clock(), pace, llm_ready=True) is None, "a paused import releases nothing"
    resumed = imports.apply(import_id, ImportAction.resume, clock(), pace, llm_ready=True)
    assert resumed.phase is ImportPhase.running and resumed.pause_reason is None
    with pytest.raises(imports.ImportNotFound):
        imports.apply(999, ImportAction.start, clock(), pace, llm_ready=True)


async def test_cancel_skips_what_waits_and_keeps_what_was_released(
    rt: Runtime, clock: Clock, settings: Settings, goal: int
) -> None:
    pace = _pace(settings)
    import_id = _stage(rt, clock, pace, _link("A", 1), _link("B", 2))
    _start(rt, clock, pace, import_id)
    assert isinstance(imports.release_next(clock(), pace, llm_ready=True), Release)
    view = imports.apply(import_id, ImportAction.cancel, clock(), pace, llm_ready=True)
    assert view.phase is ImportPhase.cancelled and view.actions == []
    assert _states(import_id) == {"A": LinkState.released, "B": LinkState.skipped}
    assert len(_export_items()) == 1


def _state(**kw: Any) -> DripState:
    return replace(DripState(in_flight=False, next_release_at=None, released_last_day=(), recent_failures=()), **kw)


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (_state(), Release()),
        (_state(recent_failures=(True,) * 5), AutoPause()),
        (_state(recent_failures=(True,) * 4 + (False,)), Release()),
        (_state(recent_failures=(False,) + (True,) * 5), Release()),
        (_state(in_flight=True), Wait(Hold.in_flight, None)),
        (_state(next_release_at=T0 + GAP), Wait(Hold.gap, T0 + GAP)),
        (_state(next_release_at=T0 - GAP), Release()),
        (
            _state(released_last_day=(T0 - timedelta(hours=20), T0 - timedelta(hours=3))),
            Wait(Hold.daily_cap, T0 + timedelta(hours=4)),
        ),
        (_state(released_last_day=(T0 - timedelta(hours=3),)), Release()),
        (
            _state(released_last_day=tuple(T0 - timedelta(hours=h) for h in (20, 10, 3))),
            Wait(Hold.daily_cap, T0 + timedelta(hours=14)),
        ),
    ],
)
def test_gate(state: DripState, expected: imports.Gate) -> None:
    pace = Pace(gap=GAP, daily_cap=2, cost=pricing.ItemCost(()))
    assert imports.gate(state, T0, pace) == expected


def test_gap_jitter_is_fixed_per_link_and_bounded() -> None:
    gaps = {imports.gap_for(i, GAP) for i in range(200)}
    assert len(gaps) > 150
    assert all(GAP * 0.65 <= g <= GAP * 1.35 for g in gaps)
    assert imports.gap_for(7, GAP) == imports.gap_for(7, GAP)


async def test_drip_releases_one_post_at_a_time(rt: Runtime, clock: Clock, settings: Settings, goal: int) -> None:
    pace = _pace(settings)
    import_id = _stage(rt, clock, pace, _link("A", 1), _link("B", 2), _link("C", 3))
    _start(rt, clock, pace, import_id)

    assert isinstance(imports.release_next(clock(), pace, llm_ready=True), Release)
    [first] = _export_items()
    assert first.canonical_id == "A", "newest saved first"
    assert imports.release_next(clock(), pace, llm_ready=True) == Wait(Hold.in_flight, None)
    view = _view(rt, clock, pace, import_id)
    assert view.hold is Hold.in_flight and view.current is not None and view.current.item_id == first.id

    assert first.id is not None
    await rt.worker.run_item(first.id)
    decision = imports.release_next(clock(), pace, llm_ready=True)
    assert isinstance(decision, Wait) and decision.hold is Hold.gap
    assert decision.until is not None and GAP * 0.65 <= decision.until - clock() <= GAP * 1.35
    assert len(_export_items()) == 1

    clock.advance(seconds=250)
    assert isinstance(imports.release_next(clock(), pace, llm_ready=True), Release)
    assert [i.canonical_id for i in _export_items()] == ["A", "B"]
    view = _view(rt, clock, pace, import_id)
    assert (view.counts.released, view.counts.waiting, view.counts.kept) == (2, 1, 1)


async def test_a_mac_waking_from_sleep_releases_one_post_not_a_burst(
    rt: Runtime, clock: Clock, settings: Settings, goal: int
) -> None:
    pace = _pace(settings)
    import_id = _stage(rt, clock, pace, _link("A", 1), _link("B", 2), _link("C", 3))
    _start(rt, clock, pace, import_id)
    imports.release_next(clock(), pace, llm_ready=True)
    [a] = _export_items()
    assert a.id is not None
    await rt.worker.run_item(a.id)

    clock.advance(hours=10)
    assert isinstance(imports.release_next(clock(), pace, llm_ready=True), Release)
    b = _export_items()[-1]
    assert b.id is not None
    await rt.worker.run_item(b.id)
    decision = imports.release_next(clock(), pace, llm_ready=True)
    assert isinstance(decision, Wait) and decision.hold is Hold.gap
    assert len(_export_items()) == 2


async def test_the_daily_cap_holds_until_the_oldest_release_is_a_day_old(
    rt: Runtime, clock: Clock, settings: Settings, goal: int
) -> None:
    pace = _pace(settings, cap=2)
    import_id = _stage(rt, clock, pace, _link("A", 1), _link("B", 2), _link("C", 3))
    _start(rt, clock, pace, import_id)
    started = clock()
    for _ in range(2):
        imports.release_next(clock(), pace, llm_ready=True)
        item_id = _export_items()[-1].id
        assert item_id is not None
        await rt.worker.run_item(item_id)
        clock.advance(seconds=300)

    assert imports.release_next(clock(), pace, llm_ready=True) == Wait(Hold.daily_cap, started + timedelta(hours=24))
    assert _view(rt, clock, pace, import_id).hold is Hold.daily_cap
    clock.now = started + timedelta(hours=24, seconds=1)
    assert isinstance(imports.release_next(clock(), pace, llm_ready=True), Release)


async def test_deleting_a_released_post_keeps_it_under_the_daily_cap(
    rt: Runtime, clock: Clock, settings: Settings, goal: int
) -> None:
    pace = _pace(settings, cap=2)
    import_id = _stage(rt, clock, pace, _link("A", 1), _link("B", 2), _link("C", 3))
    _start(rt, clock, pace, import_id)
    started = clock()
    for _ in range(2):
        imports.release_next(clock(), pace, llm_ready=True)
        item_id = _export_items()[-1].id
        assert item_id is not None
        await rt.worker.run_item(item_id)
        clock.advance(seconds=300)
    first = _export_items()[0]
    with db.write_session() as s:
        row = s.get(Item, first.id)
        assert row is not None
        row.status = ItemStatus.archived
    assert first.id is not None
    store.delete_archived(first.id)

    assert imports.release_next(clock(), pace, llm_ready=True) == Wait(Hold.daily_cap, started + timedelta(hours=24))
    view = _view(rt, clock, pace, import_id)
    assert (view.counts.released, view.hold) == (2, Hold.daily_cap)
    assert len(_export_items()) == 1


LOGIN_REQUIRED = "[Instagram] P: You need to log in to access this content"
DEAD = ProcessingError(FailureKind.post_unavailable, "Instagram says this post is gone", retryable=False)


async def _release_and_fail(rt: Runtime, clock: Clock, pace: Pace, fetcher: FakeFetcher, *, dead: bool) -> None:
    fetcher.errors = [DEAD] if dead else [download_error(LOGIN_REQUIRED) for _ in range(lifecycle.MAX_ATTEMPTS)]
    assert isinstance(imports.release_next(clock(), pace, llm_ready=True), Release)
    item_id = _export_items()[-1].id
    assert item_id is not None
    while fetcher.errors:
        await rt.worker.step(only=item_id)
        clock.advance(minutes=30)
    [item] = [i for i in _export_items() if i.id == item_id]
    assert item.failure_kind is (FailureKind.post_unavailable if dead else FailureKind.download_failed)


async def test_five_failed_downloads_in_a_row_pause_the_import(
    rt: Runtime, clock: Clock, settings: Settings, fetcher: FakeFetcher, goal: int
) -> None:
    pace = _pace(settings)
    import_id = _stage(rt, clock, pace, *(_link(f"P{i}", i) for i in range(1, 8)))
    _start(rt, clock, pace, import_id)
    for _ in range(5):
        await _release_and_fail(rt, clock, pace, fetcher, dead=False)

    assert isinstance(imports.release_next(clock(), pace, llm_ready=True), AutoPause)
    view = _view(rt, clock, pace, import_id)
    assert view.phase is ImportPhase.paused and view.pause_reason is PauseReason.download_failures
    assert len(_export_items()) == 5

    imports.apply(import_id, ImportAction.resume, clock(), pace, llm_ready=True)
    assert isinstance(imports.release_next(clock(), pace, llm_ready=True), Release), "resume starts a fresh count"


async def test_dead_posts_do_not_pause_the_import(
    rt: Runtime, clock: Clock, settings: Settings, fetcher: FakeFetcher, goal: int
) -> None:
    pace = _pace(settings)
    import_id = _stage(rt, clock, pace, *(_link(f"P{i}", i) for i in range(1, 8)))
    _start(rt, clock, pace, import_id)
    for _ in range(5):
        await _release_and_fail(rt, clock, pace, fetcher, dead=True)

    assert isinstance(imports.release_next(clock(), pace, llm_ready=True), Release)
    assert _view(rt, clock, pace, import_id).phase is ImportPhase.running


async def test_dead_posts_between_download_failures_do_not_reset_the_count(
    rt: Runtime, clock: Clock, settings: Settings, fetcher: FakeFetcher, goal: int
) -> None:
    pace = _pace(settings)
    import_id = _stage(rt, clock, pace, *(_link(f"P{i}", i) for i in range(1, 10)))
    _start(rt, clock, pace, import_id)
    for dead in (False, False, False, True, True, False, False):
        await _release_and_fail(rt, clock, pace, fetcher, dead=dead)

    assert isinstance(imports.release_next(clock(), pace, llm_ready=True), AutoPause)


async def test_a_post_in_retry_backoff_does_not_hold_the_drip(
    rt: Runtime, clock: Clock, settings: Settings, fetcher: FakeFetcher, goal: int
) -> None:
    fetcher.errors = [download_error()]
    pace = _pace(settings, gap=timedelta(seconds=30))
    import_id = _stage(rt, clock, pace, _link("A", 1), _link("B", 2))
    _start(rt, clock, pace, import_id)
    imports.release_next(clock(), pace, llm_ready=True)
    [a] = _export_items()
    assert a.id is not None
    await rt.worker.step(only=a.id)
    clock.advance(seconds=45)
    assert isinstance(imports.release_next(clock(), pace, llm_ready=True), Release)


def test_a_crash_while_releasing_leaves_no_orphan(
    rt: Runtime, clock: Clock, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    pace = _pace(settings)
    import_id = _stage(rt, clock, pace, _link("A", 1))
    _start(rt, clock, pace, import_id)

    def crash(*_: object) -> None:
        raise RuntimeError("killed")

    with monkeypatch.context() as m:
        m.setattr(imports, "gap_for", crash)
        with pytest.raises(RuntimeError):
            imports.release_next(clock(), pace, llm_ready=True)
    assert _export_items() == [] and _states(import_id) == {"A": LinkState.waiting}
    assert isinstance(imports.release_next(clock(), pace, llm_ready=True), Release)
    assert len(_export_items()) == 1 and _states(import_id) == {"A": LinkState.released}


@pytest.mark.parametrize("action", [ImportAction.cancel, ImportAction.pause])
def test_a_cancel_or_pause_between_the_gate_and_the_release_wins(
    action: ImportAction, rt: Runtime, clock: Clock, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    pace = _pace(settings)
    import_id = _stage(rt, clock, pace, _link("A", 1))
    _start(rt, clock, pace, import_id)
    pick = imports._next_link

    def pick_then_interrupt(s: Any, row: Any) -> ImportLink | None:
        link = pick(s, row)
        imports.apply(import_id, action, clock(), pace, llm_ready=True)
        return link

    monkeypatch.setattr(imports, "_next_link", pick_then_interrupt)
    assert imports.release_next(clock(), pace, llm_ready=True) is None
    assert _export_items() == [], "nothing goes to Instagram after the user stopped the import"
    expected = LinkState.skipped if action is ImportAction.cancel else LinkState.waiting
    assert _states(import_id) == {"A": expected}


async def test_a_link_pasted_before_its_release_becomes_a_duplicate(
    rt: Runtime, clock: Clock, settings: Settings
) -> None:
    pace = _pace(settings)
    import_id = _stage(rt, clock, pace, _link("A", 1))
    _start(rt, clock, pace, import_id)
    intake.submit("https://www.instagram.com/reel/A/", Origin(Channel.web), clock(), llm_ready=True)
    imports.release_next(clock(), pace, llm_ready=True)
    assert _states(import_id) == {"A": LinkState.duplicate}
    assert _export_items() == []
    assert _view(rt, clock, pace, import_id).phase is ImportPhase.finished
