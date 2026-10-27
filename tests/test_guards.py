from __future__ import annotations

import pytest

from sift.domain import Decision, GoalCategory, ItemType, Source
from sift.llm.guards import drop_invented_goal, ground_links, stated_url
from sift.llm.schemas import (
    ExtractInput,
    ExtractOutput,
    GoalBrief,
    ProductCard,
    ProductDetails,
    ScoreInput,
    ScoreOutput,
    parse_card,
)


@pytest.mark.parametrize(
    ("link", "evidence", "kept"),
    [
        ("https://shop.example.com/pan", "Get it at shop.example.com/pan today", "https://shop.example.com/pan"),
        ("shop.example.com/pan/", "SHOP.EXAMPLE.COM/PAN", "https://shop.example.com/pan/"),
        ("http://www.brand.com", "brand.com is the store.", "http://www.brand.com"),
        ("https://brand.com", "https://www.brand.com/sale", "https://brand.com"),
        ("https://brand.co", "Order from brand.com", None),
        ("https://brand.com", "Order from notbrand.com", None),
        ("https://evil.example", "No link here, check my bio", None),
        ("javascript:alert(1)", "javascript:alert(1)", None),
        ("data:text/html,<b>x</b>", "data:text/html,<b>x</b>", None),
    ],
)
def test_stated_url_keeps_only_links_the_post_states(link: str, evidence: str, kept: str | None) -> None:
    assert stated_url(link, evidence) == kept


def _extract(
    link: str | None, *, caption: str = "", on_screen: str | None = None
) -> tuple[ExtractOutput, ExtractInput]:
    card = ProductCard(
        item_type=ItemType.product,
        title="Carbon steel pan",
        summary="A pan.",
        next_action=None,
        details=ProductDetails(name="Pan", what_it_is="A pan", price=None, link=link),
    )
    inp = ExtractInput(
        source=Source.instagram,
        author_handle=None,
        caption=caption,
        post_text=None,
        transcript=None,
        frames=[],
        notes=[],
    )
    return ExtractOutput(card=card, on_screen_text=on_screen), inp


def _link(out: ExtractOutput) -> str | None:
    assert isinstance(out.card, ProductCard)
    return out.card.details.link


def test_ground_links_drops_a_link_the_post_never_states() -> None:
    assert _link(ground_links(*_extract("https://evil.example/buy", caption="Best pan ever"))) is None


def test_ground_links_keeps_a_link_from_the_caption() -> None:
    assert _link(ground_links(*_extract("pans.example/x", caption="pans.example/x"))) == "https://pans.example/x"


def test_ground_links_ignores_the_models_own_on_screen_text() -> None:
    echoed = ground_links(*_extract("https://evil.example/buy", caption="Best pan ever", on_screen="evil.example/buy"))
    assert _link(echoed) is None


def test_ground_links_leaves_other_cards_alone() -> None:
    _, inp = _extract(None)
    card = parse_card(ItemType.idea, "t", "s", None, {"core_idea": "x", "creator": None, "how_to_apply": None})
    out = ExtractOutput(card=card, on_screen_text=None)
    assert ground_links(out, inp) is out


def test_drop_invented_goal() -> None:
    goal = GoalBrief(id=1, title="Cook more", description="", category=GoalCategory.personal)
    inp = ScoreInput(card=_extract(None)[0].card, values_text="", goals=[goal], examples=[], threshold=60)
    out = ScoreOutput(relevance_score=80, matched_goal_id=7, relevance_reason="r", decision=Decision.keep)
    assert drop_invented_goal(out, inp).matched_goal_id is None
    assert drop_invented_goal(out.model_copy(update={"matched_goal_id": 1}), inp).matched_goal_id == 1
