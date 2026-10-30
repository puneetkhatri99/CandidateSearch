"""Key hashing and settings rules. The limiter's counting is tested against Postgres in
tests/integration/test_rate_limit_db.py, because the table is the limiter."""

from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from app.core import rate_limit
from app.core.config import DEVELOPMENT_RATE_LIMIT_KEY_SECRET, Settings, get_settings

DATABASE_URL = "postgresql+asyncpg://user:pass@localhost:5432/db"


def test_keys_are_deterministic_and_scoped() -> None:
    key = rate_limit.rate_limit_key("login_failure", "asha@example.com", "10.0.0.1")
    assert key == rate_limit.rate_limit_key("login_failure", "asha@example.com", "10.0.0.1")
    assert key.startswith("login_failure:")
    assert key != rate_limit.rate_limit_key("other_scope", "asha@example.com", "10.0.0.1")
    assert len(key) <= 100  # fits the column


def test_keys_never_contain_the_identity() -> None:
    key = rate_limit.rate_limit_key("login_failure", "asha@example.com", "10.0.0.1")
    assert "asha" not in key
    assert "10.0.0.1" not in key


def test_identity_parts_cannot_be_rejoined_into_the_same_key() -> None:
    assert rate_limit.rate_limit_key("s", "a:b", "c") != rate_limit.rate_limit_key("s", "a", "b:c")


def test_a_different_secret_gives_a_different_key(monkeypatch: pytest.MonkeyPatch) -> None:
    before = rate_limit.rate_limit_key("s", "x")
    settings = get_settings().model_copy(update={"rate_limit_key_secret": SecretStr("other" * 8)})
    monkeypatch.setattr(rate_limit, "get_settings", lambda: settings)
    assert rate_limit.rate_limit_key("s", "x") != before


@pytest.mark.parametrize("environment", ["staging", "production"])
@pytest.mark.parametrize(
    "secret",
    [
        None,
        "too-short",
        DEVELOPMENT_RATE_LIMIT_KEY_SECRET,
        "change-me-to-a-long-random-string-of-32-plus-chars",
    ],
)
def test_staging_and_production_require_a_real_secret(environment: str, secret: str | None) -> None:
    # Any: Settings' keyword arguments are heterogeneous, so a typed dict can't express them.
    values: dict[str, Any] = {"environment": environment, "database_url": DATABASE_URL}
    if secret is not None:
        values["rate_limit_key_secret"] = secret
    with pytest.raises(ValidationError, match="RATE_LIMIT_KEY_SECRET"):
        Settings(_env_file=None, **values)


def test_a_long_random_secret_is_accepted_in_production() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        database_url=DATABASE_URL,
        rate_limit_key_secret=SecretStr("k3" * 20),
    )
    assert settings.rate_limit_key_secret.get_secret_value() == "k3" * 20


def test_local_uses_the_development_secret() -> None:
    settings = Settings(_env_file=None, database_url=DATABASE_URL)
    assert settings.rate_limit_key_secret.get_secret_value() == DEVELOPMENT_RATE_LIMIT_KEY_SECRET
