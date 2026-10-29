from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import col, select

from sift import db, digest
from sift.domain import Channel, DigestRole, FailureKind, ItemStatus, Origin, ProcessingError
from sift.inbox import intake
from sift.items import queries, store
from sift.items.lifecycle import MAX_ATTEMPTS, UserAction
from sift.items.views import ArchivedOutcome, ItemOutcome
from sift.llm.client import LLM
from sift.llm.fake import FakeLLM
from sift.llm.schemas import (
    DigestDraft,
    DigestInput,
    ExtractInput,
    ExtractOutput,
    OutlineDraft,
    OutlineInput,
    ProductCard,
    ScoreInput,
    ScoreOutput,
)
from sift.models import Digest, DigestEntry, Item, Outline
from sift.organize import store as organize
from sift.organize.organizer import Organizer
from sift.runtime import Runtime
from sift.web.app import create_app
from tests.conftest import Clock
from tests.fakes import FakeFetcher
from tests.test_topic_digest import add_post, add_topic

JACKET = "Rain jacket that packs into its own pocket. $90, buy it before the fall."
TACOS = "Best tacos in the East Village spot, al pastor."
FREE_TOOL = "Free open-source CLI that renames your photos. Not a product you buy, grab it on github."


class WishLLM(FakeLLM):
    def __init__(self) -> None:
        super().__init__()
        self.wishlist: bool | None = None
        self.digest_inputs: list[DigestInput] = []
        self.scored: list[str] = []
        self.outlined: list[str] = []
        self.score_fails = False
        self.while_composing: Callable[[], None] = lambda: None

    def extract(self, inp: ExtractInput) -> tuple[ExtractOutput, str]:
        out, model = super().extract(inp)
        card = out.card
        if self.wishlist is None or not isinstance(card, ProductCard):
            return out, model
        details = card.details.model_copy(update={"wishlist": self.wishlist})
        return out.model_copy(update={"card": card.model_copy(update={"details": details})}), model

    def score(self, inp: ScoreInput) -> tuple[ScoreOutput, str]:
        self.scored.append(inp.card.title)
        if self.score_fails:
            raise ProcessingError(FailureKind.llm_failed, "The model refused.", retryable=False)
        return super().score(inp)

    def outline(self, inp: OutlineInput) -> tuple[OutlineDraft, str]:
        self.outlined.append(inp.card.title)
        return super().outline(inp)

    def compose_digest(self, inp: DigestInput) -> tuple[DigestDraft, str]:
        self.digest_inputs.append(inp)
        self.while_composing()
        return super().compose_digest(inp)


@pytest.fixture
def llm() -> LLM | None:
    return WishLLM()


@pytest.fixture
def wish_llm(rt: Runtime) -> WishLLM:
    assert isinstance(rt.llm, WishLLM)
    return rt.llm


@pytest.fixture
def client(rt: Runtime, tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(rt, run_background=False, dist=tmp_path / "no-dist")) as c:
        yield c


async def _saved(rt: Runtime, clock: Clock, fetcher: FakeFetcher, caption: str, code: str) -> int:
    fetcher.caption = caption
    [r] = intake.submit(f"https://www.instagram.com/reel/{code}/", Origin(Channel.web), clock(), llm_ready=True)
    assert isinstance(r, intake.Queued)
    await rt.worker.run_item(r.item.id)
    return r.item.id


def _ids(client: TestClient, view: str) -> list[int]:
    return [i["id"] for i in client.get("/api/items", params={"view": view}).json()]


def _wishlist(client: TestClient, item_id: int, on: bool | None) -> Any:
    return client.put(f"/api/items/{item_id}/wishlist", json={"on": on})


def _organize(rt: Runtime, clock: Clock) -> None:
    organizer = Organizer(clock)
    while organizer.step(rt.llm, import_running=False):
        pass


