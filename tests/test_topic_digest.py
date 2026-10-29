from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from sift import db, digest
from sift.domain import Channel, Decision, DigestRole, ItemStatus, ItemType, Source
from sift.items import store
from sift.items.lifecycle import UserAction
from sift.llm.client import LLM
from sift.llm.fake import FakeLLM
from sift.models import Digest, DigestEntry, Item, Outline, Topic
from sift.organize import store as organize
from sift.runtime import Runtime
from sift.web.app import create_app
from tests.conftest import Clock
from tests.fakes import FakeFetcher
from tests.test_organize import brief_two_twins


@pytest.fixture
def forbid_llm(monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
    def refuse(*_: Any) -> Any:
        raise AssertionError("a topic digest must not call the LLM")

    def forbid() -> None:
        for name in (n for n in vars(LLM) if not n.startswith("_")):
            monkeypatch.setattr(FakeLLM, name, refuse)

    return forbid


def add_topic(name: str, clock: Clock, *, description: str = "") -> int:
    with db.write_session() as s:
        t = Topic(name=name, slug=name.lower(), description=description, created_at=clock(), updated_at=clock())
        s.add(t)
        s.flush()
        assert t.id is not None
        return t.id


def add_post(
    i: int,
    topic_id: int,
    decided: datetime,
    *,
    score: int = 70,
    status: ItemStatus = ItemStatus.kept,
    gist: str | None = None,
) -> None:
    with db.write_session() as s:
        s.add(
            Item(
                id=i,
                source=Source.instagram,
                canonical_id=f"C{i}",
                url=f"https://www.instagram.com/reel/C{i}/",
                clean_url=f"https://www.instagram.com/reel/C{i}/",
                origin_channel=Channel.web,
                received_at=decided,
                status=status,
                item_type=ItemType.idea,
                title=f"Post {i}",
                summary=f"Summary {i}",
                details={"core_idea": f"Idea {i}", "creator": None, "how_to_apply": None},
                next_action=f"Action {i}",
                relevance_reason=f"Reason {i}",
                relevance_score=score,
                threshold_decision=Decision.keep,
                fetched_at=decided,
                media_processed_at=decided,
                extracted_at=decided,
                scored_at=decided,
                decided_at=decided,
            )
        )
        s.flush()
        s.add(
            Outline(
                item_id=i,
                extracted_at=decided,
                outlined_at=decided,
                model="fake",
                gist=f"Gist {i}" if gist is None else gist,
                key_points=["p"],
                labels=[],
                topic_id=topic_id,
            )
        )


def add_digest(digest_id: int, at: datetime, shown: list[int]) -> None:
    with db.write_session() as s:
        s.add(Digest(id=digest_id, period_start=at, period_end=at, created_at=at, model="fake"))
        s.flush()
        for position, i in enumerate(shown, 1):
            s.add(DigestEntry(digest_id=digest_id, item_id=i, position=position, role=DigestRole.pick))


def view(topic_id: int) -> digest.TopicDigestView:
    v = digest.topic_digest(topic_id, llm_ready=True)
    assert v is not None
    return v


def ids(v: digest.TopicDigestView) -> tuple[list[int], list[int]]:
    return [p.item.id for p in v.next], [line.item.id for line in v.new]


def test_tabs_are_topics_with_a_kept_post_most_kept_first(rt: Runtime, clock: Clock) -> None:
    t0 = clock()
    counts = {"Tacos": 3, "Bars": 2, "Coffee": 1, "Art": 1}
    n = 0
    for name, kept in counts.items():
        topic_id = add_topic(name, clock)
        for _ in range(kept):
            n += 1
            add_post(n, topic_id, t0)
    finished = add_topic("Finished", clock)
    add_post(90, finished, t0, status=ItemStatus.done)
    add_post(91, finished, t0, status=ItemStatus.archived)

    tabs = digest.list_digests(llm_ready=True).topics
    assert [(t.topic.name, t.open) for t in tabs] == [("Tacos", 3), ("Bars", 2), ("Art", 1), ("Coffee", 1)]


def test_picks_the_highest_scores_and_lists_the_rest_not_yet_in_a_digest(
    rt: Runtime, clock: Clock, forbid_llm: Callable[[], None]
) -> None:
    forbid_llm()
    t0 = clock()
    tacos = add_topic("Tacos", clock, description="Where to eat tacos")
    other = add_topic("Bars", clock)
    after, before = t0 + timedelta(hours=1), t0 - timedelta(days=10)
    for i, score in ((1, 60), (3, 80), (6, 50), (7, 40)):
        add_post(i, tacos, after, score=score)
    add_post(8, tacos, after, score=30, gist="")
    add_post(2, tacos, before, score=95)
    add_post(4, tacos, before, score=90)
    add_post(5, tacos, before - timedelta(days=10), score=99)
    add_post(11, tacos, before, score=20)
    add_post(9, tacos, after, score=99, status=ItemStatus.done)
    add_post(10, other, after, score=99)
    add_digest(1, t0 - timedelta(days=14), [5])
    add_digest(2, t0 - timedelta(days=7), [5, 2, 4])
    add_digest(3, t0, [5])

    v = view(tacos)
    assert v.topic.name == "Tacos" and v.overview == "Where to eat tacos"
    assert ids(v) == ([2, 4, 3], [1, 6, 7, 8, 11]), "5 was shown too often; 9 is done; 10 is another topic"
    first = v.next[0]
    assert (first.why, first.next_action, first.refill) == ("Reason 2", "Action 2", False)
    assert [line.line for line in v.new] == ["Gist 1", "Gist 6", "Gist 7", "Summary 8", "Gist 11"]

    store.apply_action(3, UserAction.done, clock(), llm_ready=True)
    assert ids(view(tacos)) == ([2, 4, 1], [6, 7, 8, 11])


def test_a_shown_post_outranks_a_new_one_with_a_lower_score_and_over_shown_posts_wait(
    rt: Runtime, clock: Clock
) -> None:
    t0 = clock()
    tacos = add_topic("Tacos", clock)
    add_post(1, tacos, t0 + timedelta(hours=1), score=40)
    add_post(2, tacos, t0 - timedelta(days=10), score=80)
    add_post(4, tacos, t0 - timedelta(days=10), score=90)
    add_post(5, tacos, t0 - timedelta(days=20), score=99)
    add_digest(1, t0 - timedelta(days=14), [5])
    add_digest(2, t0 - timedelta(days=7), [5, 2, 4])
    add_digest(3, t0, [5])

    assert ids(view(tacos)) == ([4, 2, 1], [])


def test_before_the_first_digest_every_kept_post_is_new(rt: Runtime, clock: Clock) -> None:
    tacos = add_topic("Tacos", clock)
    for i, score in enumerate((50, 90, 70, 60, 80), 1):
        add_post(i, tacos, clock(), score=score)

    assert ids(view(tacos)) == ([2, 5, 3], [4, 1])


async def test_a_folded_post_leaves_its_place_to_its_cover(
    rt: Runtime, clock: Clock, goal: int, fetcher: FakeFetcher, forbid_llm: Callable[[], None]
) -> None:
    first, _, topic_id, _ = await brief_two_twins(rt, clock, fetcher)
    forbid_llm()
    v = view(topic_id)
    assert ids(v) == ([first], [])
    assert v.overview


@pytest.fixture
def client(rt: Runtime, tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(rt, run_background=False, dist=tmp_path / "no-dist")) as c:
        yield c


def test_the_api_follows_a_merge_and_404s_a_removed_topic(
    client: TestClient, clock: Clock, forbid_llm: Callable[[], None]
) -> None:
    forbid_llm()
    survivor = add_topic("Tacos", clock)
    merged = add_topic("Taco spots", clock)
    removed = add_topic("Noise", clock)
    add_post(1, survivor, clock())
    add_post(2, merged, clock())
    organize.merge_topics(merged, survivor, clock())
    organize.dissolve_topic(removed, clock())

    body = client.get(f"/api/digests/topics/{merged}").json()
    assert body["topic"] == {"id": survivor, "name": "Tacos"}
    assert sorted(p["item"]["id"] for p in body["next"]) == [1, 2]
    assert client.get(f"/api/digests/topics/{removed}").status_code == 404
    assert client.get("/api/digests/topics/9999").status_code == 404
    assert client.get("/api/digests").json()["topics"] == [{"topic": {"id": survivor, "name": "Tacos"}, "open": 2}]
