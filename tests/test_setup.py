from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from sift import goals
from sift.domain import Channel, FailureKind, GoalCategory, ItemStatus, Origin, ProcessingError
from sift.inbox import intake
from sift.items import queries
from sift.llm.fake import FakeLLM
from sift.llm.schemas import GoalBrief, ProposedGoal, SetupDraft, SetupInput
from sift.runtime import Runtime
from sift.web.app import create_app
from tests.conftest import Clock

ANSWERS: list[dict[str, Any]] = [
    {"question_id": "saving", "text": "SEO tips and NYC date spots", "picked": []},
    {"question_id": "areas", "text": "Woodworking", "picked": ["marketing", "food"]},
    {"question_id": "strictness", "text": "", "picked": ["strict"]},
]


@pytest.fixture
def client(rt: Runtime, tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(rt, run_background=False, dist=tmp_path / "no-dist")) as c:
        yield c


def _plan(client: TestClient, answers: list[dict[str, Any]] = ANSWERS) -> dict[str, Any]:
    r = client.post("/api/setup/draft", json={"answers": answers})
    assert r.status_code == 200, r.text
    return r.json()


def test_setup_lists_the_questions_and_no_answers_before_the_first_apply(client: TestClient) -> None:
    view = client.get("/api/setup").json()
    assert [q["id"] for q in view["questions"]] == [q.id for q in goals.QUESTIONS]
    assert view["answers"] == [] and view["setup_at"] is None


@pytest.mark.parametrize(
    "answers",
    [
        [{"question_id": "nope", "text": "x", "picked": []}],
        [{"question_id": "saving", "text": "a", "picked": []}, {"question_id": "saving", "text": "b", "picked": []}],
        [{"question_id": "areas", "text": "", "picked": ["knitting"]}],
        [{"question_id": "strictness", "text": "", "picked": ["strict", "loose"]}],
        [{"question_id": "with_whom", "text": "my cousin", "picked": []}],
        [{"question_id": "saving", "text": "x" * 1_001, "picked": []}],
        [{"question_id": "saving", "text": "   ", "picked": []}],
        [],
    ],
)
def test_bad_answers_are_refused_before_any_llm_call(client: TestClient, answers: list[dict[str, Any]]) -> None:
    assert client.post("/api/setup/draft", json={"answers": answers}).status_code == 422


def test_a_draft_writes_nothing(client: TestClient) -> None:
    plan = _plan(client)
    assert [g["title"] for g in plan["add"]] == [
        "Marketing and growing a business",
        "Restaurants, bars and food spots",
        "Woodworking",
    ]
    assert "SEO tips and NYC date spots" in plan["values_text"] and plan["deactivate"] == []
    assert client.get("/api/goals").json() == []
    assert client.get("/api/setup").json()["answers"] == []
    assert client.get("/api/values").json() == {"values_text": ""}


@pytest.mark.parametrize("llm", [None])
def test_a_draft_needs_an_llm(client: TestClient) -> None:
    r = client.post("/api/setup/draft", json={"answers": ANSWERS})
    assert r.status_code == 503 and "add them by hand" in r.json()["detail"]


class Failing(FakeLLM):
    def draft_setup(self, inp: SetupInput) -> tuple[SetupDraft, str]:
        raise ProcessingError(FailureKind.llm_failed, "The model returned invalid output twice.", retryable=True)


@pytest.mark.parametrize("llm", [Failing()])
def test_a_failed_draft_is_a_502(client: TestClient) -> None:
    r = client.post("/api/setup/draft", json={"answers": ANSWERS})
    assert r.status_code == 502 and "invalid output twice" in r.json()["detail"]


