"""Candidate intake schemas. These rules mirror the frontend zod schema; change both together."""

import re
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    EmailStr,
    Field,
    StrictBool,
    StrictInt,
    ValidationInfo,
    field_validator,
)

from app.shared.validation import (
    BlankToNone,
    Currency,
    StrictModel,
    YearlySalary,
    custom_error,
    normalize_country,
    reject_bool,
    salary_needs_currency,
    tag_list,
    text,
)

WorkMode = Literal["remote", "hybrid", "onsite"]

MIN_YEAR = 1950
MAX_URL_LENGTH = 300

_PHONE_RE = re.compile(r"^\+[1-9]\d{6,14}$")
_PHONE_SEPARATORS_RE = re.compile(r"[\s().-]")
_YEAR_MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_URL_UNSAFE_CHARS_RE = re.compile(r"[\\\s\x00-\x1f\x7f]")


def _current_month() -> date:
    today = datetime.now(UTC).date()
    return today.replace(day=1)


def _parse_year_month(value: object) -> object:
    if isinstance(value, str):
        match = _YEAR_MONTH_RE.match(value.strip())
        if not match:
            raise custom_error("year_month_format", "Use the format YYYY-MM.")
        return date(int(match[1]), int(match[2]), 1)
    return value


def _normalize_phone(value: str) -> str:
    phone = _PHONE_SEPARATORS_RE.sub("", value)
    if not _PHONE_RE.match(phone):
        raise custom_error("phone_format", "Use international format, e.g. +919876543210.")
    return phone


def _url_validator(
    *, host_suffix: str | None = None, path_prefix: str | None = None, https_only: bool = False
) -> AfterValidator:
    def validate(value: str) -> str:
        url = value if "://" in value else f"https://{value}"
        message = "Enter a valid https:// URL." if https_only else "Enter a valid URL."
        try:
            parts = urlsplit(url)
        except ValueError as exc:
            # e.g. NFKC-unsafe hosts; Python's message echoes the input, so replace it.
            raise custom_error("url_format", message) from exc
        allowed_schemes = {"https"} if https_only else {"http", "https"}
        host = (parts.hostname or "").lower()
        # Browsers read "\" as "/" and honour "user@host", so urlsplit's idea of the host can
        # differ from where a click actually goes. Reject anything that could disagree.
        ambiguous = _URL_UNSAFE_CHARS_RE.search(url) is not None or "@" in parts.netloc
        if parts.scheme not in allowed_schemes or "." not in host or ambiguous:
            raise custom_error("url_format", message)
        if host_suffix and host != host_suffix and not host.endswith(f".{host_suffix}"):
            raise custom_error("url_host", f"Must be a {host_suffix} URL.")
        if path_prefix and (
            not parts.path.startswith(path_prefix)
            or len(parts.path.rstrip("/")) <= len(path_prefix)
        ):
            raise custom_error("url_path", f"Must be a {host_suffix}{path_prefix}... profile URL.")
        if len(url) > MAX_URL_LENGTH:
            raise custom_error("url_length", f"Must be at most {MAX_URL_LENGTH} characters.")
        return url

    return AfterValidator(validate)


YearMonth = Annotated[date, BeforeValidator(_parse_year_month)]
OptionalText = Annotated[Annotated[str, text(1, 2000)] | None, BlankToNone]
LinkedInUrl = Annotated[
    Annotated[str, _url_validator(host_suffix="linkedin.com", path_prefix="/in/")] | None,
    BlankToNone,
]
GitHubUrl = Annotated[
    Annotated[str, _url_validator(host_suffix="github.com", path_prefix="/")] | None, BlankToNone
]
HttpsUrl = Annotated[Annotated[str, _url_validator(https_only=True)] | None, BlankToNone]
Phone = Annotated[Annotated[str, AfterValidator(_normalize_phone)] | None, BlankToNone]


