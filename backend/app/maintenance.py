"""Composes the periodic tasks from each feature's public API.

Like main.py, this module only wires features together; the runner itself is in
core/maintenance.py and knows nothing about features.
"""

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.embeddings import EmbeddingConfigurationError, get_embedding_provider
from app.core.maintenance import MaintenanceTask
from app.core.rate_limit import prune_rate_limit_hits
from app.features import auth, embeddings

logger = structlog.get_logger(__name__)


def maintenance_tasks() -> list[MaintenanceTask]:
    tasks = [
        MaintenanceTask("core.prune_rate_limit_hits", 600, prune_rate_limit_hits),
        MaintenanceTask("auth.prune_expired_sessions", 3600, auth.prune_expired_sessions),
    ]
    try:
        provider = get_embedding_provider()
    except EmbeddingConfigurationError:
        # Saves keep working; their documents are embedded once a key is set and the app restarts.
        logger.warning("embedding_disabled", reason="no usable OPENAI_API_KEY")
        return tasks

    async def embed(session: AsyncSession) -> int:
        return await embeddings.embed_all_stale(session, provider)

    poll_seconds = get_settings().embedding_poll_seconds
    return [MaintenanceTask("embeddings.embed_stale", poll_seconds, embed), *tasks]
