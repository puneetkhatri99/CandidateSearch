"""Job role schemas. These rules mirror the frontend zod schema; change both together."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, Field, StrictInt, ValidationInfo, field_validator

from app.shared.validation import (
    BlankToNone,
    Country,
    Currency,
    StrictModel,
    YearlySalary,
    custom_error,
    reject_bool,
    salary_needs_currency,
    tag_list,
    text,
)

WorkMode = Literal["remote", "hybrid", "onsite"]
EmploymentType = Literal["full_time", "part_time", "contract", "internship"]
JobStatus = Literal["draft", "open", "closed"]
EmbeddingStatus = Literal["ready", "pending", "failed", "budget_blocked"]

MAX_PAGE_SIZE = 100
MAX_YEARS = 50
SKILL_MAX_LENGTH = 50
MAX_SKILLS = 20

Years = Annotated[
    Decimal, BeforeValidator(reject_bool), Field(ge=0, le=MAX_YEARS, max_digits=3, decimal_places=1)
]
OptionalYears = Annotated[
    Annotated[
        Decimal,
        BeforeValidator(reject_bool),
        Field(ge=0, le=MAX_YEARS, max_digits=3, decimal_places=1),
    ]
    | None,
    BeforeValidator(reject_bool),
]


class JobFields(StrictModel):
    """Every job field and rule. Create validates it directly; edit validates the merged result."""

    title: Annotated[str, text(1, 120)]
    department: Annotated[Annotated[str, text(1, 120)] | None, BlankToNone] = None
    work_mode: WorkMode
    employment_type: EmploymentType
    city: Annotated[Annotated[str, text(1, 100)] | None, BlankToNone] = Field(
        default=None, validate_default=True
    )
    country_code: Annotated[Country | None, BlankToNone] = Field(
        default=None, validate_default=True
    )
    min_years: Years
    max_years: OptionalYears = Field(default=None, validate_default=True)
    must_have_skills: Annotated[
        list[str], tag_list(min_items=1, max_items=MAX_SKILLS, max_length=SKILL_MAX_LENGTH)
    ]
    nice_to_have_skills: Annotated[
        list[str], tag_list(min_items=0, max_items=MAX_SKILLS, max_length=SKILL_MAX_LENGTH)
    ] = Field(default_factory=list)
    description: Annotated[str, text(100, 10_000)]
    status: JobStatus
    # Yearly pay range in whole units of salary_currency; either end may be left open.
    salary_min: YearlySalary | None = None
    salary_max: YearlySalary | None = Field(default=None, validate_default=True)
    salary_currency: Annotated[Currency | None, BlankToNone] = Field(
        default=None, validate_default=True
    )

    @field_validator("salary_max")
    @classmethod
    def _salary_max_not_below_min(cls, value: int | None, info: ValidationInfo) -> int | None:
        minimum = info.data.get("salary_min")
        if value is not None and minimum is not None and value < minimum:
            raise custom_error("max_below_min", "Maximum pay cannot be less than the minimum.")
        return value

    @field_validator("salary_currency")
    @classmethod
    def _currency_with_salary(cls, value: str | None, info: ValidationInfo) -> str | None:
        if "salary_min" not in info.data or "salary_max" not in info.data:
            return value  # an amount itself failed; one error for one mistake
        has_amount = info.data["salary_min"] is not None or info.data["salary_max"] is not None
        return salary_needs_currency(has_amount, value)

    @field_validator("city")
    @classmethod
    def _city_required_on_site(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None and info.data.get("work_mode") in ("hybrid", "onsite"):
            raise custom_error("city_required", "Enter the city for a hybrid or onsite role.")
        return value

    @field_validator("country_code")
    @classmethod
    def _country_required_with_location(cls, value: str | None, info: ValidationInfo) -> str | None:
        located = info.data.get("city") is not None or info.data.get("work_mode") in (
            "hybrid",
            "onsite",
        )
        if value is None and located:
            raise custom_error("country_required", "Select the country.")
        return value

    @field_validator("max_years")
    @classmethod
    def _max_not_below_min(cls, value: Decimal | None, info: ValidationInfo) -> Decimal | None:
        minimum = info.data.get("min_years")
        if value is not None and minimum is not None and value < minimum:
            raise custom_error("max_below_min", "Maximum years cannot be less than the minimum.")
        return value

    @field_validator("nice_to_have_skills")
    @classmethod
    def _not_also_required(cls, value: list[str], info: ValidationInfo) -> list[str]:
        required = set(info.data.get("must_have_skills") or [])
        if any(skill in required for skill in value):
            raise custom_error("skill_in_both", "A skill can't be both must-have and nice-to-have.")
        return value


class JobCreate(JobFields):
    """A new job role."""


class JobPatch(StrictModel):
    """Any subset of the job fields plus the version the editor loaded.

    Values are only loosely typed here; the merged result is validated with `JobFields`, so
    one set of rules covers create and edit. An explicit null clears an optional field.
    """

    version: StrictInt = Field(ge=1)
    title: str | None = None
    department: str | None = None
    work_mode: str | None = None
    employment_type: str | None = None
    city: str | None = None
    country_code: str | None = None
    min_years: Annotated[Decimal | None, BeforeValidator(reject_bool)] = None
    max_years: Annotated[Decimal | None, BeforeValidator(reject_bool)] = None
    must_have_skills: list[str] | None = None
    nice_to_have_skills: list[str] | None = None
    description: str | None = None
    status: str | None = None
    # Strict like JobFields: lax parsing here would accept "100" on edit but not on create.
    salary_min: YearlySalary | None = None
    salary_max: YearlySalary | None = None
    salary_currency: str | None = None


class JobListParams(StrictModel):
    status: JobStatus | None = None
    cursor: str | None = Field(default=None, max_length=500)
    limit: int = Field(default=25, ge=1, le=MAX_PAGE_SIZE)

    @field_validator("cursor")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return value or None


class JobOwner(BaseModel):
    id: UUID
    full_name: str


class JobSummary(BaseModel):
    id: UUID
    title: str
    department: str | None
    status: JobStatus
    work_mode: WorkMode
    employment_type: EmploymentType
    city: str | None
    country_code: str | None
    min_years: float
    max_years: float | None
    must_have_skills: list[str]
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    created_by: JobOwner
    created_at: datetime
    updated_at: datetime


class JobDetail(JobSummary):
    nice_to_have_skills: list[str]
    description: str
    version: int
    can_edit: bool
    embedding_status: EmbeddingStatus


class JobPage(BaseModel):
    items: list[JobSummary]
    next_cursor: str | None