class ExperienceIn(StrictModel):
    company: Annotated[str, text(1, 120)]
    title: Annotated[str, text(1, 120)]
    start_month: YearMonth
    is_current: StrictBool = False
    end_month: Annotated[YearMonth | None, BlankToNone] = Field(default=None, validate_default=True)
    description: OptionalText = None

    @field_validator("start_month")
    @classmethod
    def _start_not_in_future(cls, value: date) -> date:
        if value > _current_month():
            raise custom_error("date_in_future", "Start month cannot be in the future.")
        if value.year < MIN_YEAR:
            raise custom_error("date_too_early", f"Start month must be {MIN_YEAR} or later.")
        return value

    @field_validator("end_month")
    @classmethod
    def _end_matches_current_flag(cls, value: date | None, info: ValidationInfo) -> date | None:
        if info.data.get("is_current"):
            if value is not None:
                raise custom_error(
                    "end_for_current", "Leave the end month empty for a current role."
                )
            return None
        if value is None:
            raise custom_error(
                "end_required", "End month is required unless this is your current role."
            )
        start = info.data.get("start_month")
        if start is not None and value < start:
            raise custom_error("end_before_start", "End month cannot be before the start month.")
        if value > _current_month():
            raise custom_error("date_in_future", "End month cannot be in the future.")
        return value


class EducationIn(StrictModel):
    institution: Annotated[str, text(1, 200)]
    degree: Annotated[Annotated[str, text(1, 120)] | None, BlankToNone] = None
    field_of_study: Annotated[Annotated[str, text(1, 120)] | None, BlankToNone] = None
    start_year: StrictInt | None = Field(default=None, ge=MIN_YEAR)
    end_year: StrictInt | None = Field(default=None, ge=MIN_YEAR)

    @field_validator("start_year", "end_year")
    @classmethod
    def _year_not_too_far_ahead(cls, value: int | None) -> int | None:
        # Allows expected graduation dates for current students.
        if value is not None and value > datetime.now(UTC).year + 7:
            raise custom_error("year_too_late", "Year is too far in the future.")
        return value

    @field_validator("end_year")
    @classmethod
    def _end_after_start(cls, value: int | None, info: ValidationInfo) -> int | None:
        start = info.data.get("start_year")
        if value is not None and start is not None and value < start:
            raise custom_error("end_before_start", "End year cannot be before the start year.")
        return value


class CandidateProfile(StrictModel):
    """Every profile field and rule. Public intake, staff create and staff edit all extend this."""

    full_name: Annotated[str, text(2, 120)]
    email: EmailStr
    phone: Phone = None
    city: Annotated[str, text(1, 100)]
    country_code: Annotated[str, AfterValidator(normalize_country)]

    linkedin_url: LinkedInUrl = None
    github_url: GitHubUrl = None
    portfolio_url: HttpsUrl = None

    headline: Annotated[str, text(2, 120)]
    years_experience: Annotated[Decimal, BeforeValidator(reject_bool)] = Field(
        ge=0, le=50, max_digits=3, decimal_places=1
    )
    skills: Annotated[list[str], tag_list(min_items=1, max_items=50, max_length=50)]
    summary: Annotated[str, text(50, 3000)]

    experiences: list[ExperienceIn] = Field(default_factory=list, max_length=15)
    educations: list[EducationIn] = Field(default_factory=list, max_length=10)

    desired_roles: Annotated[list[str], tag_list(min_items=0, max_items=10, max_length=120)] = (
        Field(default_factory=list)
    )
    work_modes: list[WorkMode] = Field(min_length=1)
    open_to_relocation: StrictBool | None = None
    notice_period_days: StrictInt | None = Field(default=None, ge=0, le=180)
    # Yearly, in whole units of salary_currency (user decision 2026-10-30; Phase 1 left it out).
    expected_salary: YearlySalary | None = None
    salary_currency: Annotated[Currency | None, BlankToNone] = Field(
        default=None, validate_default=True
    )

    @field_validator("salary_currency")
    @classmethod
    def _currency_with_salary(cls, value: str | None, info: ValidationInfo) -> str | None:
        if "expected_salary" not in info.data:
            return value  # the amount itself failed; one error for one mistake
        return salary_needs_currency(info.data["expected_salary"] is not None, value)

    @field_validator("email")
    @classmethod
    def _lowercase_email(cls, value: str) -> str:
        if len(value) > 254:
            raise custom_error("email_length", "Email must be at most 254 characters.")
        return value.lower()

    @field_validator("work_modes")
    @classmethod
    def _dedupe_work_modes(cls, value: list[WorkMode]) -> list[WorkMode]:
        return list(dict.fromkeys(value))

    @field_validator("experiences")
    @classmethod
    def _single_current_role(cls, value: list[ExperienceIn]) -> list[ExperienceIn]:
        if sum(1 for e in value if e.is_current) > 1:
            raise custom_error("multiple_current", "Only one role can be marked as current.")
        return value


