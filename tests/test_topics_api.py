from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sift import db
from sift.llm.fake import FakeLLM
from sift.models import Topic
from sift.organize.organizer import Organizer
from sift.runtime import Runtime
from sift.web.app import create_app
from tests.conftest import Clock
from tests.fakes import FakeFetcher

CAPTION = "Best tacos in the East Village. The al pastor at this spot is worth the line."


@pytest.fixture
def client(rt: Runtime, tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(rt, run_background=False, dist=tmp_path / "no-dist")) as c:
        yield c


async def _kept(client: TestClient, rt: Runtime, clock: Clock, fetcher: FakeFetcher, *codes: str) -> list[int]:
    ids = []
    for code in codes:
        fetcher.caption = CAPTION
        [r] = client.post("/api/items", json={"text": f"https://www.instagram.com/reel/{code}/"}).json()
        await rt.worker.run_item(r["item"]["id"])
        clock.advance(minutes=1)
        ids.append(r["item"]["id"])
    org = Organizer(clock)
    while org.step(FakeLLM(), import_running=False):
        pass
    return ids


async def test_topics_are_grouped_by_goal_with_a_brief_on_request(
    client: TestClient, rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    first, second = await _kept(client, rt, clock, fetcher, "A1", "A2")
    view = client.get("/api/topics").json()
    [group] = view["groups"]
    [topic] = group["topics"]
    assert group["goal"]["id"] == goal and topic["kept"] == 2 and topic["brief_state"] == "none"
    assert [o["name"] for o in view["options"]] == [topic["name"]] and view["suggestions"] == []

    requested = client.post(f"/api/topics/{topic['id']}/brief")
    assert requested.status_code == 202 and requested.json()["brief_state"] == "writing"
    assert client.get("/api/status").json()["pulse"]["busy"] is True
    Organizer(clock).step(FakeLLM(), import_running=False)
    detail = client.get(f"/api/topics/{topic['id']}").json()
    assert detail["brief_state"] == "fresh" and detail["freshness"] == {"posts": 2, "in_brief": 2}
    assert detail["brief"]["sections"][0]["points"][0]["cites"][0]["n"] == 1
    assert {label["label"] for label in detail["labels"]} == set(client.get(f"/api/items/{first}").json()["labels"])

    rows = client.get("/api/items", params={"view": "kept", "topic_id": topic["id"]}).json()
    assert {r["id"]: (r["covered_by"] or {}).get("id") for r in rows} == {first: None, second: first}
    page = client.get(f"/api/items/{second}").json()
    assert page["organization"]["covered_by"]["id"] == first and page["topic"]["id"] == topic["id"]
    assert client.get("/api/labels", params={"topic_id": topic["id"]}).json() == detail["labels"]


async def test_rename_merge_move_and_dissolve(
    client: TestClient, rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    [item] = await _kept(client, rt, clock, fetcher, "A1")
    with db.write_session() as s:
        s.add(Topic(name="Food", slug="food", created_at=clock(), updated_at=clock()))
    options = {o["name"]: o["id"] for o in client.get("/api/topics").json()["options"]}
    places, food = options["Places"], options["Food"]

    clash = client.patch(f"/api/topics/{places}", json={"name": "  FOOD "})
    assert clash.status_code == 409 and "Merge" in clash.json()["detail"]
    renamed = client.patch(f"/api/topics/{places}", json={"name": "NYC tacos", "description": "Taco spots."}).json()
    assert (renamed["name"], renamed["description"]) == ("NYC tacos", "Taco spots.")

    moved = client.put(f"/api/items/{item}/topic", json={"topic_id": food}).json()
    assert moved["topic"]["id"] == food and moved["sift_topic"]["id"] == places and moved["topic_chosen_by"] == "you"
    assert client.put(f"/api/items/{item}/topic", json={"topic_id": 999}).status_code == 404
    back = client.put(f"/api/items/{item}/topic", json={"topic_id": None}).json()
    assert back["topic"]["id"] == places and back["topic_chosen_by"] == "sift"

    merged = client.post(f"/api/topics/{places}/merge", json={"into_id": food}).json()
    assert merged["id"] == food and merged["kept"] == 1
    assert client.get(f"/api/topics/{places}").json()["id"] == food
    assert client.post(f"/api/topics/{food}/merge", json={"into_id": food}).status_code == 409

    gone = client.delete(f"/api/topics/{food}")
    assert gone.status_code == 200 and gone.json() == {"rehoming": 1}
    assert client.get(f"/api/topics/{food}").status_code == 404
    assert client.get(f"/api/items/{item}").json()["status"] == "kept"


async def test_writes_that_cannot_apply_explain_themselves(
    client: TestClient, rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    [item] = await _kept(client, rt, clock, fetcher, "A1")
    [topic] = client.get("/api/topics").json()["options"]
    lonely = client.post(f"/api/topics/{topic['id']}/brief")
    assert lonely.status_code == 409 and "at least 2" in lonely.json()["detail"]
    [r] = client.post("/api/items", json={"text": "https://www.instagram.com/reel/NEW/"}).json()
    unorganized = client.put(f"/api/items/{r['item']['id']}/topic", json={"topic_id": topic["id"]})
    assert unorganized.status_code == 409
    assert client.post(f"/api/topics/{topic['id']}/suggestions/99/dismiss").status_code == 404
    cross_site = client.delete(f"/api/topics/{topic['id']}", headers={"Sec-Fetch-Site": "cross-site"})
    assert cross_site.status_code == 403
    assert client.get(f"/api/items/{item}").json()["topic"]["id"] == topic["id"]
