from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class HealthStatus(BaseModel):
    status: Literal["ok", "unavailable"]
    checks: dict[str, bool] = {}


class AiModels(BaseModel):
    embedding_model: str
    ranking_model: str
    ranking_prompt_version: str
    understanding_prompt_version: str


class EmbeddingHealth(BaseModel):
    total: int
    current: int
    failed: int


class BudgetHealth(BaseModel):
    spent_usd: Decimal
    limit_usd: Decimal
    limit_reached: bool


class SystemDetails(BaseModel):
    """For the staff System page: model names, counts and money only, never candidate data."""

    models: AiModels
    candidates: EmbeddingHealth
    jobs: EmbeddingHealth
    budget: BudgetHealth
