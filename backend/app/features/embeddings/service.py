"""Embedding business logic.

The whole flow: a save changes a search document → `embed_stale` (run every few seconds by the
maintenance runner) finds documents whose hash differs from their stored embedding → embeds
them in batches through `ai_usage.metered_call` → stores the vectors. Failures go to the
dead-letter table, which also paces retries.
"""

import hashlib
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import structlog
from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai_pricing import UnknownModelPriceError
from app.core.config import get_settings
from app.core.embeddings import (
    MAX_INPUT_CHARACTERS,
    EmbeddingBatch,
    OpenAIEmbeddingProvider,
    PermanentEmbeddingError,
    TransientEmbeddingError,
)
from app.core.errors import describe_error
from app.features import ai_usage
from app.features.ai_usage import BudgetExceededError
from app.features.embeddings import repository
from app.features.embeddings.repository import EmbeddingRow
from app.features.embeddings.targets import JOBS, TARGETS, EmbeddingTarget

logger = structlog.get_logger(__name__)

type JobEmbeddingStatus = Literal["ready", "pending", "failed", "budget_blocked"]


@dataclass
class EmbedOutcome:
    embedded: int = 0
    failed: int = 0
    # Refused by the AI budget (or a missing model price); the rest of the run is not sent.
    blocked: int = 0


@dataclass(frozen=True)
class _Pending:
    entity_id: uuid.UUID
    text: str
    content_hash: str


def hash_document(document: str) -> str:
    return hashlib.sha256(document.encode("utf-8")).hexdigest()


async def _record_failures(
    session: AsyncSession,
    model: str,
    target: EmbeddingTarget,
    batch: Sequence[_Pending],
    error: str,
) -> None:
    async with session.begin():
        for item in batch:
            await repository.record_failure(
                session,
                entity_id=item.entity_id,
                model=model,
                content_hash=item.content_hash,
                error=error,
                target=target,
            )


async def _embed_batch(
    session: AsyncSession,
    provider: OpenAIEmbeddingProvider,
    target: EmbeddingTarget,
    batch: Sequence[_Pending],
    outcome: EmbedOutcome,
    trigger: str,
) -> None:
    model = provider.model_name
    for item in batch:
        if len(item.text) > MAX_INPUT_CHARACTERS:
            logger.warning(
                "embedding_input_truncated", target=target.name, entity_id=str(item.entity_id)
            )
    try:
        result = await ai_usage.metered_call(
            session,
            provider=provider.provider_name,
            model=model,
            operation=target.operation,
            trigger=trigger,
            item_count=len(batch),
            call=lambda: provider.embed_documents([item.text for item in batch]),
            tokens_of=EmbeddingBatch.billed_tokens,
        )
    except (BudgetExceededError, UnknownModelPriceError) as exc:
        reason = (
            repository.BUDGET_EXCEEDED_ERROR
            if isinstance(exc, BudgetExceededError)
            else repository.PRICE_UNKNOWN_ERROR
        )
        await _record_failures(session, model, target, batch, reason)
        outcome.blocked += len(batch)
        logger.warning("embedding_blocked", target=target.name, reason=reason)
        return
    except PermanentEmbeddingError as exc:
        if len(batch) > 1:
            # One bad input must not dead-letter its neighbours: retry them one by one.
            for index, item in enumerate(batch):
                if outcome.blocked:
                    # The budget refused mid-way: don't ask again for every remaining item.
                    rest = batch[index:]
                    await _record_failures(
                        session, model, target, rest, repository.BUDGET_EXCEEDED_ERROR
                    )
                    outcome.blocked += len(rest)
                    return
                await _embed_batch(session, provider, target, [item], outcome, trigger)
            return
        await _record_failures(session, model, target, batch, describe_error(exc))
        outcome.failed += 1
        logger.warning("embedding_failed", target=target.name, permanent=True)
        return
    except TransientEmbeddingError as exc:
        # The failure row makes the scan retry these later (see repository.find_stale_ids).
        await _record_failures(session, model, target, batch, describe_error(exc))
        outcome.failed += len(batch)
        logger.warning("embedding_failed", target=target.name, batch_size=len(batch))
        return

    rows = [
        EmbeddingRow(item.entity_id, item.content_hash, vector)
        for item, vector in zip(batch, result.vectors, strict=True)
    ]
    async with session.begin():
        await repository.upsert_embeddings(session, model, rows, target=target)
        await repository.clear_failures(
            session, model, [item.entity_id for item in batch], target=target
        )
    outcome.embedded += len(batch)


