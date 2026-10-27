from __future__ import annotations

from dataclasses import dataclass

from sift.config import Settings

PRICE_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-opus-5-5": (4.00, 20.00),
    "fake": (0.0, 0.0),
}


@dataclass(frozen=True, slots=True)
class CallBudget:
    name: str
    model: str
    input_tokens: int
    output_tokens: int

    @property
    def usd(self) -> float | None:
        price = PRICE_PER_MTOK.get(self.model)
        if price is None:
            return None
        return (self.input_tokens * price[0] + self.output_tokens * price[1]) / 1_000_000


@dataclass(frozen=True, slots=True)
class ItemCost:
    calls: tuple[CallBudget, ...]

    @property
    def tokens(self) -> int:
        return sum(c.input_tokens + c.output_tokens for c in self.calls)

    @property
    def usd(self) -> float | None:
        costs = [c.usd for c in self.calls]
        return None if any(c is None for c in costs) else sum(c for c in costs if c is not None)


# Average tokens per call, measured from sift.log on the first real items (Sonnet 5.5).
EXTRACT_TOKENS = (8_300, 400)
SCORE_TOKENS = (1_100, 100)
OUTLINE_TOKENS_ESTIMATE = (4_800, 700)


def item_cost(settings: Settings) -> ItemCost:
    fake = settings.llm_backend == "fake"
    return ItemCost(
        (
            CallBudget("extract", "fake" if fake else settings.extract_model, *EXTRACT_TOKENS),
            CallBudget("score", "fake" if fake else settings.effective_score_model, *SCORE_TOKENS),
            CallBudget("outline", "fake" if fake else settings.outline_model, *OUTLINE_TOKENS_ESTIMATE),
        )
    )