async def test_a_buyable_product_goes_on_the_wishlist_unscored_and_on_no_topic(
    rt: Runtime, clock: Clock, fetcher: FakeFetcher, goal: int, client: TestClient, wish_llm: WishLLM
) -> None:
    item_id = await _saved(rt, clock, fetcher, JACKET, "JACKET")
    _organize(rt, clock)
    assert wish_llm.scored == [] and wish_llm.outlined == []
    item = client.get(f"/api/items/{item_id}").json()
    assert (item["status"], item["wishlist"], item["status_reason"]) == ("kept", True, "On your wishlist")
    assert (item["relevance_score"], item["threshold_decision"], item["stage"]) == (None, None, None)
    assert (item["topic"], item["organization"], item["state_label"]) == (None, None, "On wishlist")
    assert item["product"] == {"name": item["card"]["details"]["name"], "price": None, "link": None}
    assert {"done", "archive"} <= set(item["actions"]) and item["can_wishlist"] is True
    assert _ids(client, "wishlist") == [item_id]
    assert _ids(client, "kept") == [] and _ids(client, "inbox") == []
    status = client.get("/api/status").json()
    assert (status["nav"]["wishlist"], status["nav"]["kept"], status["nav"]["archived"]) == (1, 0, 0)
    assert status["in_motion"] == [] and status["pulse"]["busy"] is False


async def test_a_wishlist_post_never_waits_for_goals(
    rt: Runtime, clock: Clock, fetcher: FakeFetcher, client: TestClient, wish_llm: WishLLM
) -> None:
    item_id = await _saved(rt, clock, fetcher, JACKET, "JACKET")
    item = client.get(f"/api/items/{item_id}").json()
    assert (item["status"], item["waiting_for"]) == ("kept", None)
    assert wish_llm.scored == []


async def test_a_wishlist_post_left_waiting_to_be_scored_settles_without_a_score(
    rt: Runtime, clock: Clock, fetcher: FakeFetcher, client: TestClient, wish_llm: WishLLM
) -> None:
    wish_llm.wishlist = False
    item_id = await _saved(rt, clock, fetcher, JACKET, "JACKET")
    assert client.get(f"/api/items/{item_id}").json()["waiting_for"] == "goals"
    _put_on_wishlist(item_id)
    queued = client.get(f"/api/items/{item_id}").json()
    assert (queued["status"], queued["waiting_for"], queued["stage"]) == ("queued", None, None)
    await rt.worker.run_item(item_id)
    item = client.get(f"/api/items/{item_id}").json()
    assert (item["status"], item["relevance_score"]) == ("kept", None) and wish_llm.scored == []


async def test_a_free_tool_below_the_line_is_scored_and_archived_as_before(
    rt: Runtime, clock: Clock, fetcher: FakeFetcher, goal: int, client: TestClient, wish_llm: WishLLM
) -> None:
    item_id = await _saved(rt, clock, fetcher, FREE_TOOL, "TOOL")
    item = client.get(f"/api/items/{item_id}").json()
    assert (item["item_type"], item["status"], item["wishlist"]) == ("product", "archived", False)
    assert item["relevance_score"] is not None and len(wish_llm.scored) == 1
    assert _ids(client, "archived") == [item_id] and _ids(client, "wishlist") == []
    _organize(rt, clock)
    assert len(wish_llm.outlined) == 1


async def test_removing_an_unscored_post_leaves_it_kept_as_a_normal_post_the_organizer_files(
    rt: Runtime, clock: Clock, fetcher: FakeFetcher, goal: int, client: TestClient, wish_llm: WishLLM
) -> None:
    jacket = await _saved(rt, clock, fetcher, JACKET, "JACKET")
    removed = _wishlist(client, jacket, False)
    assert removed.status_code == 200
    body = removed.json()
    assert (body["status"], body["wishlist"], body["relevance_score"]) == ("kept", False, None)
    assert (body["stage"], body["in_motion"], body["state_label"], body["status_reason"]) == (None, False, "Kept", None)
    assert {"done", "archive"} <= set(body["actions"])
    assert _ids(client, "kept") == [jacket] and _ids(client, "wishlist") == [] and _ids(client, "inbox") == []

    archived = client.post(f"/api/items/{jacket}/actions/archive").json()
    assert archived["status"] == "archived" and "keep" in archived["actions"]
    kept = client.post(f"/api/items/{jacket}/actions/keep").json()
    assert (kept["status"], kept["wishlist"]) == ("kept", False)
    assert client.post(f"/api/items/{jacket}/actions/done").json()["status"] == "done"
    assert client.post(f"/api/items/{jacket}/actions/undone").json()["status"] == "kept"

    products = add_topic("Products", clock)
    _organize(rt, clock)
    assert wish_llm.scored == [] and wish_llm.outlined == [body["title"]]
    filed = client.get(f"/api/items/{jacket}").json()
    assert (filed["topic"], filed["relevance_score"]) == ({"id": products, "name": "Products"}, None)