def test_apply_saves_goals_values_and_answers_once(client: TestClient, clock: Clock) -> None:
    body = {**_plan(client), "answers": ANSWERS}
    first = client.post("/api/setup/apply", json=body)
    assert first.status_code == 200
    assert sorted(g["title"] for g in first.json()) == sorted(g["title"] for g in body["add"])
    clock.advance(minutes=1)
    again = client.post("/api/setup/apply", json=body).json()
    assert [(g["id"], g["title"], g["active"]) for g in again] == [
        (g["id"], g["title"], g["active"]) for g in first.json()
    ]
    assert client.get("/api/values").json()["values_text"] == body["values_text"]
    view = client.get("/api/setup").json()
    assert view["answers"] == ANSWERS and view["setup_at"] is not None
    assert client.get("/api/status").json()["active_goals"] == 3


def test_apply_revives_a_goal_with_the_drafted_title(client: TestClient, clock: Clock) -> None:
    old = goals.create_goal("Cook more", "Weeknight dinners", GoalCategory.personal, clock())
    goals.update_goal(old.id, clock(), active=False)
    add = [{"title": "cook MORE", "description": "Meal prep", "category": "personal"}]
    after = client.post("/api/setup/apply", json={"add": add, "deactivate": [], "values_text": "", "answers": ANSWERS})
    assert [(g["id"], g["title"], g["active"], g["description"]) for g in after.json()] == [
        (old.id, "Cook more", True, "Meal prep")
    ]


def test_apply_never_leaves_no_active_goal(client: TestClient, clock: Clock) -> None:
    only = goals.create_goal("Cook more", "", GoalCategory.personal, clock())
    body = {"add": [], "deactivate": [only.id], "values_text": "changed", "answers": ANSWERS}
    r = client.post("/api/setup/apply", json=body)
    assert r.status_code == 409 and r.json()["detail"] == "Keep at least one goal active."
    assert [g.active for g in goals.list_goals()] == [True]
    assert goals.get_values() == "" and goals.setup_view().setup_at is None
    unknown = client.post("/api/setup/apply", json={**body, "deactivate": [only.id + 1]})
    assert unknown.status_code == 404


def test_apply_deactivates_only_the_listed_goals(client: TestClient, clock: Clock) -> None:
    keep = goals.create_goal("Cook more", "", GoalCategory.personal, clock())
    drop = goals.create_goal("Run a marathon", "", GoalCategory.personal, clock())
    body = {**_plan(client), "answers": ANSWERS}
    client.post("/api/setup/apply", json={**body, "deactivate": [drop.id]})
    active = {g.title for g in goals.list_goals(active_only=True)}
    assert keep.title in active and drop.title not in active and len(active) == 4


async def test_items_waiting_for_goals_are_scored_after_apply(client: TestClient, rt: Runtime, clock: Clock) -> None:
    [queued] = intake.submit("https://www.instagram.com/reel/TACO1/", Origin(Channel.cli), clock(), llm_ready=True)
    assert isinstance(queued, intake.Queued)
    await rt.worker.run_item(queued.item.id)
    waiting = queries.get_item(queued.item.id, llm_ready=True)
    assert waiting is not None and waiting.waiting_for == "goals"
    add = [{"title": "East Village tacos", "description": "best taco spots", "category": "personal"}]
    client.post("/api/setup/apply", json={"add": add, "deactivate": [], "values_text": "", "answers": ANSWERS})
    await rt.worker.run_item(queued.item.id)
    scored = queries.get_item(queued.item.id, llm_ready=True)
    assert scored is not None and scored.status is ItemStatus.kept


def test_goal_and_values_routes_are_bounded(client: TestClient) -> None:
    assert client.post("/api/goals", json={"title": "Cook", "description": "x" * 601}).status_code == 422
    assert client.put("/api/values", json={"values_text": "x" * 4_001}).status_code == 422
    assert client.put("/api/values", json={"values_text": "x" * 4_000}).status_code == 200


def _draft(*goals_: tuple[str, int], deactivate: list[int] | None = None) -> SetupDraft:
    return SetupDraft(
        goals=[ProposedGoal(title=t, description="", category=GoalCategory.other, revises=r) for t, r in goals_],
        deactivate=deactivate or [],
        values_text="v",
    )


