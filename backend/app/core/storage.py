"""S3-compatible object storage (Neon object storage in practice) for files we keep, such as the
formatted resume PDFs.

boto3 is synchronous, so every call runs in a worker thread and never blocks the event loop.
Errors become StorageError with the exception class only (never a key or a body), so callers
can fall back instead of failing the request.
"""

import asyncio
from typing import Any, Protocol

import boto3
import structlog
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import get_settings

logger = structlog.get_logger(__name__)

# The SDK's own retries (RULES section 7: configure them, don't stack another layer).
_CLIENT_CONFIG = Config(
    signature_version="s3v4",
    # Neon object storage supports path-style addressing only.
    s3={"addressing_style": "path"},
    retries={"mode": "standard", "max_attempts": 3},
    connect_timeout=5,
    read_timeout=30,
)
_MISSING = {"NoSuchKey", "404", "NotFound"}


class StorageError(Exception):
    """The object store failed; the message never contains keys or contents."""


class ObjectStorage(Protocol):
    async def put(self, key: str, body: bytes, content_type: str) -> None: ...

    async def get(self, key: str) -> bytes | None:
        """None when there is no object under `key`."""
        ...

    async def delete(self, key: str) -> None:
        """Deleting a missing key is not an error."""
        ...


class S3Storage:
    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None,
        region: str,
        access_key_id: str,
        secret_access_key: str,
    ) -> None:
        self._bucket = bucket
        # Any: boto3 ships no type hints; only the three methods below touch the client.
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            config=_CLIENT_CONFIG,
        )

    async def put(self, key: str, body: bytes, content_type: str) -> None:
        try:
            await asyncio.to_thread(
                self._client.put_object,
                Bucket=self._bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
            )
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(f"put failed: {type(exc).__name__}") from exc

    async def get(self, key: str) -> bytes | None:
        def read() -> bytes:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            body: bytes = response["Body"].read()
            return body

        try:
            return await asyncio.to_thread(read)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _MISSING:
                return None
            raise StorageError(f"get failed: {type(exc).__name__}") from exc
        except BotoCoreError as exc:
            raise StorageError(f"get failed: {type(exc).__name__}") from exc

    async def delete(self, key: str) -> None:
        try:
            await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(f"delete failed: {type(exc).__name__}") from exc


_installed: ObjectStorage | None = None


def get_storage() -> ObjectStorage | None:
    """The configured store, or None when the bucket or keys aren't set (features then work
    without storing files)."""
    global _installed
    if _installed is None:
        settings = get_settings()
        key_id = (
            settings.aws_access_key_id.get_secret_value().strip()
            if settings.aws_access_key_id
            else ""
        )
        secret = (
            settings.aws_secret_access_key.get_secret_value().strip()
            if settings.aws_secret_access_key
            else ""
        )
        # .env.example ships CHANGE_ME placeholders; they count as not configured.
        if not settings.resume_bucket or {key_id.upper(), secret.upper()} & {"", "CHANGE_ME"}:
            return None
        _installed = S3Storage(
            bucket=settings.resume_bucket,
            endpoint_url=settings.aws_endpoint_url_s3 or None,
            region=settings.aws_region,
            access_key_id=key_id,
            secret_access_key=secret,
        )
    return _installed


def use_storage(storage: ObjectStorage | None) -> None:
    """Install a store (tests) or clear the slot so the next get_storage reads the settings."""
    global _installed
    _installed = storage


async def discard(key: str | None) -> None:
    """Delete an object nothing points at any more. A failure only leaves an orphan file, so it
    is logged, not raised: the database change it follows has already committed."""
    storage = get_storage()
    if key is None or storage is None:
        return
    try:
        await storage.delete(key)
    except StorageError as exc:
        logger.warning("stored_file_not_deleted", error=str(exc))
