from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from sift import db, goals
from sift.config import Settings
from sift.domain import Channel
from sift.items import store
from sift.items.lifecycle import UserAction
from sift.llm.fake import FakeLLM
from sift.models import Item
from sift.runtime import Overrides, Runtime, build_runtime, migrate
from sift.web import services
from sift.web.app import create_app
from tests.conftest import Clock
from tests.fakes import FakeFetcher, download_error, fake_fetchers


@pytest.fixture
def client(rt: Runtime, tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(rt, run_background=False, dist=tmp_path / "no-dist")) as c:
        yield c


def _submit(client: TestClient, url: str, **body: str) -> int:
    [result] = client.post("/api/items", json={"text": url, **body}).json()
    return result["item"]["id"]


def _row(item_id: int) -> Item:
    with db.read_session() as s:
        row = s.get(Item, item_id)
        assert row is not None
        return row


def test_submit_reports_each_link_by_kind(client: TestClient) -> None:
    first = client.post("/api/items", json={"text": "https://www.instagram.com/reel/ABC/?igsh=1"})
    assert first.status_code == 202 and [r["kind"] for r in first.json()] == ["queued"]
    assert first.json()[0]["item"]["display_title"] == "Instagram post"
    again = client.post("/api/items", json={"text": "https://www.instagram.com/reel/ABC/"}).json()
    assert [r["kind"] for r in again] == ["duplicate"]
    mixed = client.post("/api/items", json={"text": "https://example.com/x https://www.threads.com/t/Q1"}).json()
    assert sorted(r["kind"] for r in mixed) == ["queued", "rejected"]
    assert client.post("/api/items", json={"text": "hello"}).json() == []


def test_submit_records_the_channel(client: TestClient) -> None:
    from_web = _submit(client, "https://www.instagram.com/reel/WEB/", channel="web")
    from_script = _submit(client, "https://www.instagram.com/reel/API/")
    assert _row(from_web).origin_channel is Channel.web
    assert _row(from_script).origin_channel is Channel.api
    assert client.post("/api/items", json={"text": "x", "channel": "telegram"}).status_code == 422


async def test_actions_follow_the_transition_table(client: TestClient, rt: Runtime, goal: int) -> None:
    item_id = _submit(client, "https://www.instagram.com/reel/ABC/")
    await rt.worker.run_item(item_id)
    kept = client.get(f"/api/items/{item_id}").json()
    assert kept["status"] == "kept" and kept["stage"] is None and kept["threshold_decision"] == "keep"
    archived = client.post(f"/api/items/{item_id}/actions/archive").json()
    assert archived["status"] == "archived" and archived["user_override"] == "archive"
    conflict = client.post(f"/api/items/{item_id}/actions/retry")
    assert conflict.status_code == 409 and conflict.json()["detail"] == "cannot retry an item that is archived"
    assert [i["id"] for i in client.get("/api/items", params={"view": "archived"}).json()] == [item_id]
    assert client.get("/api/items/999").status_code == 404


async def test_list_filters_by_goal_type_and_text(client: TestClient, rt: Runtime, goal: int) -> None:
    item_id = _submit(client, "https://www.instagram.com/reel/ABC/")
    await rt.worker.run_item(item_id)
    [item] = client.get("/api/items", params={"view": "kept", "goal_id": goal}).json()
    assert item["id"] == item_id
    assert client.get("/api/items", params={"view": "kept", "goal_id": goal + 1}).json() == []
    assert client.get("/api/items", params={"view": "kept", "type": item["item_type"]}).json() != []
    assert client.get("/api/items", params={"view": "kept", "q": "no-such-word"}).json() == []


def test_status_carries_the_frame(client: TestClient) -> None:
    body = client.get("/api/status").json()
    assert body["nav"] == {"inbox": 0, "kept": 0, "wishlist": 0, "archived": 0, "topics": 0}
    assert body["notice"] == "fake_llm" and body["threshold"] == 60
    assert body["timezone"] == "America/New_York"
    assert body["digest_schedule"] == "Sundays at 6:00pm"
    assert body["pulse"]["busy"] is False and body["in_motion"] == []


@pytest.mark.parametrize(
    ("cron", "words"),
    [
        ("0 18 * * SUN", "Sundays at 6:00pm"),
        ("30 7 * * *", "Daily at 7:30am"),
        ("0 9 * * MON-FRI", "Mondays to Fridays at 9:00am"),
        ("0 12 * * MON,THU", "Mondays and Thursdays at 12:00pm"),
        ("0 0 * * MON,WED,FRI", "Mondays, Wednesdays and Fridays at 12:00am"),
        ("*/5 * * * MON", "on its schedule"),
        ("0 18 1 * *", "on its schedule"),
        ("0 18 * 6 SUN", "on its schedule"),
        ("0 18 * * MON-FRI/2", "on its schedule"),
    ],
)
def test_digest_schedule_in_words(cron: str, words: str) -> None:
    assert services.digest_schedule(cron) == words


