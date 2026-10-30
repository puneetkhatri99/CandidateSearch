from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from app.features.candidates import CandidateSummary
from app.shared.validation import normalize_country

MAX_QUERY_LENGTH = 500
MAX_RESULTS = 20  # the service ranks only the 20 best hybrid-search hits

FilterName = Literal["min_years", "skill", "city", "country", "source"]


def _clean(value: object) -> object:
    if isinstance(value, str):
        if "\x00" in value:
            raise ValueError("must not contain NUL characters")
        return " ".join(value.split())
    return value


class HardFilters(BaseModel):
    """Applied after the AI ranking; the same names as the candidate list filters."""

    model_config = ConfigDict(extra="forbid")

    min_years: Decimal | None = Field(default=None, ge=0, le=50)
    # Comma-separated, all required. Long enough for a job's 20 must-have skills of 50 characters.
    skill: str | None = Field(default=None, max_length=1100)
    city: str | None = Field(default=None, max_length=100)
    country: Annotated[str, AfterValidator(normalize_country)] | None = None
    source: str | None = Field(default=None, max_length=30)

    @field_validator("skill", "city", "source", mode="before")
    @classmethod
    def _clean_text(cls, value: object) -> object:
        return _clean(value)


class SemanticSearchParams(HardFilters):
    q: str = Field(min_length=2, max_length=MAX_QUERY_LENGTH)
    limit: int = Field(default=20, ge=1, le=MAX_RESULTS)

    @field_validator("q", mode="before")
    @classmethod
    def _clean_query(cls, value: object) -> object:
        return _clean(value)


Fit = Literal["strong", "partial", "weak"]


class Criterion(BaseModel):
    """One reason from the AI ranking a recruiter can read."""

    name: Literal["skills", "location", "experience", "salary"]
    status: Literal["met", "partial", "missed"]
    note: str


class SemanticMatch(BaseModel):
    candidate: CandidateSummary
    # None, with no criteria, when the AI ranking was unavailable.
    fit: Fit | None
    criteria: list[Criterion]
    # The hard filters this candidate fails; empty for everyone in `items`.
    failed_filters: list[FilterName] = []


Stage = Literal["embedding", "retrieval", "augmentation", "ranking", "filtering"]


class StageEvent(BaseModel):
    """One step of a search, streamed so the UI can show what is happening. Never carries the
    query text or anything about a candidate beyond counts."""

    stage: Stage
    state: Literal["started", "done"]
    detail: str | None = None
    elapsed_ms: int | None = None  # set on "done"


class SemanticSearchResult(BaseModel):
    # Best first. `items` pass every hard filter; `filtered_out` are the other hybrid-search
    # hits, in the same order, so a strong candidate a filter removed is still visible.
    items: list[SemanticMatch]
    filtered_out: list[SemanticMatch]
    # "ai": ranked by the LLM; "search": the LLM was unavailable, so hybrid-search order.
    ranked_by: Literal["ai", "search"]
    # Models and prompt version behind this answer (RULES §8).
    embedding_model: str
    ranking_model: str | None
    prompt_version: str | None
