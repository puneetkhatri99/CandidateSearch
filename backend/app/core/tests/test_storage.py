import io
from collections.abc import Iterator

import pytest
from botocore.response import StreamingBody
from botocore.stub import Stubber

from app.core import storage
from app.core.config import get_settings
from app.core.storage import S3Storage, StorageError


@pytest.fixture
def s3() -> Iterator[tuple[S3Storage, Stubber]]:
    store = S3Storage(
        bucket="resumes",
        endpoint_url="https://storage.example.test",
        region="us-east-2",
        access_key_id="nak_test",
        secret_access_key="not-a-real-secret",  # noqa: S106 - a stubbed client, no network
    )
    with Stubber(store._client) as stubber:
        yield store, stubber
        stubber.assert_no_pending_responses()


def test_the_client_uses_path_style_and_sigv4() -> None:
    # Neon object storage supports only these.
    config = storage._CLIENT_CONFIG
    assert config.s3 == {"addressing_style": "path"}
    assert config.signature_version == "s3v4"


async def test_put_get_and_delete(s3: tuple[S3Storage, Stubber]) -> None:
    store, stubber = s3
    stubber.add_response(
        "put_object",
        {},
        {"Bucket": "resumes", "Key": "a.pdf", "Body": b"%PDF", "ContentType": "application/pdf"},
    )
    stubber.add_response(
        "get_object",
        {"Body": StreamingBody(io.BytesIO(b"%PDF"), 4)},
        {"Bucket": "resumes", "Key": "a.pdf"},
    )
    stubber.add_response("delete_object", {}, {"Bucket": "resumes", "Key": "a.pdf"})

    await store.put("a.pdf", b"%PDF", "application/pdf")
    assert await store.get("a.pdf") == b"%PDF"
    await store.delete("a.pdf")


async def test_a_missing_object_reads_as_none(s3: tuple[S3Storage, Stubber]) -> None:
    store, stubber = s3
    stubber.add_client_error("get_object", service_error_code="NoSuchKey", http_status_code=404)

    assert await store.get("gone.pdf") is None


async def test_other_errors_become_storage_errors_without_details(
    s3: tuple[S3Storage, Stubber],
) -> None:
    store, stubber = s3
    stubber.add_client_error(
        "put_object", service_error_code="AccessDenied", http_status_code=403,
        service_message="key resumes/secret-name.pdf denied",
    )  # fmt: skip

    with pytest.raises(StorageError) as raised:
        await store.put("resumes/secret-name.pdf", b"%PDF", "application/pdf")
    assert "secret-name" not in str(raised.value)


def test_no_store_without_a_bucket_and_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    storage.use_storage(None)
    settings = get_settings()
    monkeypatch.setattr(settings, "resume_bucket", "resumes")
    assert storage.get_storage() is None  # bucket but no keys
    monkeypatch.setattr(settings, "resume_bucket", None)
    assert storage.get_storage() is None


async def test_discarding_ignores_failures_and_missing_keys() -> None:
    class Failing:
        async def put(self, key: str, body: bytes, content_type: str) -> None: ...

        async def get(self, key: str) -> bytes | None:
            return None

        async def delete(self, key: str) -> None:
            raise StorageError("delete failed: EndpointConnectionError")

    storage.use_storage(Failing())
    try:
        await storage.discard("resumes/x.pdf")  # logged, not raised
        await storage.discard(None)
    finally:
        storage.use_storage(None)