async def test_pulse_moves_with_the_pipeline_and_settles(client: TestClient, rt: Runtime, goal: int) -> None:
    idle = client.get("/api/status").json()
    item_id = _submit(client, "https://www.instagram.com/reel/ABC/")
    queued = client.get("/api/status").json()
    assert queued["pulse"]["revision"] != idle["pulse"]["revision"] and queued["pulse"]["busy"] is True
    assert queued["in_motion"] == [{"id": item_id, "state_label": "Queued", "stage": "fetch", "announce": True}]
    await rt.worker.run_item(item_id)
    done = client.get("/api/status").json()
    assert done["pulse"]["revision"] != queued["pulse"]["revision"] and done["pulse"]["busy"] is False
    assert done["in_motion"] == [] and done["nav"]["kept"] == 1
    assert client.get("/api/status").json()["pulse"] == done["pulse"]


async def test_a_reprocessed_item_is_in_motion_not_waiting(client: TestClient, rt: Runtime, goal: int) -> None:
    item_id = _submit(client, "https://www.instagram.com/reel/ABC/")
    await rt.worker.run_item(item_id)
    reprocessed = client.post(f"/api/items/{item_id}/actions/reprocess").json()
    assert reprocessed["waiting_for"] is None and reprocessed["in_motion"] is True
    assert reprocessed["state_label"] == "Queued"
    status = client.get("/api/status").json()
    assert status["in_motion"] == [{"id": item_id, "state_label": "Queued", "stage": "extract", "announce": True}]
    assert status["pulse"]["busy"] is True


def test_pulse_moves_when_a_goal_changes_elsewhere(client: TestClient, clock: Clock, goal: int) -> None:
    before = client.get("/api/status").json()["pulse"]["revision"]
    goals.update_goal(goal, clock.advance(minutes=1), title="Tacos")
    renamed = client.get("/api/status").json()["pulse"]["revision"]
    assert renamed != before
    goals.update_goal(goal, clock.advance(minutes=1), active=False)
    assert client.get("/api/status").json()["pulse"]["revision"] not in (before, renamed)


async def test_pulse_moves_when_a_retry_fails_again(
    client: TestClient, rt: Runtime, fetcher: FakeFetcher, clock: Clock, goal: int
) -> None:
    fetcher.errors = [download_error(), download_error()]
    item_id = _submit(client, "https://www.instagram.com/reel/RETRY/")
    await rt.worker.run_item(item_id)
    first = client.get("/api/status").json()
    clock.advance(minutes=2)
    await rt.worker.run_item(item_id)
    second = client.get("/api/status").json()
    assert (
        second["in_motion"]
        == first["in_motion"]
        == [{"id": item_id, "state_label": "Retrying soon", "stage": "fetch", "announce": True}]
    )
    assert second["pulse"]["revision"] != first["pulse"]["revision"]


async def test_pulse_sees_an_action_from_another_channel(
    client: TestClient, rt: Runtime, clock: Clock, goal: int
) -> None:
    item_id = _submit(client, "https://www.instagram.com/reel/ABC/")
    await rt.worker.run_item(item_id)
    before = client.get("/api/status").json()["pulse"]["revision"]
    store.apply_action(item_id, UserAction.done, clock.advance(minutes=1), llm_ready=True)
    done = client.get("/api/status").json()
    assert done["nav"]["kept"] == 1, "the Kept shelf counts done items, as its list shows them"
    store.apply_action(item_id, UserAction.undone, clock.advance(minutes=1), llm_ready=True)
    assert client.get("/api/status").json()["pulse"]["revision"] not in (before, done["pulse"]["revision"])


async def test_a_retry_waiting_on_backoff_is_not_busy(
    client: TestClient, rt: Runtime, fetcher: FakeFetcher, clock: Clock, goal: int
) -> None:
    fetcher.errors = [download_error()]
    item_id = _submit(client, "https://www.instagram.com/reel/RETRY/")
    await rt.worker.run_item(item_id)
    body = client.get("/api/status").json()
    assert body["in_motion"] == [{"id": item_id, "state_label": "Retrying soon", "stage": "fetch", "announce": True}]
    assert body["pulse"]["busy"] is False
    clock.advance(minutes=2)
    assert client.get("/api/status").json()["pulse"]["busy"] is True


def test_notice_without_goals_on_a_real_backend(tmp_path: Path, clock: Clock) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", llm_backend="anthropic")  # pyright: ignore[reportCallIssue]
    rt = build_runtime(
        settings,
        Overrides(fetchers=fake_fetchers(settings.uploads_dir), llm=FakeLLM(), use_llm_override=True, clock=clock),
    )
    migrate(settings)
    assert services.notice(rt, active_goals=0) is services.Notice.no_goals
    assert services.notice(rt, active_goals=1) is None


