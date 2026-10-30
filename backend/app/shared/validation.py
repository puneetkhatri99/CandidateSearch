"""Validation building blocks shared by features (candidates, jobs).

Rules here mirror the frontend zod helpers; change both together.
"""

from typing import Annotated

import pycountry
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)
from pydantic_core import PydanticCustomError

COUNTRY_CODES = frozenset(country.alpha_2 for country in pycountry.countries)


def custom_error(code: str, message: str) -> PydanticCustomError:
    # Custom errors keep messages user-readable (no "Value error, ..." prefix).
    return PydanticCustomError(code, message)


def _blank_to_none(value: object) -> object:
    if isinstance(value, str) and not value.strip():
        return None
    return value


BlankToNone = BeforeValidator(_blank_to_none)


def normalize_tag(value: str) -> str:
    return " ".join(value.split()).lower()


def split_tags(value: str | None) -> list[str]:
    """A comma-separated filter ("Python, FastAPI") as stored tags: ["python", "fastapi"]."""
    return [tag for tag in (normalize_tag(part) for part in (value or "").split(",")) if tag]


def tag_list(min_items: int, max_items: int, max_length: int) -> AfterValidator:
    """Trim, lower-case and de-duplicate tags, then enforce counts on the cleaned list."""

    def validate(values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for raw in values:
            tag = normalize_tag(raw)
            if not tag or tag in cleaned:
                continue
            if "," in tag:
                # Filters are comma-separated lists, so "react, redux" would read as two tags.
                raise custom_error("tag_comma", "Add each entry separately, without commas.")
            if len(tag) > max_length:
                raise custom_error(
                    "tag_too_long", f"Each entry must be at most {max_length} characters."
                )
            cleaned.append(tag)
        if len(cleaned) < min_items:
            raise custom_error("too_few_items", f"Add at least {min_items}.")
        if len(cleaned) > max_items:
            raise custom_error("too_many_items", f"Add at most {max_items}.")
        return cleaned

    return AfterValidator(validate)


def normalize_country(value: str) -> str:
    code = value.strip().upper()
    if code not in COUNTRY_CODES:
        raise custom_error("country_code", "Select a valid country.")
    return code


def text(min_length: int, max_length: int) -> StringConstraints:
    return StringConstraints(strip_whitespace=True, min_length=min_length, max_length=max_length)


def reject_bool(value: object) -> object:
    # Pydantic's lax mode turns true/false into 1/0; a boolean here is always a client bug.
    if isinstance(value, bool):
        raise custom_error("number_type", "Enter a number.")
    return value


def _contains_nul(value: object) -> bool:
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, list):
        return any(_contains_nul(item) for item in value)
    return False


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("*", mode="before")
    @classmethod
    def _reject_nul_characters(cls, value: object) -> object:
        # PostgreSQL text can't store NUL; without this the insert fails with a 500.
        if _contains_nul(value):
            raise custom_error("invalid_characters", "Remove invalid characters.")
        return value


Country = Annotated[str, AfterValidator(normalize_country)]

# The currencies the forms offer; mirrors CURRENCIES in frontend/src/shared/forms/salary.ts.
# Accepting more here would store values the edit forms can't show or save.
CURRENCY_CODES = ("INR", "USD", "EUR", "GBP", "AED", "SGD", "CAD", "AUD")
MAX_SALARY = 1_000_000_000  # a yearly amount; fits a Postgres integer even in INR or JPY


def normalize_currency(value: str) -> str:
    code = value.strip().upper()
    if code not in CURRENCY_CODES:
        raise custom_error("currency_code", "Select a valid currency.")
    return code


Currency = Annotated[str, AfterValidator(normalize_currency)]
# Whole units per year; booleans are rejected like other numbers.
YearlySalary = Annotated[int, BeforeValidator(reject_bool), Field(strict=True, ge=1, le=MAX_SALARY)]


def salary_needs_currency(has_amount: bool, currency: str | None) -> str | None:
    """A salary and its currency are given together or not at all."""
    if has_amount and currency is None:
        raise custom_error("currency_required", "Select the currency.")
    if not has_amount and currency is not None:
        raise custom_error("salary_required", "Enter the salary, or clear the currency.")
    return currency
