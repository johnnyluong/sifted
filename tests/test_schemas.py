from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from sift.domain import Decision, GoalCategory, ItemType, Source
from sift.llm.client import _image_blocks, extract_prompt, score_prompts
from sift.llm.prompts import Prompt, _source
from sift.llm.schemas import (
    ExtractInput,
    ExtractOutput,
    GoalBrief,
    OtherCard,
    OtherDetails,
    ScoreInput,
    ScoreOutput,
    parse_card,
)


def test_card_literals_cover_every_item_type() -> None:
    schema = TypeAdapter(ExtractOutput).json_schema()
    consts = {v["properties"]["item_type"]["const"] for k, v in schema["$defs"].items() if k.endswith("Card")}
    assert consts == {t.value for t in ItemType}


def test_stored_card_round_trips() -> None:
    card = parse_card(
        ItemType.place,
        "Taco spot",
        "Great tacos.",
        "Go Friday",
        {
            "name": "Los Tacos",
            "kind": "restaurant",
            "neighborhood": "East Village",
            "city": "New York",
            "address": None,
            "why_notable": None,
            "what_to_order_or_do": ["al pastor"],
            "price_hint": "$",
            "maps_query": "Los Tacos East Village",
        },
    )
    assert card.item_type is ItemType.place
    assert card.details.neighborhood == "East Village"


def test_score_bounds_are_enforced_client_side() -> None:
    with pytest.raises(ValidationError):
        ScoreOutput(relevance_score=140, matched_goal_id=None, relevance_reason="x", decision=Decision.keep)


def test_every_prompt_file_exists_and_renders() -> None:
    card = OtherCard(
        item_type=ItemType.other, title="t", summary="s", next_action=None, details=OtherDetails(key_points=[])
    )
    goals = [GoalBrief(id=1, title="Coffee shop", description="open one", category=GoalCategory.entrepreneurial)]
    system, user = score_prompts(ScoreInput(card=card, values_text="craft", goals=goals, examples=[], threshold=60))
    assert "id 1" in system and ">= 60" in system and '"title": "t"' in user
    text = extract_prompt(
        ExtractInput(
            source=Source.instagram,
            author_handle=None,
            caption="cap",
            post_text=None,
            transcript=None,
            frames=["a.jpg"],
            notes=[],
        )
    )
    assert "cap" in text and "1 image(s)" in text
    assert all(_source(p.value).strip() for p in Prompt)


def test_the_llm_is_sent_only_image_types_it_reads(tmp_path: Path) -> None:
    files = {
        "a.jpg": b"\xff\xd8\xff\xe0rest",
        "b.png": b"\x89PNG\r\n\x1a\nrest",
        "c.webp": b"RIFF\x00\x00\x00\x00WEBPVP8",
        "d.gif": b"GIF89a\x01\x00",
        "e.heic": b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00",
        "f.txt": b"not an image",
    }
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
    blocks = _image_blocks([tmp_path / name for name in files])
    assert [dict(b["source"]).get("media_type") for b in blocks if b["type"] == "image"] == [
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/gif",
    ]


def _count(node: object, key: str) -> int:
    if isinstance(node, dict):
        return (key in node) + sum(_count(v, key) for v in node.values())
    if isinstance(node, list):
        return sum(_count(v, key) for v in node)
    return 0


def _optional_properties(node: object) -> int:
    if isinstance(node, dict):
        own = 0
        if node.get("type") == "object" and "properties" in node:
            own = len(set(node["properties"]) - set(node.get("required", [])))
        return own + sum(_optional_properties(v) for v in node.values())
    if isinstance(node, list):
        return sum(_optional_properties(v) for v in node)
    return 0


def test_strict_schemas_stay_inside_their_union_budget() -> None:
    """Each nullable field is a union in the compiled grammar, which has a limit.
    A new nullable field or object union fails here instead of as a 400."""
    from anthropic.lib._parse._transform import transform_schema

    from sift.llm.schemas import BriefDraft, DigestDraft, OutlineDraft, SetupDraft, TopicPlanDraft

    budget = {ScoreOutput: 1, DigestDraft: 1, OutlineDraft: 2, BriefDraft: 0, TopicPlanDraft: 0, SetupDraft: 0}
    for schema, unions in budget.items():
        wire = transform_schema(schema.model_json_schema())
        assert (_count(wire, "anyOf"), _count(wire, "oneOf"), _optional_properties(wire)) == (unions, 0, 0), schema


def test_organize_prompts_render() -> None:
    from sift.llm.client import brief_prompts, outline_prompts, plan_prompts
    from sift.llm.schemas import (
        BriefInput,
        BriefPointIn,
        BriefSourceIn,
        OutlineInput,
        PlanPost,
        PlanTopicLine,
        TopicMoveExample,
        TopicOption,
        TopicPlanInput,
    )

    card = OtherCard(
        item_type=ItemType.other, title="t", summary="s", next_action=None, details=OtherDetails(key_points=[])
    )
    goals = [GoalBrief(id=1, title="Market the app", description="SEO", category=GoalCategory.entrepreneurial)]
    system, user = outline_prompts(
        OutlineInput(
            source=Source.instagram,
            card=card,
            caption="cap",
            on_screen_text=None,
            transcript_excerpt="talk",
            topics=[TopicOption(id=4, name="SEO", description="Search.", size=3)],
            may_create_topic=False,
            label_vocabulary=["search console"],
            moves=[TopicMoveExample(title="x", from_topic=None, to_topic="SEO")],
        )
    )
    assert 'id 4 "SEO"' in system and "Do not propose" in system and "search console" in system
    assert "cap" in user and "talk" in user
    system, user = brief_prompts(
        BriefInput(
            topic="SEO",
            topic_description="Search.",
            goals=goals,
            sources=[BriefSourceIn(title="t", item_type=ItemType.idea, gist="g", points=[BriefPointIn(n=1, text="p")])],
            previous_points=["old point"],
        )
    )
    assert "Market the app" in system and '"n": 1' in user and "old point" in user
    system, user = plan_prompts(
        TopicPlanInput(
            goals=goals,
            topics=[PlanTopicLine(id=2, name="SEO", description="d", posts=5)],
            retired=["Gone"],
            posts=[PlanPost(title="t", item_type=ItemType.idea, summary="s")],
        )
    )
    assert "Gone" in system and 'id 2 "SEO"' in user and '"title": "t"' in user
