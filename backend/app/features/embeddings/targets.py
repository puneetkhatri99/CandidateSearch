"""What gets embedded: one descriptor per kind of entity, so the embedding logic exists once.

Candidates and jobs have parallel tables (real foreign keys with cascade, separate HNSW
indexes). The descriptor names each target's tables and constraints; the repository and
service are parameterised by it.
"""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Table, TableClause, column, table
from sqlalchemy.orm import DeclarativeBase

from app.features.embeddings.models import (
    CandidateEmbedding,
    EmbeddingFailure,
    JobEmbedding,
    JobEmbeddingFailure,
)

TargetName = Literal["candidate", "job"]


def _table_of(model: type[DeclarativeBase]) -> Table:
    mapped = model.__table__
    if not isinstance(mapped, Table):  # pragma: no cover - declarative models always map a Table
        raise TypeError(f"{model.__name__} is not mapped to a table")
    return mapped


@dataclass(frozen=True)
class EmbeddingTarget:
    name: TargetName
    # The ai_usage operation under which every call for this target is metered.
    operation: str
    # Read-only reference to the embedded entity's table (deliberate boundary exception).
    source: TableClause
    embeddings: Table
    failures: Table
    entity_column: str
    embedding_unique: str
    failure_unique: str


CANDIDATES = EmbeddingTarget(
    name="candidate",
    operation="candidate_embedding",
    source=table("candidates", column("id"), column("search_document")),
    embeddings=_table_of(CandidateEmbedding),
    failures=_table_of(EmbeddingFailure),
    entity_column="candidate_id",
    embedding_unique="uq_candidate_embeddings_candidate_id_model",
    failure_unique="uq_embedding_failures_candidate_id_model",
)

JOBS = EmbeddingTarget(
    name="job",
    operation="job_embedding",
    source=table("jobs", column("id"), column("search_document")),
    embeddings=_table_of(JobEmbedding),
    failures=_table_of(JobEmbeddingFailure),
    entity_column="job_id",
    embedding_unique="uq_job_embeddings_job_id_model",
    failure_unique="uq_job_embedding_failures_job_id_model",
)

# Jobs first: a recruiter is waiting on a new job, while candidates usually arrive in bulk.
TARGETS = (JOBS, CANDIDATES)