async def test_removing_an_unscored_archived_post_leaves_it_archived_with_keep(
    rt: Runtime, clock: Clock, fetcher: FakeFetcher, goal: int, client: TestClient, wish_llm: WishLLM
) -> None:
    jacket = await _saved(rt, clock, fetcher, JACKET, "JACKET")
    client.post(f"/api/items/{jacket}/actions/archive")
    removed = _wishlist(client, jacket, False).json()
    assert (removed["status"], removed["relevance_score"], removed["stage"]) == ("archived", None, None)
    assert "keep" in removed["actions"] and removed["status_reason"] == "Archived by you"
    kept = client.post(f"/api/items/{jacket}/actions/keep").json()
    assert (kept["status"], kept["wishlist"]) == ("kept", False)
    assert _ids(client, "kept") == [jacket] and wish_llm.scored == []


def _telegram_saves(monkeypatch: pytest.MonkeyPatch, rt: Runtime) -> list[ItemOutcome]:
    announced: list[ItemOutcome] = []

    async def spy(outcome: ItemOutcome) -> None:
        announced.append(outcome)

    monkeypatch.setattr(rt.notifier, "item_finished", spy)
    return announced


async def _saved_on_telegram(rt: Runtime, clock: Clock, fetcher: FakeFetcher, caption: str, code: str) -> int:
    fetcher.caption = caption
    url = f"https://www.instagram.com/reel/{code}/"
    [r] = intake.submit(url, Origin(Channel.telegram, {"chat_id": 1}), clock(), llm_ready=True)
    assert isinstance(r, intake.Queued)
    await rt.worker.run_item(r.item.id)
    return r.item.id


