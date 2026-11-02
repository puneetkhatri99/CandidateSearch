import json
import uuid
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx2
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.storage import StorageError, get_storage, use_storage
from app.features import resumes
from app.features.audit.models import AuditEvent
from app.features.candidates import CandidateCreate, create_candidate
from app.features.candidates.models import Candidate
from app.features.candidates.schemas import CandidateUpdate
from app.features.candidates.tests.factories import valid_candidate_payload
from tests.integration.conftest import FETCH_HEADERS

PDF = b"%PDF-1.7 formatted resume"
EXTRACTED = {
    "name": "Priya Raman",
    "email": "priya.raman@example.com",
    "phone": "+91 98765 43210",
    "location": "Pune, India",
    "links": ["https://github.com/priya"],
    "skills": ["Python", "FastAPI"],
    "experience": [
        {"company": "Nimbus", "title": "Backend Engineer", "start_date": "Jan 2021",
         "end_date": "Present", "location": "Pune", "description": "Built APIs"}
    ],
    "education": [],
    "projects": [],
    "certificates": [],
}  # fmt: skip


@dataclass
class FakeResumeAI:
    """ResumeAI's two endpoints, holding what was extracted per candidate_id."""

    stored: dict[str, bytes] = field(default_factory=dict)
    requests: list[httpx2.Request] = field(default_factory=list)
    fail_with: httpx2.Response | None = None

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        assert request.headers["X-API-Key"] == "test-resumeai-key"
        if self.fail_with is not None:
            return self.fail_with
        if request.method == "POST":
            body = request.content
            ref = body.split(b'name="candidate_id"\r\n\r\n', 1)[1].split(b"\r\n", 1)[0].decode()
            self.stored[ref] = body
            return httpx2.Response(
                200, json={"candidate_id": ref, "resume_id": "resume", "data": EXTRACTED}
            )
        ref = request.url.path.split("/")[-3]
        if ref not in self.stored:
            return httpx2.Response(404, json={"detail": "Resume not found."})
        return httpx2.Response(200, content=PDF, headers={"Content-Type": "application/pdf"})


@pytest.fixture
def resumeai() -> Iterator[FakeResumeAI]:
    fake = FakeResumeAI()
    client = resumes.ResumeAIClient(
        api_key="test-resumeai-key",
        base_url="https://resumeai.test",
        timeout_seconds=5,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(fake.handler)),
    )
    resumes.use_resumeai_client(client)
    yield fake
    resumes.use_resumeai_client(None)


async def _seed() -> uuid.UUID:
    async with get_sessionmaker()() as session:
        created = await create_candidate(
            session,
            CandidateCreate.model_validate(valid_candidate_payload()),
            consent_version="test",
        )
    return created.id


async def _resume_ref(candidate_id: uuid.UUID) -> uuid.UUID | None:
    async with get_sessionmaker()() as session:
        return await session.scalar(
            select(Candidate.resume_ref).where(Candidate.id == candidate_id)
        )


def _upload(
    client: AsyncClient, url: str, body: bytes = b"resume bytes", method: str = "POST"
) -> Any:
    return client.request(method, url, content=body, headers=FETCH_HEADERS)


# --- Reading a resume for the profile form ------------------------------------------------


async def test_reading_a_resume_suggests_profile_values(
    client: AsyncClient, resumeai: FakeResumeAI
) -> None:
    response = await _upload(client, "/api/v1/resumes")

    assert response.status_code == 200, response.text
    body = response.json()
    uuid.UUID(body["resume_ref"])
    profile = body["profile"]
    assert (profile["full_name"], profile["city"], profile["country_code"]) == (
        "Priya Raman", "Pune", "IN",
    )  # fmt: skip
    assert profile["skills"] == ["python", "fastapi"]
    assert profile["experiences"][0]["start_month"] == "2021-01"
    assert profile["experiences"][0]["is_current"] is True
    # ResumeAI got the file and our ref, never the browser's name for the file.
    sent = resumeai.requests[0]
    assert sent.url.path == "/api/public/resumes"
    assert body["resume_ref"].encode() in sent.content and b"resume bytes" in sent.content


async def test_the_public_read_needs_the_fetch_header(
    client: AsyncClient, resumeai: FakeResumeAI
) -> None:
    response = await client.post("/api/v1/resumes", content=b"x")

    assert response.status_code == 403
    assert resumeai.requests == []


async def test_an_empty_upload_is_refused_without_calling_resumeai(
    client: AsyncClient, resumeai: FakeResumeAI
) -> None:
    response = await _upload(client, "/api/v1/resumes", b"")

    assert response.status_code == 422
    assert resumeai.requests == []