class CandidateCreate(CandidateProfile):
    """Public intake form submission."""

    consent: StrictBool
    # Honeypot: hidden in the UI, so only bots fill it in.
    website: str | None = Field(default=None, max_length=500)

    @field_validator("consent")
    @classmethod
    def _consent_given(cls, value: bool) -> bool:
        if not value:
            raise custom_error(
                "consent_required", "You must agree to the privacy notice to continue."
            )
        return value


class StaffCandidateCreate(CandidateProfile):
    """Candidate added by staff, who attest that the candidate agreed to the privacy notice."""

    consent_confirmed: StrictBool

    @field_validator("consent_confirmed")
    @classmethod
    def _consent_confirmed(cls, value: bool) -> bool:
        if not value:
            raise custom_error(
                "consent_required", "Confirm the candidate agreed to the privacy notice."
            )
        return value


class CandidateUpdate(CandidateProfile):
    """Full replacement of a profile. `version` is the one the editor loaded."""

    version: StrictInt = Field(ge=1)


class CandidateCreated(BaseModel):
    """Acknowledgement only. Never echo stored PII back to an unauthenticated caller."""

    id: UUID
    created_at: datetime


# --- Staff search / detail -------------------------------------------------------------

MAX_PAGE_SIZE = 100


class CandidateSearchParams(StrictModel):
    """The browse list: newest first, with the same hard filters as search by meaning."""

    country: Annotated[str, AfterValidator(normalize_country)] | None = None
    min_years: Decimal | None = Field(default=None, ge=0, le=50)
    # Comma-separated; a candidate must have every one.
    skill: str | None = Field(default=None, max_length=300)
    city: str | None = Field(default=None, max_length=100)
    source: str | None = Field(default=None, max_length=30)
    cursor: str | None = Field(default=None, max_length=500)
    limit: int = Field(default=25, ge=1, le=MAX_PAGE_SIZE)

    @field_validator("skill", "city", "source")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return value or None


class CandidateSummary(BaseModel):
    id: UUID
    full_name: str
    email: str
    headline: str
    city: str
    country_code: str
    years_experience: float
    top_skills: list[str]
    expected_salary: int | None
    salary_currency: str | None
    source: str
    created_at: datetime


class CandidatePage(BaseModel):
    items: list[CandidateSummary]
    next_cursor: str | None


class ExperienceOut(BaseModel):
    company: str
    title: str
    start_month: str  # "YYYY-MM", the format the form edits
    is_current: bool
    end_month: str | None
    description: str | None


class EducationOut(BaseModel):
    institution: str
    degree: str | None
    field_of_study: str | None
    start_year: int | None
    end_year: int | None


class CandidateDetail(BaseModel):
    id: UUID
    version: int
    full_name: str
    email: str
    phone: str | None
    city: str
    country_code: str
    linkedin_url: str | None
    github_url: str | None
    portfolio_url: str | None
    headline: str
    years_experience: float
    skills: list[str]
    summary: str
    experiences: list[ExperienceOut]
    educations: list[EducationOut]
    desired_roles: list[str]
    work_modes: list[str]
    open_to_relocation: bool | None
    notice_period_days: int | None
    expected_salary: int | None
    salary_currency: str | None
    source: str
    consent_given_at: datetime
    consent_version: str
    created_at: datetime
    updated_at: datetime