async def test_undoing_a_removal_puts_it_back_on_the_wishlist_with_no_pipeline_run_or_notification(
    rt: Runtime,
    clock: Clock,
    fetcher: FakeFetcher,
    goal: int,
    client: TestClient,
    wish_llm: WishLLM,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    announced = _telegram_saves(monkeypatch, rt)
    jacket = await _saved_on_telegram(rt, clock, fetcher, JACKET, "JACKET")
    assert [o.item_id for o in announced] == [jacket]
    assert _wishlist(client, jacket, False).json()["status"] == "kept"
    undone = _wishlist(client, jacket, None).json()
    assert (undone["status"], undone["wishlist"], undone["wishlist_override"]) == ("kept", True, None)
    assert (undone["relevance_score"], undone["status_reason"]) == (None, "On your wishlist")
    assert await rt.worker.step(only=jacket) == (False, None), "nothing to run"
    assert [o.item_id for o in announced] == [jacket] and wish_llm.scored == []
    assert _ids(client, "wishlist") == [jacket]


async def test_no_wishlist_toggle_announces_a_post_again(
    rt: Runtime, clock: Clock, fetcher: FakeFetcher, goal: int, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    announced = _telegram_saves(monkeypatch, rt)
    jacket = await _saved_on_telegram(rt, clock, fetcher, JACKET, "JACKET")
    tool = await _saved_on_telegram(rt, clock, fetcher, FREE_TOOL, "TOOL")
    for on in (False, True, None, True, False):
        for item_id in (jacket, tool):
            assert _wishlist(client, item_id, on).status_code == 200
            while (await rt.worker.step())[0]:
                pass
    assert [o.item_id for o in announced] == [jacket, tool]


async def test_a_wishlist_post_you_archived_is_announced_with_your_archive(
    rt: Runtime, clock: Clock, fetcher: FakeFetcher, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    announced = _telegram_saves(monkeypatch, rt)
    jacket = await _saved_on_telegram(rt, clock, fetcher, JACKET, "JACKET")
    client.post(f"/api/items/{jacket}/actions/archive")
    client.post(f"/api/items/{jacket}/actions/reprocess")
    await rt.worker.run_item(jacket)
    last = announced[-1]
    assert isinstance(last, ArchivedOutcome) and last.reason == "Archived by you"


def _mid_settle(item_id: int, attempts: int) -> None:
    with db.write_session() as s:
        row = s.get(Item, item_id)
        assert row is not None
        row.status, row.processed_at, row.attempts = ItemStatus.processing, None, attempts
        row.claim_token, row.claimed_at = "lost", row.received_at


async def test_an_interrupted_wishlist_settle_reads_saving_and_is_requeued_not_failed(
    rt: Runtime, clock: Clock, fetcher: FakeFetcher, client: TestClient, wish_llm: WishLLM
) -> None:
    jacket = await _saved(rt, clock, fetcher, JACKET, "JACKET")
    _mid_settle(jacket, attempts=MAX_ATTEMPTS)
    assert client.get(f"/api/items/{jacket}").json()["state_label"] == "Saving"
    assert store.reset_stuck(clock()) == (1, 0)
    queued = client.get(f"/api/items/{jacket}").json()
    assert (queued["status"], queued["failure_kind"]) == ("queued", None)
    await rt.worker.run_item(jacket)
    assert client.get(f"/api/items/{jacket}").json()["status"] == "kept" and wish_llm.scored == []


async def test_undoing_an_add_leaves_a_post_you_archived_after_it_failed_archived(
    rt: Runtime, clock: Clock, fetcher: FakeFetcher, goal: int, client: TestClient, wish_llm: WishLLM
) -> None:
    wish_llm.wishlist = False
    wish_llm.score_fails = True
    jacket = await _saved(rt, clock, fetcher, JACKET, "JACKET")
    assert client.get(f"/api/items/{jacket}").json()["status"] == "failed"
    assert client.post(f"/api/items/{jacket}/actions/archive").json()["status"] == "archived"
    assert _wishlist(client, jacket, True).json()["status"] == "kept"
    undone = _wishlist(client, jacket, None).json()
    assert (undone["status"], undone["wishlist"], undone["status_reason"]) == ("archived", False, "Archived by you")
    await rt.worker.run_item(jacket)
    assert client.get(f"/api/items/{jacket}").json()["status"] == "archived"
    assert len(wish_llm.scored) == 1, "only the attempt that failed"
    assert _ids(client, "archived") == [jacket] and _ids(client, "inbox") == []


async def test_a_wishlist_post_keeps_its_fetch_notes_as_the_reason(
    rt: Runtime, clock: Clock, fetcher: FakeFetcher, client: TestClient
) -> None:
    fetcher.notes = ("Only the first slide loaded.",)
    jacket = await _saved(rt, clock, fetcher, JACKET, "JACKET")
    item = client.get(f"/api/items/{jacket}").json()
    assert (item["status"], item["status_reason"]) == ("kept", "Only the first slide loaded.")


async def test_bought_marks_it_done_and_undo_puts_it_back_on_the_wishlist(
    rt: Runtime, clock: Clock, fetcher: FakeFetcher, goal: int, client: TestClient
) -> None:
    item_id = await _saved(rt, clock, fetcher, JACKET, "JACKET")
    bought = client.post(f"/api/items/{item_id}/actions/done").json()
    assert bought["status"] == "done"
    assert _ids(client, "wishlist") == [] and _ids(client, "kept") == [item_id]
    undone = client.post(f"/api/items/{item_id}/actions/undone").json()
    assert (undone["status"], undone["wishlist"]) == ("kept", True)
    assert _ids(client, "wishlist") == [item_id]


async def test_adding_keeps_an_archived_post_and_removing_restores_its_threshold_status(
    rt: Runtime, clock: Clock, fetcher: FakeFetcher, goal: int, client: TestClient
) -> None:
    tool = await _saved(rt, clock, fetcher, FREE_TOOL, "TOOL")
    assert client.get(f"/api/items/{tool}").json()["can_wishlist"] is True
    added = _wishlist(client, tool, True).json()
    assert (added["status"], added["wishlist"], added["status_reason"]) == ("kept", True, "On your wishlist")
    removed = _wishlist(client, tool, False).json()
    assert (removed["status"], removed["wishlist"]) == ("archived", False)
    assert removed["status_reason"] == removed["relevance_reason"]

    tacos = await _saved(rt, clock, fetcher, TACOS, "TACO")
    assert client.get(f"/api/items/{tacos}").json()["threshold_decision"] == "keep"
    assert _wishlist(client, tacos, True).json()["status"] == "kept"
    assert _ids(client, "wishlist") == [tacos] and tacos not in _ids(client, "kept")
    assert _wishlist(client, tacos, False).json()["status"] == "kept"
    assert _ids(client, "kept") == [tacos]


def _overrides(item_id: int) -> tuple[Any, ...]:
    with db.read_session() as s:
        row = s.get(Item, item_id)
        assert row is not None
        return row.user_override, row.overridden_at, row.wishlist, row.wishlist_override


async def test_adding_beats_your_archive_and_undo_restores_it(
    rt: Runtime, clock: Clock, fetcher: FakeFetcher, goal: int, client: TestClient
) -> None:
    tacos = await _saved(rt, clock, fetcher, TACOS, "TACO")
    assert client.post(f"/api/items/{tacos}/actions/archive").json()["status"] == "archived"
    archived_at = _overrides(tacos)[1]
    clock.advance(days=1)
    assert _wishlist(client, tacos, True).json()["status"] == "kept"
    assert _overrides(tacos) == ("archive", archived_at, True, True), "your archive is left as it was"
    assert [e.title for e in queries.recent_override_examples()] == [TACOS]
    undone = _wishlist(client, tacos, False).json()
    assert (undone["status"], undone["status_reason"]) == ("archived", "Archived by you")
    assert _ids(client, "archived") == [tacos]


async def test_archiving_a_post_you_added_takes_it_off_the_wishlist(
    rt: Runtime, clock: Clock, fetcher: FakeFetcher, goal: int, client: TestClient
) -> None:
    tool = await _saved(rt, clock, fetcher, FREE_TOOL, "TOOL")
    _wishlist(client, tool, True)
    archived = client.post(f"/api/items/{tool}/actions/archive").json()
    assert (archived["status"], archived["wishlist"]) == ("archived", False)
    assert _overrides(tool)[2:] == (False, None), "the hand add is cleared, back to the extracted flag"
    assert _ids(client, "wishlist") == [] and _ids(client, "archived") == [tool]
    assert client.post(f"/api/items/{tool}/actions/keep").json()["wishlist"] is False


async def test_your_archive_wins_over_the_wishlist(
    rt: Runtime, clock: Clock, fetcher: FakeFetcher, goal: int, client: TestClient
) -> None:
    jacket = await _saved(rt, clock, fetcher, JACKET, "JACKET")
    assert client.post(f"/api/items/{jacket}/actions/archive").json()["status"] == "archived"
    client.post(f"/api/items/{jacket}/actions/reprocess")
    await rt.worker.run_item(jacket)
    assert client.get(f"/api/items/{jacket}").json()["status"] == "archived"


async def test_the_wishlist_field_means_on_the_wishlist_shelf(
    rt: Runtime, clock: Clock, fetcher: FakeFetcher, goal: int, client: TestClient
) -> None:
    kept = await _saved(rt, clock, fetcher, JACKET, "JACKET")
    archived = await _saved(rt, clock, fetcher, JACKET, "JACKET2")
    done = await _saved(rt, clock, fetcher, JACKET, "JACKET3")
    client.post(f"/api/items/{archived}/actions/archive")
    client.post(f"/api/items/{done}/actions/done")
    assert _overrides(archived)[2] is True, "the extracted flag is still stored"

    item = client.get(f"/api/items/{archived}").json()
    assert (item["status"], item["wishlist"], item["can_wishlist"]) == ("archived", False, True)
    rows = [
        i for view in ("kept", "wishlist", "archived") for i in client.get("/api/items", params={"view": view}).json()
    ]
    assert {i["id"]: i["wishlist"] for i in rows} == {kept: True, archived: False, done: False}
    assert [i["id"] for i in rows if i["wishlist"]] == _ids(client, "wishlist")


async def test_clearing_your_choice_follows_the_extracted_flag_again(
    rt: Runtime, clock: Clock, fetcher: FakeFetcher, goal: int, client: TestClient, wish_llm: WishLLM
) -> None:
    tool = await _saved(rt, clock, fetcher, FREE_TOOL, "TOOL")
    assert _wishlist(client, tool, True).json()["wishlist_override"] is True
    cleared = _wishlist(client, tool, None).json()
    assert (cleared["status"], cleared["wishlist"], cleared["wishlist_override"]) == ("archived", False, None)

    wish_llm.wishlist = True
    client.post(f"/api/items/{tool}/actions/reprocess")
    await rt.worker.run_item(tool)
    after = client.get(f"/api/items/{tool}").json()
    assert (after["status"], after["wishlist"]) == ("kept", True), "a later extraction decides again"

    jacket = await _saved(rt, clock, fetcher, JACKET, "JACKET")
    assert _wishlist(client, jacket, False).json()["wishlist"] is False
    back = _wishlist(client, jacket, None).json()
    assert (back["status"], back["wishlist"], back["wishlist_override"]) == ("kept", True, None)


async def test_archiving_a_post_you_added_whose_card_no_longer_parses(
    rt: Runtime, clock: Clock, fetcher: FakeFetcher, goal: int, client: TestClient
) -> None:
    tool = await _saved(rt, clock, fetcher, FREE_TOOL, "TOOL")
    _wishlist(client, tool, True)
    _break_card(tool)
    r = client.post(f"/api/items/{tool}/actions/archive")
    assert r.status_code == 200
    assert _overrides(tool)[2:] == (False, None)
    assert _wishlist(client, tool, None).status_code == 200


async def test_only_kept_or_archived_posts_take_a_wishlist_change(
    rt: Runtime, clock: Clock, fetcher: FakeFetcher, goal: int, client: TestClient
) -> None:
    jacket = await _saved(rt, clock, fetcher, JACKET, "JACKET")
    client.post(f"/api/items/{jacket}/actions/done")
    r = _wishlist(client, jacket, False)
    assert r.status_code == 409
    assert client.get(f"/api/items/{jacket}").json()["can_wishlist"] is False
    assert _wishlist(client, 999, True).status_code == 404


async def test_reprocess_recomputes_the_flag_unless_you_set_it_by_hand(
    rt: Runtime, clock: Clock, fetcher: FakeFetcher, goal: int, client: TestClient, wish_llm: WishLLM
) -> None:
    async def reprocess(item_id: int) -> dict[str, Any]:
        client.post(f"/api/items/{item_id}/actions/reprocess")
        await rt.worker.run_item(item_id)
        return client.get(f"/api/items/{item_id}").json()

    jacket = await _saved(rt, clock, fetcher, JACKET, "JACKET")
    tool = await _saved(rt, clock, fetcher, FREE_TOOL, "TOOL")
    _wishlist(client, tool, True)

    wish_llm.wishlist = False
    after = await reprocess(jacket)
    assert (after["status"], after["wishlist"]) == ("archived", False), "no hand choice: the new card decides"
    scored = len(wish_llm.scored)
    after = await reprocess(tool)
    assert (after["status"], after["wishlist"]) == ("kept", True), "your add survives"
    assert (after["relevance_score"], len(wish_llm.scored)) == (None, scored), "your add skips scoring too"

    wish_llm.wishlist = True
    _wishlist(client, tool, False)
    after = await reprocess(tool)
    assert (after["status"], after["wishlist"]) == ("archived", False), "your removal survives"


def _break_card(item_id: int) -> None:
    with db.write_session() as s:
        row = s.get(Item, item_id)
        assert row is not None and row.details is not None
        row.details = {k: v for k, v in row.details.items() if k != "name"}


def _put_on_wishlist(*item_ids: int) -> None:
    with db.write_session() as s:
        for row in s.exec(select(Item).where(col(Item.id).in_(item_ids))).all():
            row.wishlist = row.wishlist_override = True


async def test_the_digest_leaves_the_ai_out_and_rotates_its_wishlist_picks(
    rt: Runtime, clock: Clock, wish_llm: WishLLM
) -> None:
    topic = add_topic("Gear", clock)
    for i in (1, 2, 3, 4):
        add_post(i, topic, clock())
    _put_on_wishlist(2, 3, 4)

    first = await digest.deliver_digest(clock(), rt.llm, rt.notifier)
    assert first is not None
    assert [i.id for i in first.wishlist] == [2, 3], "never shown first, oldest saved first"
    assert {i.item_id for i in wish_llm.digest_inputs[0].items} == {1}
    assert not {2, 3, 4} & {*first.item_ids, *(p.item.id for p in first.top)}

    clock.advance(days=7)
    second = await digest.deliver_digest(clock(), rt.llm, rt.notifier)
    assert second is not None
    assert [i.id for i in second.wishlist] == [4, 2], "the one never shown, then the longest since shown"
    assert {i.item_id for i in wish_llm.digest_inputs[1].items} == {1}
    with db.read_session() as s:
        roles = s.exec(select(DigestEntry.item_id).where(DigestEntry.role == DigestRole.wishlist)).all()
    assert sorted(roles) == [2, 2, 3, 4]

    store.apply_action(2, UserAction.done, clock(), llm_ready=True)
    later = digest.get_digest(second.id, llm_ready=True)
    assert later is not None and [i.id for i in later.wishlist] == [4], "a bought post drops out"


def test_topic_tabs_leave_wishlist_posts_out(rt: Runtime, clock: Clock) -> None:
    gear = add_topic("Gear", clock)
    tacos = add_topic("Tacos", clock)
    add_post(1, gear, clock())
    add_post(2, tacos, clock())
    add_post(3, tacos, clock())
    _put_on_wishlist(1, 3)
    tabs = digest.list_digests(llm_ready=True).topics
    assert [(t.topic.name, t.open) for t in tabs] == [("Tacos", 1)]
    tab = digest.topic_digest(tacos, llm_ready=True)
    assert tab is not None and [p.item.id for p in tab.next] == [2] and tab.new == []
    assert queries.wishlist_rotation(5) == [1, 3]


async def test_a_post_added_to_the_wishlist_while_the_digest_is_written_is_queued_once(
    rt: Runtime, clock: Clock, wish_llm: WishLLM
) -> None:
    topic = add_topic("Gear", clock)
    add_post(1, topic, clock())
    wish_llm.while_composing = lambda: _put_on_wishlist(1)
    view = await digest.deliver_digest(clock(), rt.llm, rt.notifier)
    assert view is not None
    with db.read_session() as s:
        assert s.exec(select(DigestEntry.item_id)).all() == [1]


def test_the_rotation_counts_only_digests_that_showed_the_post(rt: Runtime, clock: Clock) -> None:
    topic = add_topic("Gear", clock)
    add_post(1, topic, clock())
    add_post(2, topic, clock())
    _put_on_wishlist(1, 2)
    with db.write_session() as s:
        d = Digest(period_start=clock(), period_end=clock(), created_at=clock(), model="fake")
        s.add(d)
        s.flush()
        assert d.id is not None
        s.add(DigestEntry(digest_id=d.id, item_id=1, position=1, role=DigestRole.wishlist))
        s.add(DigestEntry(digest_id=d.id, item_id=2, position=2, role=DigestRole.carryover))
    assert queries.wishlist_rotation(2) == [2, 1], "a carryover entry was never on screen"


async def test_a_product_card_that_no_longer_parses_leaves_its_list_working(
    rt: Runtime, clock: Clock, fetcher: FakeFetcher, goal: int, client: TestClient
) -> None:
    jacket = await _saved(rt, clock, fetcher, JACKET, "JACKET")
    _break_card(jacket)
    r = client.get("/api/items", params={"view": "wishlist"})
    assert r.status_code == 200
    assert [(i["id"], i["product"]) for i in r.json()] == [(jacket, None)]


def test_topics_leave_out_a_wishlist_post_that_already_has_a_topic(rt: Runtime, clock: Clock) -> None:
    gear = add_topic("Gear", clock)
    for i in (1, 2, 3):
        add_post(i, gear, clock())
    _put_on_wishlist(3)

    [summary] = [t for g in organize.list_topics().groups for t in g.topics]
    assert summary.kept == 2
    detail = organize.get_topic(gear)
    assert detail is not None and detail.freshness.posts == 2
    assert [(t.name, n) for t, n in organize.kept_counts()] == [("Gear", 2)]
    members = organize.topic_members(gear)
    assert members is not None and members.item_ids == {1, 2}
    on_topic = queries.list_items(queries.ItemFilter(statuses=frozenset(ItemStatus), topic_id=gear), llm_ready=True)
    assert [i.id for i in on_topic] == [2, 1]
    item = queries.get_item(3, llm_ready=True)
    assert item is not None and (item.topic, item.organization, item.gist) == (None, None, None)
    assert organize.next_outline_targets(10) == []
    with db.read_session() as s:
        assert s.exec(select(Outline.topic_id).where(Outline.item_id == 3)).one() == gear, "its topic data is kept"


def test_a_topic_whose_only_kept_post_is_on_the_wishlist_leaves_the_sidebar(rt: Runtime, clock: Clock) -> None:
    gear = add_topic("Gear", clock)
    add_post(1, gear, clock())
    _put_on_wishlist(1)
    assert organize.kept_counts() == []
