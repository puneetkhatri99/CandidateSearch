from decimal import Decimal

import pytest

from app.core.ai_pricing import UnknownModelPriceError, compute_cost_usd


def test_cost_uses_the_per_million_price() -> None:
    assert compute_cost_usd("text-embedding-3-small", 1_000_000) == Decimal("0.020000")
    assert compute_cost_usd("text-embedding-3-large", 1_000_000) == Decimal("0.130000")


def test_cost_rounds_up_never_down() -> None:
    # 1 token of the small model is 0.00000002 USD; stored precision is 6 places.
    assert compute_cost_usd("text-embedding-3-small", 1) == Decimal("0.000001")


def test_zero_tokens_cost_nothing() -> None:
    assert compute_cost_usd("text-embedding-3-small", 0) == Decimal("0.000000")


def test_embedding_models_have_no_output_price() -> None:
    assert compute_cost_usd("text-embedding-3-small", 0, output_tokens=5_000_000) == Decimal(0)


def test_unknown_model_fails_closed() -> None:
    with pytest.raises(UnknownModelPriceError) as raised:
        compute_cost_usd("mystery-model", 10)
    assert raised.value.model == "mystery-model"
