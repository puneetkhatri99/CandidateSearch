"""Target descriptors and permanent-failure detection (no database, no network)."""

import pytest

from app.core.embeddings import PermanentEmbeddingError, TransientEmbeddingError
from app.core.errors import describe_error
from app.features.embeddings import repository
from app.features.embeddings.targets import CANDIDATES, JOBS, TARGETS


def test_targets_resolve_the_right_tables_and_operations() -> None:
    assert (CANDIDATES.embeddings.name, CANDIDATES.failures.name) == (
        "candidate_embeddings",
        "embedding_failures",
    )
    assert (JOBS.embeddings.name, JOBS.failures.name) == (
        "job_embeddings",
        "job_embedding_failures",
    )
    assert (CANDIDATES.operation, JOBS.operation) == ("candidate_embedding", "job_embedding")
    assert (CANDIDATES.entity_column, JOBS.entity_column) == ("candidate_id", "job_id")
    assert JOBS.source.name == "jobs"


def test_jobs_are_served_before_candidates() -> None:
    assert [target.name for target in TARGETS] == ["job", "candidate"]


def test_unique_constraint_names_exist_on_the_tables() -> None:
    for target in TARGETS:
        names = {
            constraint.name
            for table in (target.embeddings, target.failures)
            for constraint in table.constraints
        }
        assert {target.embedding_unique, target.failure_unique} <= names


@pytest.mark.parametrize(
    ("last_error", "permanent"),
    [
        ("PermanentEmbeddingError status=400", True),
        ("PermanentEmbeddingError", True),
        ("TransientEmbeddingError status=503", False),
        ("budget_exceeded", False),
        # Retrying cannot help until a price is added, so it is never retried automatically.
        ("model_price_unknown", True),
    ],
)
def test_is_permanent_failure(last_error: str, permanent: bool) -> None:
    assert repository.is_permanent_failure(last_error) is permanent


def test_describe_error_format_that_permanence_detection_relies_on() -> None:
    """If this changes, `is_permanent_failure` silently stops recognising dead letters."""
    assert describe_error(PermanentEmbeddingError("x", status_code=400)) == (
        "PermanentEmbeddingError status=400"
    )
    assert describe_error(PermanentEmbeddingError("x")) == "PermanentEmbeddingError"
    assert not repository.is_permanent_failure(describe_error(TransientEmbeddingError("x")))
