from __future__ import annotations

from collections.abc import Iterator
from itertools import count
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import col, select

from sift import db
from sift.domain import FailureKind, ProcessingError
from sift.items import store
from sift.items.lifecycle import UserAction
from sift.llm.fake import FakeLLM
from sift.llm.schemas import TopicFitDraft, TopicFitInput, TopicRebuildDraft, TopicRebuildInput
from sift.models import Outline, Topic
from sift.organize import model
from sift.organize.organizer import Organizer
from sift.runtime import Runtime
from sift.web.app import create_app
from tests.conftest import Clock
from tests.fakes import FakeFetcher

TACOS = "Best tacos in the East Village. The al pastor at this spot is worth the line."
BIRRIA = "Birria in the East Village restaurant. Get the consomme on the side."
CODES = count()


@pytest.fixture
def client(rt: Runtime, tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(rt, run_background=False, dist=tmp_path / "no-dist")) as c:
        yield c


async def kept(client: TestClient, rt: Runtime, clock: Clock, fetcher: FakeFetcher, *captions: str) -> list[int]:
    ids = []
    for caption in captions:
        fetcher.caption = caption
        [r] = client.post("/api/items", json={"text": f"https://www.instagram.com/reel/K{next(CODES)}/"}).json()
        await rt.worker.run_item(r["item"]["id"])
        clock.advance(minutes=1)
        ids.append(r["item"]["id"])
    org = Organizer(clock)
    while org.step(FakeLLM(), import_running=False):
        pass
    return ids


def shelve(clock: Clock, name: str, *posts: int, override: tuple[int, ...] = ()) -> int:
    with db.write_session() as s:
        t = Topic(name=name, slug=model.slug(name), created_at=clock(), updated_at=clock())
        s.add(t)
        s.flush()
        for pid in posts:
            row = s.get(Outline, pid)
            assert row is not None
            row.topic_id = t.id
        for pid in override:
            row = s.get(Outline, pid)
            assert row is not None
            row.topic_override_id = t.id
        assert t.id is not None
        return t.id


def outline(item_id: int) -> Outline:
    with db.read_session() as s:
        row = s.get(Outline, item_id)
        assert row is not None
        return row


def topic(topic_id: int) -> Topic:
    with db.read_session() as s:
        row = s.get(Topic, topic_id)
        assert row is not None
        return row


def live_names() -> set[str]:
    with db.read_session() as s:
        rows = s.exec(select(Topic).where(col(Topic.merged_into_id).is_(None), col(Topic.dissolved_at).is_(None)))
        return {t.name for t in rows.all()}


def planned(name: str, continues: list[int], posts: list[int]) -> dict[str, object]:
    return {"name": name, "description": f"{name} posts.", "continues": continues, "posts": posts}


