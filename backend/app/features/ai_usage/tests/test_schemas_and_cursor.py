from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.errors import describe_error
from app.features.ai_usage.schemas import BudgetUpdate, UsageEventParams


@pytest.mark.parametrize("value", ["0", "5.00", "10000", "0.01"])
def test_budget_update_accepts_valid_limits(value: str) -> None:
    assert BudgetUpdate.model_validate({"limit_usd": value}).limit_usd == Decimal(value)


@pytest.mark.parametrize("value", ["-0.01", "10000.01", "1.234", "NaN", "Infinity", "abc"])
def test_budget_update_rejects_invalid_limits(value: str) -> None:
    with pytest.raises(ValidationError):
        BudgetUpdate.model_validate({"limit_usd": value})


def test_budget_update_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        BudgetUpdate.model_validate({"limit_usd": "5", "role": "admin"})


def test_event_params_reject_nul_and_oversized_page() -> None:
    with pytest.raises(ValidationError):
        UsageEventParams(model="a\x00b")
    with pytest.raises(ValidationError):
        UsageEventParams(limit=101)


def test_event_params_blank_filter_means_no_filter() -> None:
    assert UsageEventParams(model="  ").model is None


def test_error_description_has_class_and_status_only() -> None:
    class ProviderError(Exception):
        status_code = 503

    assert describe_error(ProviderError("secret text")) == "ProviderError status=503"
    assert describe_error(ValueError("secret text")) == "ValueError"
