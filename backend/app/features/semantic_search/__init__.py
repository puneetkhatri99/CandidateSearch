"""Search candidates by meaning: the query is embedded and matched against candidate embeddings."""

from app.features.semantic_search.evaluation import (
    EvalReport,
    GoldenCase,
    GoldenSet,
    new_case,
    report_markdown,
    run_eval,
)
from app.features.semantic_search.ranking import PROMPT_VERSION as RANKING_PROMPT_VERSION
from app.features.semantic_search.ranking import RANK_MODEL
from app.features.semantic_search.router import router
from app.features.semantic_search.understanding import (
    PROMPT_VERSION as UNDERSTANDING_PROMPT_VERSION,
)

__all__ = [
    "RANKING_PROMPT_VERSION",
    "RANK_MODEL",
    "UNDERSTANDING_PROMPT_VERSION",
    "EvalReport",
    "GoldenCase",
    "GoldenSet",
    "new_case",
    "report_markdown",
    "router",
    "run_eval",
]