async def test_uploads_may_be_up_to_4_mb_but_other_bodies_stay_small(
    client: AsyncClient, resumeai: FakeResumeAI
) -> None:
    assert (await _upload(client, "/api/v1/resumes", b"x" * 1_000_000)).status_code == 200
    too_big = await _upload(client, "/api/v1/resumes", b"x" * (get_settings().max_resume_bytes + 1))
    assert too_big.status_code == 413
    # The candidate form keeps its 64 KB limit.
    form = await client.post("/api/v1/candidates", content=b"x" * 100_000, headers=FETCH_HEADERS)
    assert form.status_code == 413


async def test_a_new_profile_saved_with_the_ref_has_a_resume(
    admin_client: AsyncClient, resumeai: FakeResumeAI
) -> None:
    ref = (await _upload(admin_client, "/api/v1/resumes")).json()["resume_ref"]
    payload = {**valid_candidate_payload(), "consent_confirmed": True, "resume_ref": ref}
    payload.pop("consent", None)
    payload.pop("website", None)

    created = await admin_client.post("/api/v1/admin/candidates", json=payload)

    assert created.status_code == 201, created.text
    assert created.json()["has_resume"] is True
    pdf = await admin_client.get(f"/api/v1/admin/candidates/{created.json()['id']}/resume")
    assert pdf.status_code == 200 and pdf.content == PDF


async def test_the_public_form_links_the_uploaded_resume(
    client: AsyncClient, resumeai: FakeResumeAI
) -> None:
    ref = (await _upload(client, "/api/v1/resumes")).json()["resume_ref"]

    response = await client.post(
        "/api/v1/candidates",
        json={**valid_candidate_payload(), "resume_ref": ref},
        headers=FETCH_HEADERS,
    )

    assert response.status_code == 201, response.text
    assert await _resume_ref(uuid.UUID(response.json()["id"])) == uuid.UUID(ref)


# --- Attaching to a saved candidate, and the formatted resume ------------------------------


async def test_staff_attach_a_resume_and_open_the_formatted_pdf(
    recruiter_client: AsyncClient, resumeai: FakeResumeAI
) -> None:
    candidate_id = await _seed()
    url = f"/api/v1/admin/candidates/{candidate_id}/resume"
    before = (await recruiter_client.get(f"/api/v1/admin/candidates/{candidate_id}")).json()

    assert (await recruiter_client.get(url)).status_code == 404
    assert resumeai.requests == []  # no resume yet: ResumeAI isn't asked
    assert (await _upload(recruiter_client, url, method="PUT")).status_code == 204

    after = (await recruiter_client.get(f"/api/v1/admin/candidates/{candidate_id}")).json()
    assert after["has_resume"] is True
    # The profile fields and version are untouched, so an open edit form can still save.
    assert {k: v for k, v in after.items() if k not in ("has_resume", "updated_at")} == {
        k: v for k, v in before.items() if k not in ("has_resume", "updated_at")
    }

    pdf = await recruiter_client.get(url)
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["content-disposition"] == 'inline; filename="resume.pdf"'
    assert pdf.headers["cache-control"] == "no-store"
    assert pdf.content == PDF
    async with get_sessionmaker()() as session:
        actions = list(
            await session.scalars(
                select(AuditEvent.action).where(AuditEvent.entity_id == candidate_id)
            )
        )
    assert "candidate.resume_attach" in actions and "candidate.resume_view" in actions


async def test_replacing_a_resume_reuses_the_ref(
    admin_client: AsyncClient, resumeai: FakeResumeAI
) -> None:
    candidate_id = await _seed()
    url = f"/api/v1/admin/candidates/{candidate_id}/resume"
    await _upload(admin_client, url, method="PUT")
    first = await _resume_ref(candidate_id)

    await _upload(admin_client, url, b"newer resume", method="PUT")

    assert await _resume_ref(candidate_id) == first
    assert len(resumeai.stored) == 1


async def test_attach_to_an_unknown_candidate_is_404(
    admin_client: AsyncClient, resumeai: FakeResumeAI
) -> None:
    response = await _upload(
        admin_client, f"/api/v1/admin/candidates/{uuid.uuid4()}/resume", method="PUT"
    )

    assert response.status_code == 404
    assert resumeai.requests == []


