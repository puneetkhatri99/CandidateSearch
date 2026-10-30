import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_PAGE_SIZE = 100
MAX_LIMIT_USD = Decimal(10_000)

EventStatus = Literal["succeeded", "failed", "blocked"]


class UsageTotals(BaseModel):
    key: str
    requests: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal


class BudgetSummary(BaseModel):
    limit_usd: Decimal
    spent_usd: Decimal
    remaining_usd: Decimal
    percent_used: float
    # Spend has reached the limit, so every paid call is refused until an admin raises it.
    limit_reached: bool
    updated_at: datetime | None
    by_model: list[UsageTotals]
    by_operation: list[UsageTotals]


class UsageEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    provider: str
    model: str
    operation: str
    trigger: str
    item_count: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    status: EventStatus
    error: str | None


class UsageEventPage(BaseModel):
    items: list[UsageEventOut]
    next_cursor: str | None


class UsageEventParams(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    model: str | None = Field(default=None, max_length=100)
    operation: str | None = Field(default=None, max_length=50)
    status: EventStatus | None = None
    cursor: str | None = Field(default=None, max_length=500)
    limit: int = Field(default=50, ge=1, le=MAX_PAGE_SIZE)

    @field_validator("model", "operation", "cursor")
    @classmethod
    def _clean_text(cls, value: str | None) -> str | None:
        # Postgres rejects NUL in text parameters; without this the filter would be a 500.
        if value and "\x00" in value:
            raise ValueError("invalid characters")
        return value or None


class BudgetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit_usd: Annotated[Decimal, Field(ge=0, le=MAX_LIMIT_USD, max_digits=7, decimal_places=2)]
