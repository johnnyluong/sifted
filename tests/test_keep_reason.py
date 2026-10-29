from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from sift import db, goals
from sift.domain import Channel, Decision, GoalCategory, ItemStatus, ItemType, Origin
from sift.inbox import intake
from sift.items import queries, store
from sift.items.lifecycle import UserAction
from sift.llm.client import score_prompts, setup_prompts
from sift.llm.fake import FakeLLM
from sift.llm.schemas import (
    GoalBrief,
    KeptAnyway,
    OtherCard,
    OtherDetails,
    OverrideExample,
    ScoreInput,
    SetupDraft,
    SetupInput,
)
from sift.models import PROFILE_ID, Item, Profile
from sift.runtime import Runtime
from sift.web.app import create_app
from tests.conftest import Clock

ANSWERS = [{"question_id": "saving", "text": "SEO tips", "picked": []}]


class Recording(FakeLLM):
    def __init__(self) -> None:
        super().__init__()
        self.setup_inputs: list[SetupInput] = []

    def draft_setup(self, inp: SetupInput) -> tuple[SetupDraft, str]:
        self.setup_inputs.append(inp)
        return super().draft_setup(inp)


@pytest.fixture
def client(rt: Runtime, tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(rt, run_background=False, dist=tmp_path / "no-dist")) as c:
        yield c


def _archived(clock: Clock, code: str, title: str) -> int:
    [result] = intake.submit(f"https://www.instagram.com/reel/{code}/", Origin(Channel.web), clock(), llm_ready=True)
    assert isinstance(result, intake.Queued)
    now = clock()
    with db.write_session() as s:
        row = s.get(Item, result.item.id)
        assert row is not None
        row.status = ItemStatus.archived
        row.fetched_at = row.media_processed_at = row.extracted_at = row.scored_at = now
        row.item_type = ItemType.other
        row.title = title
        row.summary = "s"
        row.details = {"key_points": []}
        row.relevance_score = 20
        row.threshold_decision = Decision.archive
    assert result.item.id is not None
    return result.item.id


def _kept(clock: Clock, code: str = "K1", title: str = "Cold email teardown") -> int:
    item_id = _archived(clock, code, title)
    store.apply_action(item_id, UserAction.keep, clock(), llm_ready=True)
    return item_id


def _reason(client: TestClient, item_id: int, goal_id: int | None, note: str = "") -> Any:
    return client.put(f"/api/items/{item_id}/keep-reason", json={"goal_id": goal_id, "note": note})


def test_a_reason_is_saved_and_shown_on_the_post(client: TestClient, clock: Clock, goal: int) -> None:
    item_id = _kept(clock)
    r = _reason(client, item_id, goal, "  the subject lines alone  ")
    assert r.status_code == 200, r.text
    reason = r.json()["keep_reason"]
    assert (reason["goal_id"], reason["goal_title"], reason["note"]) == (
        goal,
        "Eat my way through the East Village tacos",
        "the subject lines alone",
    )
    assert client.get(f"/api/items/{item_id}").json()["keep_reason"] == reason
    assert r.json()["asks_keep_reason"] is True


def test_none_of_my_goals_is_a_reason_without_a_note(client: TestClient, clock: Clock) -> None:
    reason = _reason(client, _kept(clock), None).json()["keep_reason"]
    assert reason["goal_id"] is None and reason["goal_title"] is None and reason["note"] is None


def test_only_a_post_you_kept_takes_a_reason(client: TestClient, clock: Clock, goal: int) -> None:
    r = _reason(client, _archived(clock, "A1", "Archived"), goal)
    assert r.status_code == 409
    assert client.get("/api/setup").json()["kept_anyway"] == []


def test_a_post_the_filter_also_kept_takes_no_reason(client: TestClient, clock: Clock, goal: int) -> None:
    item_id = _kept(clock)
    with db.write_session() as s:
        row = s.get(Item, item_id)
        assert row is not None
        row.threshold_decision = Decision.keep
    assert _reason(client, item_id, goal).status_code == 409


def test_the_goal_must_be_active(client: TestClient, clock: Clock, goal: int) -> None:
    item_id = _kept(clock)
    assert _reason(client, item_id, 999).status_code == 404
    goals.update_goal(goal, clock(), active=False)
    assert _reason(client, item_id, goal).status_code == 404