def test_normalize_setup_keeps_the_draft_inside_the_api_bounds() -> None:
    current = [GoalBrief(id=4, title="Cook more", description="", category=GoalCategory.personal)]
    titles = ["", "A" * 300, "Date nights", "date nights", "B", "C", "D", "E", "F"]
    draft = SetupDraft(
        goals=[ProposedGoal(title=t, description="d" * 2_000, category=GoalCategory.other, revises=0) for t in titles],
        deactivate=[4, 4, 99],
        values_text="  v  ",
    )
    plan = goals.normalize_setup(draft, current)
    assert [g.title for g in plan.add] == ["A" * 120, "Date nights", "B", "C", "D", "E"]
    assert {len(g.description) for g in plan.add} == {600}
    assert (plan.deactivate, plan.values_text) == ([4], "v")


def test_normalize_setup_ties_each_drafted_goal_to_at_most_one_current_goal() -> None:
    current = [
        GoalBrief(id=i, title=t, description="", category=GoalCategory.personal)
        for i, t in [(4, "Cook more"), (5, "Run a marathon"), (6, "Read more")]
    ]
    draft = _draft(("Cook at home", 4), ("Meal prep", 4), ("Learn piano", 99), ("read MORE", 0), deactivate=[4, 5, 6])
    plan = goals.normalize_setup(draft, current)
    assert [(g.title, g.revises) for g in plan.add] == [
        ("Cook at home", 4),
        ("Meal prep", 0),
        ("Learn piano", 0),
        ("read MORE", 6),
    ], "a second revise of one goal and an unknown id become new goals; a current title revises its goal"
    assert plan.deactivate == [5], "a goal the draft revises is not also turned off"


def test_a_redo_rewrites_a_current_goal_in_place(client: TestClient, clock: Clock) -> None:
    marketing = goals.create_goal("Marketing", "old", GoalCategory.entrepreneurial, clock())
    plan = _plan(client)
    assert [(g["title"], g["revises"]) for g in plan["add"]] == [
        ("Marketing and growing a business", marketing.id),
        ("Restaurants, bars and food spots", 0),
        ("Woodworking", 0),
    ]
    after = client.post("/api/setup/apply", json={**plan, "answers": ANSWERS}).json()
    assert len(after) == 3
    assert [(g["title"], g["category"], g["active"]) for g in after if g["id"] == marketing.id] == [
        ("Marketing and growing a business", "other", True)
    ]


def test_apply_rewrites_and_revives_the_goal_a_draft_revises(client: TestClient, clock: Clock) -> None:
    old = goals.create_goal("Cook more", "Weeknight dinners", GoalCategory.other, clock())
    goals.update_goal(old.id, clock(), active=False)
    add = [{"title": "Cook at home", "description": "Meal prep", "category": "personal", "revises": old.id}]
    body = {"add": add, "deactivate": [], "values_text": "", "answers": ANSWERS}
    after = client.post("/api/setup/apply", json=body).json()
    assert [(g["id"], g["title"], g["description"], g["category"], g["active"]) for g in after] == [
        (old.id, "Cook at home", "Meal prep", "personal", True)
    ]
    unknown = client.post("/api/setup/apply", json={**body, "add": [{**add[0], "revises": old.id + 1}]})
    assert unknown.status_code == 404


def test_apply_twice_gives_the_same_goals_when_a_new_goal_takes_a_revised_title(
    client: TestClient, clock: Clock
) -> None:
    old = goals.create_goal("Cook more", "", GoalCategory.personal, clock())
    add = [
        {"title": "Cook more", "description": "", "category": "personal", "revises": 0},
        {"title": "Cook at home", "description": "", "category": "personal", "revises": old.id},
    ]
    body = {"add": add, "deactivate": [], "values_text": "", "answers": ANSWERS}
    first = client.post("/api/setup/apply", json=body).json()
    clock.advance(minutes=1)
    again = client.post("/api/setup/apply", json=body).json()
    assert sorted(g["title"] for g in first) == ["Cook at home", "Cook more"]
    assert [(g["id"], g["title"]) for g in again] == [(g["id"], g["title"]) for g in first]