async def test_a_failed_read_attaches_nothing(
    admin_client: AsyncClient, resumeai: FakeResumeAI
) -> None:
    candidate_id = await _seed()
    resumeai.fail_with = httpx2.Response(415, json={"detail": "Unsupported file type."})

    response = await _upload(
        admin_client, f"/api/v1/admin/candidates/{candidate_id}/resume", method="PUT"
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_file"
    assert await _resume_ref(candidate_id) is None


@pytest.mark.parametrize(
    ("upstream", "status", "code", "message"),
    [
        (httpx2.Response(422, json={"detail": "The resume is over 4 pages."}), 422,
         "resume_unreadable", "The resume is over 4 pages."),
        # FastAPI's field lists aren't shown to people.
        (httpx2.Response(422, json={"detail": [{"loc": ["body", "file"]}]}), 422,
         "resume_unreadable", "We couldn't read this resume"),
        (httpx2.Response(402, json={"detail": "limit"}), 503, "resume_service_unavailable",
         "paused"),
        (httpx2.Response(401, json={"detail": "Invalid or missing API key."}), 503,
         "resume_service_unavailable", "RESUMEAI_API_KEY"),
        (httpx2.Response(502, json={"detail": "AI extraction failed"}), 502,
         "resume_service_failed", "Try again"),
        (httpx2.Response(200, content=b"not json"), 502, "resume_service_failed", "can't read"),
    ],
)  # fmt: skip
async def test_resumeai_errors_become_plain_messages(
    client: AsyncClient,
    resumeai: FakeResumeAI,
    upstream: httpx2.Response,
    status: int,
    code: str,
    message: str,
) -> None:
    resumeai.fail_with = upstream

    response = await _upload(client, "/api/v1/resumes")

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert message in response.json()["error"]["message"]


async def test_resumeai_rate_limit_passes_retry_after_on(
    client: AsyncClient, resumeai: FakeResumeAI
) -> None:
    resumeai.fail_with = httpx2.Response(429, headers={"Retry-After": "120"}, json={"detail": "x"})

    response = await _upload(client, "/api/v1/resumes")

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "120"


async def test_resumeai_not_answering_is_503(client: AsyncClient) -> None:
    def time_out(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    resumes.use_resumeai_client(
        resumes.ResumeAIClient(
            api_key="test-resumeai-key", base_url="https://resumeai.test", timeout_seconds=5,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(time_out)),
        )
    )  # fmt: skip
    try:
        response = await _upload(client, "/api/v1/resumes")
    finally:
        resumes.use_resumeai_client(None)

    assert response.status_code == 503
    assert "took too long" in response.json()["error"]["message"]


async def test_without_a_key_uploads_answer_503(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    resumes.use_resumeai_client(None)
    settings = get_settings().model_copy(update={"resumeai_api_key": None})
    monkeypatch.setattr("app.features.resumes.client.get_settings", lambda: settings)

    response = await _upload(client, "/api/v1/resumes")

    assert response.status_code == 503
    assert "isn't set up" in json.loads(response.text)["error"]["message"]


async def test_viewing_a_resume_needs_login(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/admin/candidates/{uuid.uuid4()}/resume")

    assert response.status_code == 401
    assert await _count_candidates() == 0


async def _count_candidates() -> int:
    async with get_sessionmaker()() as session:
        return await session.scalar(select(func.count()).select_from(Candidate)) or 0


# --- The stored copy of the formatted PDF ---------------------------------------------------


@dataclass
class FakeStorage:
    """An in-memory object store. `before_put` runs inside put, to change things mid-fetch."""

    objects: dict[str, bytes] = field(default_factory=dict)
    fail: bool = False
    before_put: Callable[[], Awaitable[None]] | None = None

    async def put(self, key: str, body: bytes, content_type: str) -> None:
        assert content_type == "application/pdf"
        if self.fail:
            raise StorageError("put failed: EndpointConnectionError")
        if self.before_put is not None:
            await self.before_put()
        self.objects[key] = body

    async def get(self, key: str) -> bytes | None:
        if self.fail:
            raise StorageError("get failed: EndpointConnectionError")
        return self.objects.get(key)

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


@pytest.fixture
def store() -> Iterator[FakeStorage]:
    fake = FakeStorage()
    use_storage(fake)
    yield fake
    use_storage(None)


async def _pdf_key(candidate_id: uuid.UUID) -> str | None:
    async with get_sessionmaker()() as session:
        return await session.scalar(
            select(Candidate.resume_pdf_key).where(Candidate.id == candidate_id)
        )


def _pdf_fetches(resumeai: FakeResumeAI) -> int:
    return sum(r.method == "GET" for r in resumeai.requests)


async def _with_resume(client: AsyncClient) -> tuple[uuid.UUID, str]:
    candidate_id = await _seed()
    url = f"/api/v1/admin/candidates/{candidate_id}/resume"
    assert (await _upload(client, url, method="PUT")).status_code == 204
    return candidate_id, url


def _same_profile(detail: dict[str, Any], **changes: Any) -> dict[str, Any]:
    return {k: v for k, v in detail.items() if k in CandidateUpdate.model_fields} | changes


async def test_the_first_view_stores_the_pdf_and_later_views_skip_resumeai(
    admin_client: AsyncClient, resumeai: FakeResumeAI, store: FakeStorage
) -> None:
    candidate_id, url = await _with_resume(admin_client)

    first = await admin_client.get(url)
    second = await admin_client.get(url)

    assert first.content == second.content == PDF
    assert _pdf_fetches(resumeai) == 1
    key = await _pdf_key(candidate_id)
    assert key is not None and key.startswith(f"resumes/{candidate_id}/")
    assert store.objects == {key: PDF}
    # Storing the link isn't a profile edit: an editor with the profile open can still save.
    detail = (await admin_client.get(f"/api/v1/admin/candidates/{candidate_id}")).json()
    assert detail["version"] == 1


async def test_a_profile_edit_removes_the_stored_pdf_and_the_next_view_fetches_again(
    admin_client: AsyncClient, resumeai: FakeResumeAI, store: FakeStorage
) -> None:
    candidate_id, url = await _with_resume(admin_client)
    await admin_client.get(url)
    detail = (await admin_client.get(f"/api/v1/admin/candidates/{candidate_id}")).json()

    edited = await admin_client.put(
        f"/api/v1/admin/candidates/{candidate_id}", json=_same_profile(detail, city="Pune")
    )

    assert edited.status_code == 200, edited.text
    assert await _pdf_key(candidate_id) is None
    assert store.objects == {}
    assert (await admin_client.get(url)).content == PDF
    assert _pdf_fetches(resumeai) == 2
    assert len(store.objects) == 1


async def test_saving_an_unchanged_profile_keeps_the_stored_pdf(
    admin_client: AsyncClient, resumeai: FakeResumeAI, store: FakeStorage
) -> None:
    candidate_id, url = await _with_resume(admin_client)
    await admin_client.get(url)
    key = await _pdf_key(candidate_id)
    detail = (await admin_client.get(f"/api/v1/admin/candidates/{candidate_id}")).json()

    saved = await admin_client.put(
        f"/api/v1/admin/candidates/{candidate_id}", json=_same_profile(detail)
    )

    assert saved.status_code == 200, saved.text
    assert await _pdf_key(candidate_id) == key
    assert key in store.objects


async def test_replacing_the_resume_removes_the_stored_pdf(
    admin_client: AsyncClient, resumeai: FakeResumeAI, store: FakeStorage
) -> None:
    candidate_id, url = await _with_resume(admin_client)
    await admin_client.get(url)

    assert (await _upload(admin_client, url, b"newer resume", method="PUT")).status_code == 204

    assert await _pdf_key(candidate_id) is None
    assert store.objects == {}


async def test_deleting_the_candidate_deletes_the_stored_pdf(
    admin_client: AsyncClient, resumeai: FakeResumeAI, store: FakeStorage
) -> None:
    candidate_id, url = await _with_resume(admin_client)
    await admin_client.get(url)

    deleted = await admin_client.delete(f"/api/v1/admin/candidates/{candidate_id}")

    assert deleted.status_code == 204
    assert store.objects == {}


async def test_a_pdf_fetched_while_the_profile_changed_is_not_kept(
    admin_client: AsyncClient, resumeai: FakeResumeAI, store: FakeStorage
) -> None:
    candidate_id, url = await _with_resume(admin_client)

    async def edit_meanwhile() -> None:
        async with get_sessionmaker()() as session, session.begin():
            await session.execute(
                update(Candidate)
                .where(Candidate.id == candidate_id)
                .values(version=Candidate.version + 1)
            )

    store.before_put = edit_meanwhile

    response = await admin_client.get(url)

    assert response.content == PDF  # the person still sees the resume
    assert await _pdf_key(candidate_id) is None
    assert store.objects == {}


async def test_a_stored_pdf_that_went_missing_is_fetched_and_replaced(
    admin_client: AsyncClient, resumeai: FakeResumeAI, store: FakeStorage
) -> None:
    candidate_id, url = await _with_resume(admin_client)
    await admin_client.get(url)
    old_key = await _pdf_key(candidate_id)
    store.objects.clear()

    assert (await admin_client.get(url)).content == PDF

    new_key = await _pdf_key(candidate_id)
    assert new_key is not None and new_key != old_key
    assert store.objects == {new_key: PDF}


async def test_a_storage_outage_still_shows_the_resume(
    admin_client: AsyncClient, resumeai: FakeResumeAI, store: FakeStorage
) -> None:
    candidate_id, url = await _with_resume(admin_client)
    store.fail = True

    response = await admin_client.get(url)

    assert response.status_code == 200
    assert response.content == PDF
    assert await _pdf_key(candidate_id) is None


async def test_without_storage_every_view_asks_resumeai(
    admin_client: AsyncClient, resumeai: FakeResumeAI
) -> None:
    assert get_storage() is None  # the test settings have no bucket
    candidate_id, url = await _with_resume(admin_client)

    await admin_client.get(url)
    await admin_client.get(url)

    assert _pdf_fetches(resumeai) == 2
    assert await _pdf_key(candidate_id) is None
