import uuid

from sqlalchemy import CHAR, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import TimestampedModel
from app.core.vector import Vector

# Must match the vector(...) size in the migration and Settings.embedding_dimensions.
EMBEDDING_DIMENSIONS = 1536
HNSW_INDEX_NAME = "ix_candidate_embeddings_embedding_hnsw"
JOB_HNSW_INDEX_NAME = "ix_job_embeddings_embedding_hnsw"


class CandidateEmbedding(TimestampedModel):
    __tablename__ = "candidate_embeddings"
    __table_args__ = (
        # Also serves as the candidate_id index.
        UniqueConstraint(
            "candidate_id", "model", name="uq_candidate_embeddings_candidate_id_model"
        ),
        Index(
            HNSW_INDEX_NAME,
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    model: Mapped[str] = mapped_column(String(100))
    # sha256 of the search_document that was embedded; unchanged text is never re-embedded.
    content_hash: Mapped[str] = mapped_column(CHAR(64))
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))


class EmbeddingFailure(TimestampedModel):
    """Dead letter: the text version (by hash) that could not be embedded, and why.

    It also paces retries: a temporary failure is tried again after a delay that grows with
    `attempts` (see repository.find_stale_ids).
    """

    __tablename__ = "embedding_failures"
    __table_args__ = (
        UniqueConstraint("candidate_id", "model", name="uq_embedding_failures_candidate_id_model"),
    )

    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    model: Mapped[str] = mapped_column(String(100))
    content_hash: Mapped[str] = mapped_column(CHAR(64))
    attempts: Mapped[int] = mapped_column(Integer)
    # Error class and HTTP status only; never input text.
    last_error: Mapped[str] = mapped_column(String(200))


class JobEmbedding(TimestampedModel):
    """Mirror of CandidateEmbedding for job roles."""

    __tablename__ = "job_embeddings"
    __table_args__ = (
        # Also serves as the job_id index.
        UniqueConstraint("job_id", "model", name="uq_job_embeddings_job_id_model"),
        Index(
            JOB_HNSW_INDEX_NAME,
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    model: Mapped[str] = mapped_column(String(100))
    content_hash: Mapped[str] = mapped_column(CHAR(64))
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))


class JobEmbeddingFailure(TimestampedModel):
    """Dead letter for job documents, mirroring EmbeddingFailure."""

    __tablename__ = "job_embedding_failures"
    __table_args__ = (
        UniqueConstraint("job_id", "model", name="uq_job_embedding_failures_job_id_model"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    model: Mapped[str] = mapped_column(String(100))
    content_hash: Mapped[str] = mapped_column(CHAR(64))
    attempts: Mapped[int] = mapped_column(Integer)
    # Error class and HTTP status only; never input text.
    last_error: Mapped[str] = mapped_column(String(200))
