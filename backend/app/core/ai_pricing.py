"""Per-model prices for paid AI calls. Unknown models fail closed so the budget cap holds.

Exact decimal math throughout: prices are tiny and a float sum would drift.
"""

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

_MILLION = Decimal(1_000_000)
_COST_PRECISION = Decimal("0.000001")  # matches numeric(12,6) in ai_usage_events


@dataclass(frozen=True)
class ModelPrice:
    """USD per one million tokens."""

    input_per_million: Decimal
    output_per_million: Decimal = Decimal(0)


MODEL_PRICES: dict[str, ModelPrice] = {
    "text-embedding-3-small": ModelPrice(Decimal("0.02")),
    "text-embedding-3-large": ModelPrice(Decimal("0.13")),
    # Checked on OpenAI's model page 2026-10-30.
    "gpt-5.4-mini": ModelPrice(Decimal("0.75"), Decimal("4.50")),
}


class UnknownModelPriceError(Exception):
    """No price is known for the model, so its cost cannot be capped."""

    def __init__(self, model: str) -> None:
        super().__init__(f"No price is configured for model {model!r}.")
        self.model = model


def get_model_price(model: str) -> ModelPrice:
    try:
        return MODEL_PRICES[model]
    except KeyError:
        raise UnknownModelPriceError(model) from None


def compute_cost_usd(model: str, input_tokens: int, output_tokens: int = 0) -> Decimal:
    """Cost in USD, rounded up to the stored precision so we never undercount."""
    price = get_model_price(model)
    cost = (
        Decimal(input_tokens) * price.input_per_million
        + Decimal(output_tokens) * price.output_per_million
    ) / _MILLION
    return cost.quantize(_COST_PRECISION, rounding=ROUND_CEILING)
