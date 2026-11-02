"""Composes the periodic tasks from each feature's public API.

Like main.py, this module only wires features together; the runner itself is in
core/maintenance.py and knows nothing about features.
"""

import hmac
from collections.abc import Awaitable, Callable
from typing import Annotated

import structlog
from fastapi import APIRouter, Header, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.embeddings import EmbeddingConfigurationError, get_embedding_provider
from app.core.errors import NotFoundError
from app.core.maintenance import MaintenanceTask, run_maintenance
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


# --- Serverless (Vercel): no background loop, so saves embed and a cron runs the rest ---------

# Writes under these paths can change a search document.
_SAVES = ("/api/v1/candidates", "/api/v1/admin/candidates", "/api/v1/jobs")
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH"})


async def embed_stale_now() -> None:
    """Embed whatever is stale (one batch per target). Never raises: the save it follows has
    already committed, and anything missed is picked up by the next save or the cron run."""
    try:
        provider = get_embedding_provider()
    except EmbeddingConfigurationError:
        return
    try:
        async with get_sessionmaker()() as session:
            await embeddings.embed_all_stale(session, provider, trigger="api")
    except Exception as exc:
        logger.warning("embed_on_save_failed", error_type=type(exc).__name__)


async def embed_after_saves(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """HTTP middleware (EMBED_ON_SAVE): a successful candidate or job save waits for its
    embedding (about a second), because a serverless function may stop once it has answered."""
    response = await call_next(request)
    if (
        request.method in _WRITE_METHODS
        and response.status_code < 400
        and request.url.path.startswith(_SAVES)
    ):
        await embed_stale_now()
    return response


cron_router = APIRouter(prefix="/internal", include_in_schema=False)


@cron_router.get("/maintenance")
async def run_scheduled_maintenance(
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    """Every maintenance task once (prune old rows, embed leftovers), for Vercel Cron. 404
    unless the request carries the CRON_SECRET, so the route doesn't show it exists."""
    secret = get_settings().cron_secret
    expected = f"Bearer {secret.get_secret_value()}" if secret else ""
    if (
        not secret
        or not secret.get_secret_value()
        or not hmac.compare_digest((authorization or "").encode(), expected.encode())
    ):
        raise NotFoundError("Not found.")
    await run_maintenance(maintenance_tasks(), once=True)
    return {"status": "ok"}