def test_a_long_note_is_refused(client: TestClient, clock: Clock) -> None:
    assert _reason(client, _kept(clock), None, "x" * 281).status_code == 422


def test_archiving_the_post_drops_its_reason(client: TestClient, clock: Clock, goal: int) -> None:
    item_id = _kept(clock)
    _reason(client, item_id, goal, "for the hooks")
    detail = store.apply_action(item_id, UserAction.archive, clock(), llm_ready=True)
    assert detail.keep_reason is None
    store.apply_action(item_id, UserAction.keep, clock(), llm_ready=True)
    again = queries.get_item(item_id, llm_ready=True)
    assert again is not None and again.keep_reason is None


def test_scoring_examples_carry_the_reason(client: TestClient, clock: Clock, goal: int) -> None:
    _reason(client, _kept(clock, "K1", "With reason"), goal, "for the hooks")
    _kept(clock, "K2", "Without reason")
    reasons = {e.title: e.reason for e in queries.recent_override_examples()}
    assert reasons == {
        "With reason": 'it serves their goal "Eat my way through the East Village tacos"; in their words, "for the hooks"',
        "Without reason": "",
    }


def test_the_score_prompt_shows_a_reason_only_when_given() -> None:
    card = OtherCard(
        item_type=ItemType.other, title="t", summary="s", next_action=None, details=OtherDetails(key_points=[])
    )
    example = OverrideExample(
        title="Cold email",
        item_type=ItemType.idea,
        summary="s",
        system_decision=Decision.archive,
        user_decision=Decision.keep,
        reason="it fits none of their goals",
    )
    with_reason, _ = score_prompts(ScoreInput(card=card, values_text="", goals=[], examples=[example], threshold=60))
    assert "Why: it fits none of their goals." in with_reason
    without, _ = score_prompts(
        ScoreInput(
            card=card, values_text="", goals=[], examples=[example.model_copy(update={"reason": ""})], threshold=60
        )
    )
    assert "Why:" not in without


def test_the_setup_prompt_lists_kept_posts_only_when_there_are_some() -> None:
    base = SetupInput(
        answers=[],
        current_goals=[GoalBrief(id=1, title="g", description="", category=GoalCategory.other)],
        current_values="",
    )
    _, empty = setup_prompts(base)
    assert "<kept_anyway>" not in empty
    _, user = setup_prompts(
        base.model_copy(update={"kept_anyway": [KeptAnyway(title="Cold email", reason="it fits none of their goals")]})
    )
    assert '<kept_anyway>\n- "Cold email": it fits none of their goals\n</kept_anyway>' in user


@pytest.mark.parametrize("llm", [Recording()])
def test_the_setup_draft_reads_the_reasons(client: TestClient, clock: Clock, goal: int, llm: Recording) -> None:
    _reason(client, _kept(clock, "K1", "Cold email teardown"), None, "outreach for the app")
    _kept(clock, "K2", "No reason given")
    view = client.get("/api/setup").json()
    assert [k["title"] for k in view["kept_anyway"]] == ["Cold email teardown"]
    assert view["kept_since_setup"] == 1
    assert client.post("/api/setup/draft", json={"answers": ANSWERS}).status_code == 200
    [inp] = llm.setup_inputs
    assert [k.model_dump() for k in inp.kept_anyway] == [
        {
            "title": "Cold email teardown",
            "reason": 'it fits none of their goals; in their words, "outreach for the app"',
        }
    ]


def test_reasons_after_the_last_setup_are_counted(client: TestClient, clock: Clock, goal: int) -> None:
    _reason(client, _kept(clock, "K1", "Before"), goal)
    with db.write_session() as s:
        s.add(Profile(id=PROFILE_ID, setup_at=clock.advance(minutes=1), updated_at=clock()))
    clock.advance(minutes=1)
    _reason(client, _kept(clock, "K2", "After"), None)
    view = client.get("/api/setup").json()
    assert view["kept_since_setup"] == 1
    assert [k["title"] for k in view["kept_anyway"]] == ["After", "Before"]
