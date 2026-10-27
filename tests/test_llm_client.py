from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anthropic
import httpx2

from sift.domain import GoalCategory, ItemType, Source
from sift.llm.client import AnthropicLLM
from sift.llm.prompts import DATA_RULE
from sift.llm.schemas import (
    ExtractInput,
    GoalBrief,
    IdeaCard,
    OutlineInput,
    PlaybookCard,
    ScoreInput,
    SetupAnswerIn,
    SetupInput,
    parse_card,
)

CARD = {
    "item_type": "idea",
    "title": "Agent web access",
    "summary": "An open source repo lets an agent read Reddit and X.",
    "next_action": None,
    "details": {"core_idea": "Give the agent a fetch skill", "creator": None, "how_to_apply": None},
}


def _message(tool_input: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": [{"type": "tool_use", "id": "tu_1", "name": "record_output", "input": tool_input}],
        "stop_reason": "tool_use",
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 10},
    }


INPUT = ExtractInput(
    source=Source.instagram, author_handle=None, caption="c", post_text=None, transcript="t", frames=[], notes=[]
)


def _replying(replies: list[dict[str, Any]]) -> tuple[AnthropicLLM, list[dict[str, Any]]]:
    requests: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json=replies[len(requests) - 1], headers={"request-id": "req_test"})

    client = anthropic.Anthropic(
        api_key="key", max_retries=0, http_client=httpx2.Client(transport=httpx2.MockTransport(handler))
    )
    llm = AnthropicLLM(
        client,
        extract_model="m",
        score_model="m",
        digest_model="digest",
        outline_model="haiku",
        brief_model="brief",
        effort="low",
    )
    return llm, requests


def test_extract_validates_the_tool_input_and_retries_once() -> None:
    replies = [_message({"card": {"item_type": "idea"}}), _message({"card": CARD, "on_screen_text": None})]
    llm, requests = _replying(replies)

    out, model = llm.extract(INPUT)

    assert isinstance(out.card, IdeaCard) and out.card.title == "Agent web access"
    assert model == "m" and len(requests) == 2
    assert "tool_choice" not in requests[0] and "output_config" in requests[0]
    assert [t["name"] for t in requests[0]["tools"]] == ["record_output"]


def test_extract_accepts_a_card_sent_as_a_json_string() -> None:
    details = json.dumps(CARD["details"])
    replies = [_message({"card": json.dumps({**CARD, "details": details}), "on_screen_text": None})]
    llm, requests = _replying(replies)

    out, _ = llm.extract(INPUT)

    assert isinstance(out.card, IdeaCard) and out.card.details.core_idea == "Give the agent a fetch skill"
    assert len(requests) == 1


def test_extract_decodes_a_list_sent_as_a_json_string_inside_the_card() -> None:
    card = {
        "item_type": "playbook",
        "title": "SEO checklist",
        "summary": "Steps.",
        "next_action": None,
        "details": {"goal": "Rank", "steps": json.dumps(["a", "b"]), "tools": [], "examples": [], "caveats": []},
    }
    llm, requests = _replying([_message({"card": json.dumps(card), "on_screen_text": None})])

    out, _ = llm.extract(INPUT)

    assert isinstance(out.card, PlaybookCard) and out.card.details.steps == ["a", "b"]
    assert len(requests) == 1


def test_extract_retries_when_a_stringified_card_is_not_json() -> None:
    llm, requests = _replying(
        [_message({"card": "not json", "on_screen_text": None}), _message({"card": CARD, "on_screen_text": None})]
    )

    out, _ = llm.extract(INPUT)

    assert isinstance(out.card, IdeaCard) and len(requests) == 2


def test_extract_recovers_fields_written_inside_the_card_string() -> None:
    saved = json.loads((Path(__file__).parent / "fixtures" / "extract_card_continued_in_string.json").read_text())
    llm, requests = _replying([_message(saved)])

    out, _ = llm.extract(INPUT)

    assert isinstance(out.card, PlaybookCard) and out.card.details.tools[0] == "Google Ads Keyword Planner"
    assert out.on_screen_text is not None and out.on_screen_text.startswith("Things I set up")
    assert len(requests) == 1


def _text_message(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "msg_2",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-5-5",
        "content": [{"type": "text", "text": json.dumps(payload)}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 10},
    }


def test_outline_is_a_strict_structured_call_on_the_outline_model() -> None:
    draft = {"gist": "g", "key_points": ["p"], "labels": ["seo"], "topic_id": 3, "new_topic": None}
    llm, requests = _replying([_text_message(draft)])
    card = parse_card(ItemType.idea, "t", "s", None, CARD["details"])
    inp = OutlineInput(
        source=Source.instagram,
        card=card,
        caption=None,
        on_screen_text=None,
        transcript_excerpt=None,
        topics=[],
        may_create_topic=True,
        label_vocabulary=[],
        moves=[],
    )

    out, model = llm.outline(inp)

    assert (out.topic_id, model) == (3, "haiku")
    [request] = requests
    assert request["model"] == "haiku" and "tools" not in request
    assert request["output_config"]["format"]["type"] == "json_schema"


def test_an_over_long_reason_is_clipped_not_retried() -> None:
    reply = {"relevance_score": 70, "matched_goal_id": None, "relevance_reason": "x" * 1_000, "decision": "keep"}
    llm, requests = _replying([_text_message(reply)])
    card = parse_card(ItemType.idea, "t", "s", None, CARD["details"])

    out, _ = llm.score(ScoreInput(card=card, values_text="", goals=[], examples=[], threshold=60))

    assert len(out.relevance_reason) == 500 and len(requests) == 1


def test_draft_setup_is_a_strict_call_on_the_digest_model() -> None:
    draft = {
        "goals": [
            {"title": "Market my web app", "description": "SEO posts.", "category": "entrepreneurial", "revises": 0}
        ],
        "deactivate": [],
        "values_text": "Craft over hype.",
    }
    llm, requests = _replying([_text_message(draft)])
    current = GoalBrief(id=2, title="Cook more", description="", category=GoalCategory.personal)
    inp = SetupInput(
        answers=[SetupAnswerIn(id="saving", question="What have you saved lately, and why?", answer="SEO tips")],
        current_goals=[current],
        current_values="",
    )

    out, model = llm.draft_setup(inp)

    assert (out.goals[0].title, model) == ("Market my web app", "digest")
    [request] = requests
    assert request["model"] == "digest" and "tools" not in request
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert request["system"].endswith(DATA_RULE) and "id 2 [personal] Cook more" in request["system"]
    assert "SEO tips" in request["messages"][0]["content"][0]["text"]
