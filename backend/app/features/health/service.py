import structlog
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.features import ai_usage, embeddings, semantic_search
from app.features.health import repository
from app.features.health.schemas import (
    AiModels,
    BudgetHealth,
    EmbeddingHealth,
    HealthStatus,
    SystemDetails,
)

logger = structlog.get_logger(__name__)


async def _check_database(session: AsyncSession) -> bool:
    try:
        await repository.ping_database(session)
    except (SQLAlchemyError, OSError) as exc:
        # OSError covers refused connections and DNS failures raised by the driver.
        logger.warning("database_unreachable", error_type=type(exc).__name__)
        return False
    return True


async def _check_pgvector(session: AsyncSession) -> bool:
    try:
        return await repository.pgvector_installed(session)
    except (SQLAlchemyError, OSError) as exc:
        logger.warning("pgvector_check_failed", error_type=type(exc).__name__)
        return False


async def check_readiness(session: AsyncSession) -> HealthStatus:
    database_ok = await _check_database(session)
    pgvector_ok = database_ok and await _check_pgvector(session)
    return HealthStatus(
        status="ok" if database_ok and pgvector_ok else "unavailable",
        checks={"database": database_ok, "pgvector": pgvector_ok},
    )


async def get_system_details(session: AsyncSession) -> SystemDetails:
    model = get_settings().embedding_model
    counts = await embeddings.get_embedding_counts(session, model)
    budget = await ai_usage.get_summary(session)
    return SystemDetails(
        models=AiModels(
            embedding_model=model,
            ranking_model=semantic_search.RANK_MODEL,
            ranking_prompt_version=semantic_search.RANKING_PROMPT_VERSION,
            understanding_prompt_version=semantic_search.UNDERSTANDING_PROMPT_VERSION,
        ),
        candidates=EmbeddingHealth(**vars(counts["candidate"])),
        jobs=EmbeddingHealth(**vars(counts["job"])),
        budget=BudgetHealth(
            spent_usd=budget.spent_usd,
            limit_usd=budget.limit_usd,
            limit_reached=budget.limit_reached,
        ),
    )