def test_a_new_goal_that_repeats_a_goal_another_row_rewrites_is_dropped(client: TestClient, clock: Clock) -> None:
    fitness = goals.create_goal("Fitness", "", GoalCategory.personal, clock())
    _, current = goals.scoring_context()
    for rows in [
        (("Get fit for summer", fitness.id), ("Fitness", 0)),
        (("Fitness", 0), ("Get fit for summer", fitness.id)),
    ]:
        plan = goals.normalize_setup(_draft(*rows), current)
        assert [(g.title, g.revises) for g in plan.add] == [("Get fit for summer", fitness.id)]
    body = {**plan.model_dump(), "answers": ANSWERS}
    after = client.post("/api/setup/apply", json=body).json()
    assert [(g["id"], g["title"]) for g in after] == [(fitness.id, "Get fit for summer")]


def _apply(client: TestClient, add: list[dict[str, Any]], deactivate: list[int] | None = None) -> Any:
    body = {"add": add, "deactivate": deactivate or [], "values_text": "changed", "answers": ANSWERS}
    return client.post("/api/setup/apply", json=body)


def test_apply_refuses_to_rename_a_goal_to_another_goals_title(client: TestClient, clock: Clock) -> None:
    cook = goals.create_goal("Cook more", "", GoalCategory.personal, clock())
    run = goals.create_goal("Run a marathon", "", GoalCategory.personal, clock())
    goals.update_goal(run.id, clock(), active=False)
    r = _apply(client, [{"title": "run a MARATHON", "category": "personal", "revises": cook.id}])
    assert r.status_code == 409
    assert r.json()["detail"] == "Another goal is already called run a MARATHON. Pick a different title."
    assert [g.title for g in goals.list_goals()] == ["Cook more", "Run a marathon"] and goals.get_values() == ""

    swap = [
        {"title": "Run a marathon", "category": "personal", "revises": cook.id},
        {"title": "Run a half", "category": "personal", "revises": run.id},
    ]
    assert sorted(g["title"] for g in _apply(client, swap).json()) == ["Run a half", "Run a marathon"]


def test_apply_refuses_a_new_goal_that_matches_a_goal_it_turns_off(client: TestClient, clock: Clock) -> None:
    goals.create_goal("Cook more", "", GoalCategory.personal, clock())
    fitness = goals.create_goal("Fitness", "", GoalCategory.personal, clock())
    r = _apply(client, [{"title": "fitness", "category": "personal"}], deactivate=[fitness.id])
    assert r.status_code == 409 and r.json()["detail"] == "You turned off Fitness and also added it. Keep one."
    assert [(g.title, g.active) for g in goals.list_goals()] == [("Cook more", True), ("Fitness", True)]


def test_apply_refuses_two_rows_that_land_on_one_goal(client: TestClient, clock: Clock) -> None:
    cook = goals.create_goal("Cook more", "Weeknight dinners", GoalCategory.personal, clock())
    twice = [
        {"title": "Cook at home", "category": "personal", "revises": cook.id},
        {"title": "Meal prep", "category": "personal", "revises": cook.id},
    ]
    r = _apply(client, twice)
    assert r.status_code == 409 and r.json()["detail"] == "Two drafted goals update the same goal. Keep one."

    renamed_and_new = [
        {"title": "Cook at home", "description": "Weeknights", "category": "personal", "revises": cook.id},
        {"title": "cook at HOME", "description": "Other", "category": "professional"},
    ]
    r = _apply(client, renamed_and_new)
    assert r.status_code == 409 and r.json()["detail"] == "Two goals are called Cook at home. Pick a different title."
    assert [(g.title, g.description) for g in goals.list_goals()] == [("Cook more", "Weeknight dinners")]


def test_apply_clears_a_description_the_plan_left_empty(client: TestClient, clock: Clock) -> None:
    cook = goals.create_goal("Cook more", "Weeknight dinners", GoalCategory.personal, clock())
    after = _apply(client, [{"title": "Cook more", "description": "", "category": "personal", "revises": cook.id}])
    assert [(g["title"], g["description"]) for g in after.json()] == [("Cook more", "")]