def test_list_returns_more_than_a_hundred_items_by_default(client: TestClient) -> None:
    links = " ".join(f"https://www.instagram.com/reel/BULK{n}/" for n in range(150))
    assert len(client.post("/api/items", json={"text": links}).json()) == 150
    assert len(client.get("/api/items", params={"view": "inbox"}).json()) == 150


def test_status_counts_only_active_goals(client: TestClient) -> None:
    client.post("/api/goals", json={"title": "Cook more", "category": "personal"})
    paused = client.post("/api/goals", json={"title": "Run a marathon", "category": "personal"}).json()
    client.patch(f"/api/goals/{paused['id']}", json={"active": False})
    assert client.get("/api/status").json()["active_goals"] == 1


def test_goals_and_values(client: TestClient) -> None:
    created = client.post("/api/goals", json={"title": "  Market my web app ", "category": "entrepreneurial"})
    assert created.status_code == 201 and created.json()["title"] == "Market my web app"
    assert client.post("/api/goals", json={"title": "   "}).status_code == 422
    assert client.post("/api/goals", json={"title": "x" * 121}).status_code == 422
    goal_id = created.json()["id"]
    assert client.patch(f"/api/goals/{goal_id}", json={"active": False}).json()["active"] is False
    assert client.get("/api/status").json()["active_goals"] == 0
    assert client.patch("/api/goals/999", json={"active": True}).status_code == 404
    assert client.put("/api/values", json={"values_text": "Craft over hype."}).json() == {
        "values_text": "Craft over hype."
    }
    assert client.get("/api/values").json() == {"values_text": "Craft over hype."}


async def test_digest_conflict_then_created(client: TestClient, rt: Runtime, goal: int) -> None:
    conflict = client.post("/api/digests")
    assert conflict.status_code == 409 and "Nothing new to surface" in conflict.json()["detail"]
    assert client.get("/api/digests").json() == {"latest": None, "earlier": [], "topics": []}
    item_id = _submit(client, "https://www.instagram.com/reel/ABC/")
    await rt.worker.run_item(item_id)
    before = client.get("/api/status").json()["pulse"]["revision"]
    created = client.post("/api/digests")
    assert created.status_code == 201 and created.json()["item_ids"] == [item_id]
    assert client.get(f"/api/digests/{created.json()['id']}").json() == created.json()
    assert client.get("/api/digests").json() == {"latest": created.json(), "earlier": [], "topics": []}
    assert client.get("/api/status").json()["pulse"]["revision"] != before


def _ids(picks: list[dict[str, Any]]) -> list[int]:
    return [p["item"]["id"] for p in picks]


async def test_a_done_pick_is_refilled_and_comes_back_on_undo(client: TestClient, rt: Runtime, goal: int) -> None:
    for n in range(4):
        await rt.worker.run_item(_submit(client, f"https://www.instagram.com/reel/PICK{n}/"))
    view = client.post("/api/digests").json()
    top = _ids(view["top"])
    [fourth] = set(view["item_ids"]) - set(top)
    assert len(top) == 3 and view["item_ids"][:3] == top and not any(p["refill"] for p in view["top"])

    client.post(f"/api/items/{top[0]}/actions/done")
    after = client.get("/api/digests").json()["latest"]
    assert _ids(after["top"]) == [*top[1:], fourth] and after["top"][2]["refill"] is True
    assert _ids(after["done"]) == [top[0]] and after["groups"] == []

    client.post(f"/api/items/{top[0]}/actions/undone")
    assert _ids(client.get(f"/api/digests/{view['id']}").json()["top"]) == top

    client.post(f"/api/items/{top[1]}/actions/archive")
    archived = client.get(f"/api/digests/{view['id']}").json()
    assert _ids(archived["top"]) == [top[0], top[2], fourth] and archived["done"] == []
    assert top[1] not in {line["item"]["id"] for g in archived["groups"] for line in g["lines"]}


async def test_thumbnail_is_served_only_from_media(client: TestClient, rt: Runtime, goal: int) -> None:
    item_id = _submit(client, "https://www.instagram.com/reel/ABC/")
    await rt.worker.run_item(item_id)
    url = client.get(f"/api/items/{item_id}").json()["thumbnail_url"]
    assert url == f"/api/items/{item_id}/thumbnail"
    r = client.get(url)
    assert r.status_code == 200 and r.headers["cache-control"] == "max-age=86400"
    assert client.get("/api/items/999/thumbnail").status_code == 404

    (rt.settings.data_dir / "outside.jpg").write_bytes(b"\xff\xd8\xff")
    with db.write_session() as s:
        row = s.get(Item, item_id)
        assert row is not None
        row.thumbnail_path = "media/../outside.jpg"
    assert client.get(url).status_code == 404