async def embed_stale(
    session: AsyncSession,
    provider: OpenAIEmbeddingProvider,
    target: EmbeddingTarget,
    *,
    trigger: str = "worker",
) -> EmbedOutcome:
    """Embed one batch of entities whose document changed since their last embedding.

    Provider failures never raise: they are dead-lettered and counted, so one bad document
    cannot stop the rest. Nothing is sent while the AI budget is used up. `session` must not
    already be in a transaction.
    """
    outcome = EmbedOutcome()
    if not await ai_usage.has_budget(session):
        return outcome
    async with session.begin():
        ids = await repository.find_stale_ids(
            session, provider.model_name, get_settings().embedding_batch_size, target=target
        )
        documents = await repository.load_documents(session, ids, target=target)
    if not documents:
        return outcome

    started = time.monotonic()
    pending = [_Pending(i, text, hash_document(text)) for i, text in documents.items()]
    await _embed_batch(session, provider, target, pending, outcome, trigger)
    # Tokens and cost are logged once, exactly, by ai_usage.metered_call.
    logger.info(
        "embedding_run_completed",
        target=target.name,
        embedded=outcome.embedded,
        failed=outcome.failed,
        blocked=outcome.blocked,
        duration_ms=round((time.monotonic() - started) * 1000),
    )
    return outcome


async def embed_all_stale(
    session: AsyncSession, provider: OpenAIEmbeddingProvider, *, trigger: str = "worker"
) -> int:
    """One pass over jobs, then candidates. Returns how many were embedded."""
    embedded = 0
    for target in TARGETS:
        embedded += (await embed_stale(session, provider, target, trigger=trigger)).embedded
    return embedded


async def nearest_candidates_to_vector(
    session: AsyncSession,
    vector: list[float],
    model: str,
    *,
    count: int,
    within: Select[uuid.UUID] | None = None,
) -> list[tuple[uuid.UUID, float]]:
    """Candidate ids nearest to `vector` (cosine similarity), best first, from the HNSW index;
    only among the ids `within` selects, when given."""
    async with session.begin():
        return await repository.nearest_neighbours(session, vector, model, count, within)


async def load_job_vector(
    session: AsyncSession, job_id: uuid.UUID, model: str
) -> list[float] | None:
    """The job's embedding, or None while it is missing or older than the job's text."""
    async with session.begin():
        return await repository.load_current_vector(session, job_id, model, target=JOBS)


async def get_job_embedding_status(
    session: AsyncSession, job_id: uuid.UUID, model: str
) -> JobEmbeddingStatus:
    """Where a job's embedding stands. Runs in the caller's transaction."""
    current_hash = await repository.load_current_hash(session, job_id, target=JOBS)
    stored_hash = await repository.load_embedding_hash(session, job_id, model, target=JOBS)
    if current_hash is not None and stored_hash == current_hash:
        return "ready"
    failure = await repository.load_failure(session, job_id, model, target=JOBS)
    if failure is not None and failure.content_hash == current_hash:
        gave_up = failure.attempts >= repository.MAX_TRANSIENT_ATTEMPTS
        if gave_up or repository.is_permanent_failure(failure.last_error):
            return "failed"
    # Nothing is embedded while the budget is used up, so the job waits for an admin.
    return "budget_blocked" if await ai_usage.budget_used_up(session) else "pending"
