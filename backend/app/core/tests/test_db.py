import os
import subprocess
import sys

_SCRIPT = """
from app.features.embeddings import models
from app.core.db import Base, register_all_models
register_all_models()
table = Base.metadata.tables['candidate_embeddings']
print(list(table.c.candidate_id.foreign_keys)[0].column.table.name)
"""


def test_embedding_models_resolve_foreign_keys_in_a_worker_like_process() -> None:
    """A process that imports only the embeddings feature must still resolve its foreign keys."""
    result = subprocess.run(  # noqa: S603 (fixed interpreter and script, no user input)
        [sys.executable, "-I", "-c", _SCRIPT],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
        env={
            "DATABASE_URL": "postgresql+asyncpg://u:p@localhost/none",
            "ENVIRONMENT": "test",
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", r"C:\Windows"),
        },
    )

    assert result.stdout.strip() == "candidates"
