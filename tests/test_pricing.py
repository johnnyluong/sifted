from __future__ import annotations

import pytest

from sift.config import Settings
from sift.llm import pricing


def _settings(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # pyright: ignore[reportCallIssue]


def test_a_post_costs_extract_and_score_on_sonnet_plus_an_outline_on_haiku() -> None:
    cost = pricing.item_cost(_settings(llm_backend="anthropic"))
    assert cost.usd == pytest.approx(0.0238 + 0.00083)
    assert cost.tokens == 8_300 + 400 + 1_100 + 100 + 4_800 + 700


def test_scoring_on_haiku_is_priced_per_model() -> None:
    cost = pricing.item_cost(_settings(llm_backend="anthropic", score_model="claude-haiku-5-5"))
    assert cost.usd == pytest.approx(0.0206 + 0.00016 + 0.00083)


def test_an_unknown_model_shows_no_dollar_figure() -> None:
    assert pricing.item_cost(_settings(llm_backend="anthropic", extract_model="claude-future-9")).usd is None


def test_the_fake_backend_costs_nothing() -> None:
    assert pricing.item_cost(_settings(llm_backend="fake")).usd == 0.0
