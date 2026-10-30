"""All database access for embeddings.

Every embedding/failure function takes an `EmbeddingTarget` (candidates or jobs) and runs the
same SQL against that target's tables.

Deliberate boundary exception (see LEARNINGS.md): `candidates` and `jobs` are read, never
written, through Core table references instead of importing those features' models. They
expose only what embeddings needs: the id and the redacted search document. Never add
personal-data columns here.
"""

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import (
    Float,
    Select,
    Text,
    and_,
    bindparam,
    case,
    cast,
    delete,
    func,
    literal,
    not_,
    or_,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.vector import Vector
from app.features.embeddings.models import EMBEDDING_DIMENSIONS, CandidateEmbedding
from app.features.embeddings.targets import EmbeddingTarget

# Stored in the failure table's last_error for work the AI budget refused. Unlike other
# failures, these are retried with the same text once the budget has room again.
BUDGET_EXCEEDED_ERROR = "budget_exceeded"
PRICE_UNKNOWN_ERROR = "model_price_unknown"
# describe_error() renders our permanent provider errors as "PermanentEmbeddingError[ status=N]".
_PERMANENT_ERROR_PREFIX = "PermanentEmbeddingError"
# A temporary failure (rate limit, timeout, 5xx) is retried after 30 s, 2 min, 8 min, 32 min,
# then given up until the text changes.
RETRY_BASE_SECONDS = 30
RETRY_GROWTH = 4
MAX_TRANSIENT_ATTEMPTS = 5


@dataclass(frozen=True)
class EmbeddingRow:
    entity_id: uuid.UUID
    content_hash: str
    vector: list[float]


@dataclass(frozen=True)
class KnownFailure:
    content_hash: str
    last_error: str
    attempts: int


def is_permanent_failure(last_error: str) -> bool:
    """Whether a dead-letter row records an error that retrying the same text cannot fix."""
    return last_error.startswith(_PERMANENT_ERROR_PREFIX) or last_error == PRICE_UNKNOWN_ERROR


def _document_hash(target: EmbeddingTarget) -> ColumnElement[str]:
    # Must equal hashlib.sha256(document.encode("utf-8")).hexdigest() in Python.
    return func.encode(func.sha256(func.convert_to(target.source.c.search_document, "UTF8")), "hex")


def _entity(target: EmbeddingTarget, table_name: str) -> ColumnElement[uuid.UUID]:
    table = target.embeddings if table_name == "embeddings" else target.failures
    return table.c[target.entity_column]


async def load_documents(
    session: AsyncSession, ids: Sequence[uuid.UUID], *, target: EmbeddingTarget
) -> dict[uuid.UUID, str]:
    source = target.source
    result = await session.execute(
        select(source.c.id, source.c.search_document).where(source.c.id.in_(ids))
    )
    return {row.id: row.search_document for row in result}


async def upsert_embeddings(
    session: AsyncSession, model: str, rows: Sequence[EmbeddingRow], *, target: EmbeddingTarget
) -> None:
    statement = insert(target.embeddings)
    statement = statement.on_conflict_do_update(
        constraint=target.embedding_unique,
        set_={
            "content_hash": statement.excluded.content_hash,
            "embedding": statement.excluded.embedding,
            "updated_at": func.now(),
        },
    )
    await session.execute(
        statement,
        [
            {
                "id": uuid.uuid4(),
                target.entity_column: row.entity_id,
                "model": model,
                "content_hash": row.content_hash,
                "embedding": row.vector,
            }
            for row in rows
        ],
    )


async def clear_failures(
    session: AsyncSession, model: str, ids: Sequence[uuid.UUID], *, target: EmbeddingTarget
) -> None:
    table, entity = target.failures, _entity(target, "failures")
    await session.execute(delete(table).where(entity.in_(ids), table.c.model == model))


async def record_failure(
    session: AsyncSession,
    *,
    entity_id: uuid.UUID,
    model: str,
    content_hash: str,
    error: str,
    target: EmbeddingTarget,
) -> None:
    table = target.failures
    statement = insert(table).values(
        {
            "id": uuid.uuid4(),
            target.entity_column: entity_id,
            "model": model,
            "content_hash": content_hash,
            "attempts": 1,
            "last_error": error,
        }
    )
    # Attempts keep counting only while the failing text is the same version.
    next_attempts = case(
        (table.c.content_hash == statement.excluded.content_hash, table.c.attempts + 1),
        else_=1,
    )
    await session.execute(
        statement.on_conflict_do_update(
            constraint=target.failure_unique,
            set_={
                "content_hash": statement.excluded.content_hash,
                "attempts": next_attempts,
                "last_error": statement.excluded.last_error,
                "updated_at": func.now(),
            },
        )
    )


def _failure_allows_retry(target: EmbeddingTarget) -> ColumnElement[bool]:
    failures = target.failures
    retry_delay = func.make_interval(
        0, 0, 0, 0, 0, 0, RETRY_BASE_SECONDS * func.power(RETRY_GROWTH, failures.c.attempts - 1)
    )
    transient_due = and_(
        not_(failures.c.last_error.startswith(_PERMANENT_ERROR_PREFIX)),
        failures.c.last_error != PRICE_UNKNOWN_ERROR,
        failures.c.last_error != BUDGET_EXCEEDED_ERROR,
        failures.c.attempts < MAX_TRANSIENT_ATTEMPTS,
        failures.c.updated_at + retry_delay <= func.now(),
    )
    return or_(
        failures.c.id.is_(None),
        # Edited since it failed: the new text gets a fresh try.
        failures.c.content_hash != _document_hash(target),
        # Callers only scan while the budget has room again.
        failures.c.last_error == BUDGET_EXCEEDED_ERROR,
        transient_due,
    )


async def find_stale_ids(
    session: AsyncSession, model: str, limit: int, *, target: EmbeddingTarget
) -> list[uuid.UUID]:
    """Entities with no embedding for `model`, or one made from an older document.

    This scan is the whole "queue": a save changes the document, so its hash no longer matches
    the stored embedding. Entities whose dead-letter row matches the current document are left
    out, except temporary failures whose retry delay has passed and budget refusals.

    shortcut: hashes every document on each poll, a few ms for ~1,000 rows; add a queue table
    (or a stored hash column with an index) once there are around 100k.
    """
    source, embeddings, failures = target.source, target.embeddings, target.failures
    statement = (
        select(source.c.id)
        .select_from(source)
        .outerjoin(
            embeddings,
            and_(_entity(target, "embeddings") == source.c.id, embeddings.c.model == model),
        )
        .outerjoin(
            failures,
            and_(_entity(target, "failures") == source.c.id, failures.c.model == model),
        )
        .where(
            or_(embeddings.c.id.is_(None), embeddings.c.content_hash != _document_hash(target)),
            _failure_allows_retry(target),
        )
        .order_by(source.c.id)
        .limit(limit)
    )
    return list((await session.scalars(statement)).all())


async def load_embedding_hash(
    session: AsyncSession, entity_id: uuid.UUID, model: str, *, target: EmbeddingTarget
) -> str | None:
    table = target.embeddings
    return await session.scalar(
        select(table.c.content_hash).where(
            _entity(target, "embeddings") == entity_id, table.c.model == model
        )
    )


async def load_current_vector(
    session: AsyncSession, entity_id: uuid.UUID, model: str, *, target: EmbeddingTarget
) -> list[float] | None:
    """The stored vector, only while it was made from the entity's current document."""
    table = target.embeddings
    text_vector = await session.scalar(
        select(cast(table.c.embedding, Text)).where(
            _entity(target, "embeddings") == entity_id,
            table.c.model == model,
            table.c.content_hash
            == select(_document_hash(target))
            .where(target.source.c.id == entity_id)
            .scalar_subquery(),
        )
    )
    # pgvector's text form "[0.1,0.2]" is valid JSON.
    return None if text_vector is None else [float(x) for x in json.loads(text_vector)]


async def load_current_hash(
    session: AsyncSession, entity_id: uuid.UUID, *, target: EmbeddingTarget
) -> str | None:
    return await session.scalar(
        select(_document_hash(target)).where(target.source.c.id == entity_id)
    )


async def load_failure(
    session: AsyncSession, entity_id: uuid.UUID, model: str, *, target: EmbeddingTarget
) -> KnownFailure | None:
    table = target.failures
    row = (
        await session.execute(
            select(table.c.content_hash, table.c.last_error, table.c.attempts).where(
                _entity(target, "failures") == entity_id, table.c.model == model
            )
        )
    ).first()
    return None if row is None else KnownFailure(row[0], row[1], row[2])


def similarity_statement(
    query_vector: list[float],
    model: str,
    limit: int,
    within: Select[uuid.UUID] | None = None,
) -> Select[uuid.UUID, float]:
    """Nearest candidates, best first. ORDER BY ... LIMIT alone on the table, so the planner
    answers it from the HNSW index. `within` (a subquery of candidate ids, built by the
    candidates feature) narrows it without this feature knowing the filter rules."""
    distance = CandidateEmbedding.embedding.op("<=>", return_type=Float)(
        bindparam("query_vector", query_vector, type_=Vector(EMBEDDING_DIMENSIONS))
    )
    statement = (
        select(CandidateEmbedding.candidate_id, (literal(1.0) - distance).label("similarity"))
        .where(CandidateEmbedding.model == model)
        .order_by(distance)
        .limit(limit)
    )
    if within is not None:
        statement = statement.where(CandidateEmbedding.candidate_id.in_(within))
    return statement


async def nearest_neighbours(
    session: AsyncSession,
    query_vector: list[float],
    model: str,
    limit: int,
    within: Select[uuid.UUID] | None = None,
) -> list[tuple[uuid.UUID, float]]:
    if within is not None:
        # The index returns ef_search (40) neighbours before the filter runs; with a selective
        # filter few would survive. Iterative scan keeps searching until `limit` pass.
        await session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
    result = await session.execute(similarity_statement(query_vector, model, limit, within))
    # relaxed_order may return neighbours slightly out of order.
    rows = sorted(result, key=lambda row: -float(row.similarity))
    return [(row.candidate_id, float(row.similarity)) for row in rows]