async def test_a_rebuild_merges_into_the_largest_topic_creates_new_ones_and_retires_the_rest(
    client: TestClient, rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    a1, a2, b1, c1, c2, n1, left, unseen = await kept(client, rt, clock, fetcher, *[TACOS] * 8)
    store.apply_action(c2, UserAction.archive, clock(), llm_ready=True)
    untouched = live_names()
    big = shelve(clock, "Tacos", a1, a2, left, unseen)
    small, gone = shelve(clock, "Birria", b1), shelve(clock, "Pizza", c1, c2)

    plan = [planned("NYC food", [small, big], [a1, a2, b1, c1, c2]), planned("Side quests", [], [n1])]
    kept_aside = shelve(clock, "Travel")
    r = client.post("/api/topics/rebuild", json={"topics": plan, "resort": [left], "retire": [gone]})
    assert r.status_code == 200
    group = next(g for g in r.json()["groups"] if g["goal"] is not None)
    assert {t["name"]: t["kept"] for t in group["topics"]} == {"NYC food": 5, "Side quests": 1}

    assert (topic(big).name, topic(big).merged_into_id, topic(big).dissolved_at) == ("NYC food", None, None)
    assert topic(small).merged_into_id == big
    assert topic(gone).dissolved_at is not None
    assert client.get(f"/api/topics/{small}").json()["id"] == big
    assert [outline(i).topic_id for i in (a1, a2, b1, c1)] == [big] * 4
    assert (outline(left).topic_id, outline(left).needs_topic) == (None, True)
    assert (outline(c2).topic_id, outline(c2).needs_topic) == (None, False), "archived since the draft"
    assert (outline(unseen).topic_id, outline(unseen).needs_topic) == (big, False), "not in the draft"
    assert live_names() == {"NYC food", "Side quests", "Travel", *untouched}, "a topic the rebuild never named stays"
    assert topic(kept_aside).dissolved_at is None


async def test_a_post_moved_by_hand_stays_on_its_pick_through_the_merge(
    client: TestClient, rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    a1, a2, moved = await kept(client, rt, clock, fetcher, TACOS, TACOS, TACOS)
    base = shelve(clock, "Tacos", a1, a2, moved)
    pick = shelve(clock, "Taco trucks", override=(moved,))
    gone = shelve(clock, "Pizza", override=(a2,))

    r = client.post(
        "/api/topics/rebuild",
        json={
            "topics": [planned("Tacos", [pick, base], [a1, a2]), planned("Everything else", [], [])],
            "resort": [moved],
            "retire": [gone],
        },
    )
    assert r.status_code == 200
    row = outline(moved)
    assert (row.topic_override_id, row.needs_topic) == (base, False), "a hand pick is never sorted again"
    assert client.get(f"/api/items/{moved}").json()["topic"]["id"] == base
    assert topic(gone).dissolved_at is not None and outline(a2).topic_override_id is None


async def test_a_plan_may_take_the_name_of_a_topic_it_retires_or_merges(
    client: TestClient, rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    a1, b1, c1 = await kept(client, rt, clock, fetcher, TACOS, TACOS, TACOS)
    untouched = live_names()
    tacos, birria, pizza = shelve(clock, "Tacos", a1), shelve(clock, "Birria", b1), shelve(clock, "Pizza", c1)

    topics = [planned("Birria", [tacos], [a1]), planned("Tacos", [birria], [b1]), planned("pizza", [], [c1])]
    clash = client.post("/api/topics/rebuild", json={"topics": topics})
    assert clash.status_code == 409 and "already a topic" in clash.json()["detail"]
    r = client.post("/api/topics/rebuild", json={"topics": topics, "retire": [pizza]})
    assert r.status_code == 200
    assert (topic(tacos).name, topic(birria).name) == ("Birria", "Tacos")
    assert topic(pizza).dissolved_at is not None
    assert live_names() == {"Birria", "Tacos", "pizza", *untouched}


async def test_a_refused_rebuild_changes_nothing(
    client: TestClient, rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    a1, b1 = await kept(client, rt, clock, fetcher, TACOS, TACOS)
    tacos, birria = shelve(clock, "Tacos", a1), shelve(clock, "Birria", b1)
    before = live_names()

    refusals = [
        ([planned("Food", [tacos], [a1]), planned("FOOD!", [birria], [b1])], 409, 'Two topics are named "Food"'),
        ([planned("Food", [tacos], [a1]), planned("More", [tacos], [b1])], 409, "only one new topic"),
        ([planned("Food", [tacos], [a1]), planned("More", [birria], [a1])], 409, "only one topic"),
        ([planned("Food", [tacos, 999], [a1])], 404, "Topic not found"),
        ([planned("...", [tacos], [a1])], 409, "a letter or a digit"),
    ]
    for topics, code, message in refusals:
        r = client.post("/api/topics/rebuild", json={"topics": topics})
        assert (r.status_code, message in r.json()["detail"]) == (code, True), topics
    assert client.post("/api/topics/rebuild", json={"topics": []}).status_code == 422
    assert live_names() == before
    assert (outline(a1).topic_id, outline(b1).topic_id) == (tacos, birria)


async def test_the_draft_places_only_offered_posts_and_changes_nothing(
    client: TestClient, rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    posts = await kept(client, rt, clock, fetcher, TACOS, BIRRIA, TACOS)
    [extra] = await kept(client, rt, clock, fetcher, TACOS)
    store.apply_action(extra, UserAction.archive, clock(), llm_ready=True)
    before = live_names()

    r = client.post("/api/topics/rebuild/draft")
    assert r.status_code == 200
    plan = r.json()
    placed = [p["id"] for t in plan["topics"] for p in t["posts"]] + [p["id"] for p in plan["unsorted"]]
    assert sorted(placed) == sorted(posts)
    live = {o["id"] for o in client.get("/api/topics").json()["options"]}
    continued = [c["id"] for t in plan["topics"] for c in t["continues"]] + [t["id"] for t in plan["retiring"]]
    assert sorted(continued) == sorted(live)
    assert live_names() == before


async def test_a_draft_needs_two_kept_posts(
    client: TestClient, rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    await kept(client, rt, clock, fetcher, TACOS)
    r = client.post("/api/topics/rebuild/draft")
    assert r.status_code == 409 and "at least 2" in r.json()["detail"]


@pytest.mark.parametrize("llm", [None])
def test_a_draft_needs_an_llm(client: TestClient) -> None:
    r = client.post("/api/topics/rebuild/draft")
    assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.json()["detail"]


class Broken(FakeLLM):
    def fit_topic(self, inp: TopicFitInput) -> tuple[TopicFitDraft, str]:
        raise RuntimeError("unexpected")


@pytest.mark.parametrize("llm", [Broken()])
async def test_an_unexpected_fit_failure_still_returns_the_new_topic(
    client: TestClient, rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    await kept(client, rt, clock, fetcher, TACOS)
    r = client.post("/api/topics", json={"name": "Tacos"})
    assert r.status_code == 201 and r.json()["not_moved"].startswith("Posts were not moved")


class Failing(FakeLLM):
    def rebuild_topics(self, inp: TopicRebuildInput) -> tuple[TopicRebuildDraft, str]:
        raise ProcessingError(FailureKind.llm_failed, "The model returned invalid output twice.", retryable=True)

    def fit_topic(self, inp: TopicFitInput) -> tuple[TopicFitDraft, str]:
        raise ProcessingError(FailureKind.llm_failed, "The model returned invalid output twice.", retryable=True)


@pytest.mark.parametrize("llm", [Failing()])
async def test_a_failed_draft_is_a_502_and_a_failed_fit_keeps_the_topic(
    client: TestClient, rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    await kept(client, rt, clock, fetcher, TACOS, TACOS)
    r = client.post("/api/topics/rebuild/draft")
    assert r.status_code == 502 and "invalid output twice" in r.json()["detail"]

    created = client.post("/api/topics", json={"name": "Tacos", "description": "Taco spots."})
    assert created.status_code == 201
    body = created.json()
    assert body["topic"]["name"] == "Tacos" and body["topic"]["kept"] == 0
    assert body["not_moved"].startswith("Posts were not moved")


async def test_a_new_topic_takes_the_posts_that_fit_but_never_one_moved_by_hand(
    client: TestClient, rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    t1, t2, birria, moved = await kept(client, rt, clock, fetcher, TACOS, TACOS, BIRRIA, TACOS)
    food = shelve(clock, "Food", override=(moved,))

    r = client.post("/api/topics", json={"name": "Taco crawl", "description": "Where to get tacos."})
    assert r.status_code == 201
    body = r.json()
    assert body["not_moved"] is None and body["topic"]["kept"] == 2
    new = body["topic"]["id"]
    assert [outline(i).topic_id for i in (t1, t2)] == [new, new]
    assert outline(birria).topic_id != new and outline(moved).topic_id != new
    assert client.get(f"/api/items/{moved}").json()["topic"]["id"] == food


async def test_a_topic_added_by_hand_is_listed_while_empty_and_its_name_is_taken(
    client: TestClient, rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher
) -> None:
    await kept(client, rt, clock, fetcher, TACOS)
    r = client.post("/api/topics", json={"name": "Weekend trips", "sort_posts": False})
    assert r.status_code == 201 and r.json()["not_moved"] is None
    groups = client.get("/api/topics").json()["groups"]
    no_goal = next(g for g in groups if g["goal"] is None)
    assert [(t["name"], t["kept"]) for t in no_goal["topics"]] == [("Weekend trips", 0)]

    clash = client.post("/api/topics", json={"name": " weekend TRIPS "})
    assert clash.status_code == 409 and "already a topic" in clash.json()["detail"]


@pytest.mark.parametrize("llm", [None])
def test_without_an_llm_a_new_topic_says_its_posts_were_not_moved(client: TestClient) -> None:
    r = client.post("/api/topics", json={"name": "Weekend trips"})
    assert r.status_code == 201 and "No LLM" in r.json()["not_moved"]
