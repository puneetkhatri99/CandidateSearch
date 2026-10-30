"""Embeddings for candidates and job roles: the stale scan that embeds them, and nearest search."""

from app.features.embeddings.service import (
    EmbedOutcome,
    JobEmbeddingStatus,
    embed_all_stale,
    embed_stale,
    get_job_embedding_status,
    load_job_vector,
    nearest_candidates_to_vector,
)
from app.features.embeddings.targets import CANDIDATES, JOBS, TARGETS

__all__ = [
    "CANDIDATES",
    "JOBS",
    "TARGETS",
    "EmbedOutcome",
    "JobEmbeddingStatus",
    "embed_all_stale",
    "embed_stale",
    "get_job_embedding_status",
    "load_job_vector",
    "nearest_candidates_to_vector",
]
