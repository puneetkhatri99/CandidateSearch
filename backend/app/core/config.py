"""Application settings. The only module that reads environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "staging", "production"]

# Passed explicitly so a stray OPENAI_BASE_URL in the environment cannot redirect candidate text.
OPENAI_BASE_URL = "https://api.openai.com/v1"

# Fixed and public on purpose: fine for local and test, rejected in staging and production.
DEVELOPMENT_RATE_LIMIT_KEY_SECRET = "local-development-rate-limit-key-not-a-secret"  # noqa: S105
_NON_SECRET_RATE_LIMIT_KEYS = {
    DEVELOPMENT_RATE_LIMIT_KEY_SECRET,
    "change-me-to-a-long-random-string-of-32-plus-chars",  # the .env.example placeholder
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "candidateSearch API"
    # No default: a deploy that forgets it must fail, not run with dev cookies and secrets.
    environment: Environment
    log_level: str = "INFO"

    database_url: PostgresDsn
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_echo: bool = False

    cors_origins: list[str] = ["http://localhost:5180"]
    # Raise per route (or move uploads to direct-to-storage) when file uploads arrive.
    max_request_body_bytes: int = 64 * 1024

    # Version of the privacy notice candidates consent to; bump when the notice text changes.
    privacy_notice_version: str = "2026-10-draft"
    candidate_submit_limit: int = 5
    candidate_submit_window_seconds: int = 3600

    session_cookie_name: str = "cs_session"
    session_ttl_hours: int = 8
    login_failure_limit: int = 5
    login_failure_window_seconds: int = 900
    # Per email across all IPs, so guessing from many addresses is capped too.
    login_account_failure_limit: int = 20

    # Creating accounts and resetting passwords each run argon2, so they are limited per admin.
    admin_account_write_limit: int = 20
    admin_account_write_window_seconds: int = 3600
    # HMAC key for rate-limit keys, so emails and IPs are never stored in clear. Every process
    # must share it; rotating it resets all limits. Required in staging and production.
    rate_limit_key_secret: SecretStr = SecretStr(DEVELOPMENT_RATE_LIMIT_KEY_SECRET)

    openai_api_key: SecretStr | None = None
    embedding_model: str = "text-embedding-3-small"
    # Must match the vector(...) size in the candidate_embeddings migration.
    embedding_dimensions: int = 1536
    # Documents per OpenAI request, and per pass of the stale scan.
    embedding_batch_size: int = Field(default=64, ge=1, le=2048)
    # Per HTTP attempt; the SDK retries transient failures up to embedding_max_retries times.
    embedding_timeout_seconds: float = 30
    embedding_max_retries: int = Field(default=3, ge=0, le=10)
    # How often the stale scan looks for documents to embed.
    embedding_poll_seconds: float = Field(default=2.0, gt=0)
    # Background tasks (embedding, pruning) inside the API. Turn off to run
    # `python -m app.cli maintenance` separately.
    maintenance_in_api: bool = True

    @model_validator(mode="after")
    def _require_real_secrets_outside_development(self) -> "Settings":
        if self.environment in ("staging", "production"):
            secret = self.rate_limit_key_secret.get_secret_value()
            if len(secret) < 32 or secret in _NON_SECRET_RATE_LIMIT_KEYS:
                raise ValueError(
                    "RATE_LIMIT_KEY_SECRET must be a random value of at least 32 characters "
                    f"in {self.environment}."
                )
        return self

    def usable_openai_api_key(self) -> str | None:
        # `OPENAI_API_KEY=` in .env loads as an empty secret, and .env.example ships a
        # placeholder; both must count as missing rather than fail as a 401 on every call.
        key = self.openai_api_key.get_secret_value().strip() if self.openai_api_key else ""
        return None if not key or key.lower().startswith("sk-change_me") else key

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def session_cookie_secure(self) -> bool:
        # Local dev and tests run over plain http, where browsers drop Secure cookies.
        return self.environment in ("staging", "production")


@lru_cache
def get_settings() -> Settings:
    return Settings()
