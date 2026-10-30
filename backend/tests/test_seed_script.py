import os
import random
import subprocess
import sys
from pathlib import Path

from faker import Faker

from app.features.candidates import CandidateCreate
from scripts.seed_candidates import build_payload

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_generated_payloads_are_valid_and_unique() -> None:
    fake, rng = Faker(), random.Random(7)
    Faker.seed(7)

    candidates = [CandidateCreate.model_validate(build_payload(i, fake, rng)) for i in range(300)]

    assert len({c.email for c in candidates}) == 300
    assert all(c.email.endswith("@example.com") for c in candidates)


def test_refuses_to_run_in_production() -> None:
    # Production settings require a real rate-limit secret; without one the process would stop
    # at settings validation before the seed script's own refusal could be checked.
    env = {**os.environ, "ENVIRONMENT": "production", "RATE_LIMIT_KEY_SECRET": "p" * 40}

    result = subprocess.run(
        [sys.executable, "-m", "scripts.seed_candidates", "--count", "1"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 1
    assert "seed_refused" in result.stdout
