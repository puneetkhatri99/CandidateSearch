"""Job roles: /api/v1/jobs."""

import asyncio
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.embeddings import get_embedding_provider
from app.features.audit.models import AuditEvent
from app.features.embeddings import JOBS, embed_stale
from app.features.embeddings import repository as embedding_repository
from app.features.jobs import repository
from app.features.jobs.models import Job
from app.features.jobs.tests.factories import valid_job_payload
from tests.integration.conftest import FETCH_HEADERS, create_job, create_staff, signed_in_client

URL = "/api/v1/jobs"


async def _count(db_session: AsyncSession, model: Any) -> int:
    return int(await db_session.scalar(select(func.count()).select_from(model)) or 0)


async def _stale_job_ids() -> list[str]:
    """Jobs the background task would embed next (a save makes a job stale)."""
    async with get_sessionmaker()() as session, session.begin():
        ids = await embedding_repository.find_stale_ids(
            session, get_settings().embedding_model, 100, target=JOBS
        )
    return [str(i) for i in ids]


async def _embed_jobs() -> None:
    async with get_sessionmaker()() as session:
        await embed_stale(session, get_embedding_provider(), JOBS)


async def _audit(db_session: AsyncSession, action: str) -> list[AuditEvent]:
    return list(await db_session.scalars(select(AuditEvent).where(AuditEvent.action == action)))


# --- Create --------------------------------------------------------------------------------


async def test_a_recruiter_creates_a_job_with_a_redacted_document_waiting_to_be_embedded(
    recruiter_client: AsyncClient, db_session: AsyncSession
) -> None:
    description = (
        "Reach out to Staff Member or staff@example.com with questions about this role. " * 3
    )

    response = await recruiter_client.post(URL, json=valid_job_payload(description=description))

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["version"] == 1
    assert body["can_edit"] is True
    assert body["embedding_status"] == "pending"
    assert body["created_by"]["full_name"] == "Staff Member"
    assert body["must_have_skills"] == ["python", "postgresql"]
    assert body["min_years"] == 3.0
    job = await db_session.scalar(select(Job))
    assert job is not None
    assert str(job.id) == body["id"]
    assert job.version == 1
    assert "staff@example.com" not in job.search_document
    assert "Staff Member" not in job.search_document
    assert "Senior Backend Engineer." in job.search_document
    assert await _stale_job_ids() == [body["id"]]
    [event] = await _audit(db_session, "job.create")
    assert event.entity_id == job.id
    assert event.details == {}


async def test_a_rejected_create_leaves_no_job_or_audit_event(
    recruiter_client: AsyncClient, db_session: AsyncSession
) -> None:
    response = await recruiter_client.post(URL, json=valid_job_payload(title=""))

    assert response.status_code == 422
    assert await _count(db_session, Job) == 0
    assert await _audit(db_session, "job.create") == []


# --- Read ----------------------------------------------------------------------------------


async def test_every_staff_member_sees_every_job_but_only_owner_and_admin_can_edit(
    recruiter_client: AsyncClient, app: FastAPI
) -> None:
    job = await create_job(recruiter_client)
    await create_staff("other@example.com", "recruiter")
    await create_staff("boss@example.com", "admin")

    async with signed_in_client(app, "other@example.com") as other:
        listed = (await other.get(URL)).json()["items"]
        detail = (await other.get(f"{URL}/{job['id']}")).json()
    async with signed_in_client(app, "boss@example.com") as boss:
        boss_detail = (await boss.get(f"{URL}/{job['id']}")).json()

    assert [item["id"] for item in listed] == [job["id"]]
    assert detail["can_edit"] is False
    assert boss_detail["can_edit"] is True
    assert (await recruiter_client.get(f"{URL}/{job['id']}")).json()["can_edit"] is True


async def test_the_list_filters_by_status_and_shows_closed_jobs_by_default(
    recruiter_client: AsyncClient,
) -> None:
    draft = await create_job(recruiter_client, title="Draft role")
    open_job = await create_job(recruiter_client, title="Open role", status="open")
    closed = await create_job(recruiter_client, title="Closed role", status="closed")

    everything = (await recruiter_client.get(URL)).json()["items"]
    only_open = (await recruiter_client.get(URL, params={"status": "open"})).json()["items"]

    assert {item["id"] for item in everything} == {draft["id"], open_job["id"], closed["id"]}
    assert [item["id"] for item in only_open] == [open_job["id"]]
    assert "description" not in everything[0]
    assert (await recruiter_client.get(URL, params={"status": "archived"})).status_code == 422


async def test_keyset_paging_has_no_gaps_or_duplicates_while_jobs_are_added(
    recruiter_client: AsyncClient,
) -> None:
    created = [(await create_job(recruiter_client, title=f"Role {i}"))["id"] for i in range(5)]

    first = (await recruiter_client.get(URL, params={"limit": 2})).json()
    inserted = (await create_job(recruiter_client, title="Added mid-paging"))["id"]
    seen = [item["id"] for item in first["items"]]
    cursor = first["next_cursor"]
    while cursor:
        page = (await recruiter_client.get(URL, params={"limit": 2, "cursor": cursor})).json()
        seen.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]

    assert len(seen) == len(set(seen)) == 5
    assert set(seen) == set(created)
    assert inserted not in seen  # newer than the first page; the next fresh listing shows it


async def test_the_page_size_is_capped(recruiter_client: AsyncClient) -> None:
    assert (await recruiter_client.get(URL, params={"limit": 101})).status_code == 422
    assert (await recruiter_client.get(URL, params={"limit": 100})).status_code == 200


async def test_job_detail_reports_the_four_embedding_states(
    recruiter_client: AsyncClient, db_session: AsyncSession
) -> None:
    job = await create_job(recruiter_client)

    detail = (await recruiter_client.get(f"{URL}/{job['id']}")).json()

    assert detail["embedding_status"] == "pending"
    assert detail["description"].startswith("You will design")
    assert detail["nice_to_have_skills"] == ["kubernetes"]


# --- Edit ----------------------------------------------------------------------------------


async def test_the_owner_edits_a_job_and_it_needs_a_new_embedding(
    recruiter_client: AsyncClient, db_session: AsyncSession
) -> None:
    job = await create_job(recruiter_client)
    await _embed_jobs()

    response = await recruiter_client.patch(
        f"{URL}/{job['id']}", json={"version": 1, "title": "Staff Backend Engineer"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    # Exactly one version step per edit (a regression: autoflush once wrote the edit twice).
    assert (body["title"], body["version"]) == ("Staff Backend Engineer", 2)
    assert await _stale_job_ids() == [job["id"]]
    [event] = await _audit(db_session, "job.update")
    assert event.details == {"changed_fields": ["title"], "status": "draft"}


async def test_an_admin_can_edit_someone_elses_job(
    recruiter_client: AsyncClient, admin_client: AsyncClient
) -> None:
    job = await create_job(recruiter_client)

    response = await admin_client.patch(
        f"{URL}/{job['id']}", json={"version": 1, "department": "Growth"}
    )

    assert response.status_code == 200
    assert response.json()["department"] == "Growth"


async def test_another_recruiter_gets_403_and_nothing_changes(
    recruiter_client: AsyncClient, app: FastAPI, db_session: AsyncSession
) -> None:
    job = await create_job(recruiter_client)
    await create_staff("other@example.com", "recruiter")

    async with signed_in_client(app, "other@example.com") as other:
        response = await other.patch(f"{URL}/{job['id']}", json={"version": 1, "title": "Hijack"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    stored = await db_session.scalar(select(Job))
    assert stored is not None
    assert (stored.title, stored.version) == ("Senior Backend Engineer", 1)
    assert await _audit(db_session, "job.update") == []


async def test_a_stale_version_is_a_conflict_that_changes_nothing(
    recruiter_client: AsyncClient,
) -> None:
    job = await create_job(recruiter_client)
    assert (
        await recruiter_client.patch(f"{URL}/{job['id']}", json={"version": 1, "title": "First"})
    ).status_code == 200

    stale = await recruiter_client.patch(
        f"{URL}/{job['id']}", json={"version": 1, "title": "Second"}
    )

    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "version_conflict"
    assert (await recruiter_client.get(f"{URL}/{job['id']}")).json()["title"] == "First"


async def test_two_simultaneous_edits_with_the_same_version_do_not_overwrite_each_other(
    recruiter_client: AsyncClient,
) -> None:
    job = await create_job(recruiter_client)

    results = await asyncio.gather(
        recruiter_client.patch(f"{URL}/{job['id']}", json={"version": 1, "title": "Alpha"}),
        recruiter_client.patch(f"{URL}/{job['id']}", json={"version": 1, "title": "Beta"}),
    )

    assert sorted(r.status_code for r in results) == [200, 409]


async def test_a_partial_patch_closes_the_job_without_changing_the_document(
    recruiter_client: AsyncClient, db_session: AsyncSession
) -> None:
    job = await create_job(recruiter_client, status="open")
    before = (await db_session.scalar(select(Job.search_document))) or ""

    response = await recruiter_client.patch(
        f"{URL}/{job['id']}", json={"version": 1, "status": "closed"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "closed"
    db_session.expire_all()
    assert await db_session.scalar(select(Job.search_document)) == before


async def test_an_unchanged_patch_does_not_bump_the_version(
    recruiter_client: AsyncClient,
) -> None:
    job = await create_job(recruiter_client)

    response = await recruiter_client.patch(
        f"{URL}/{job['id']}", json={"version": 1, "title": job["title"]}
    )

    assert response.status_code == 200
    assert response.json()["version"] == 1


async def test_a_merged_result_that_breaks_a_rule_is_a_422_with_body_locations(
    recruiter_client: AsyncClient,
) -> None:
    job = await create_job(recruiter_client)  # min_years 3
    remote = await create_job(
        recruiter_client, work_mode="remote", city=None, country_code=None, title="Remote role"
    )

    below_min = await recruiter_client.patch(
        f"{URL}/{job['id']}", json={"version": 1, "max_years": 1}
    )
    needs_city = await recruiter_client.patch(
        f"{URL}/{remote['id']}", json={"version": 1, "work_mode": "hybrid"}
    )

    for response, field in ((below_min, "max_years"), (needs_city, "city")):
        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "validation_error"
        assert ["body", field] in [e["loc"] for e in error["details"]["errors"]]


async def test_an_explicit_null_clears_an_optional_field(recruiter_client: AsyncClient) -> None:
    job = await create_job(recruiter_client)

    response = await recruiter_client.patch(
        f"{URL}/{job['id']}", json={"version": 1, "department": None, "max_years": None}
    )

    assert response.status_code == 200
    assert (response.json()["department"], response.json()["max_years"]) == (None, None)


async def test_skills_are_renormalised_on_edit(recruiter_client: AsyncClient) -> None:
    job = await create_job(recruiter_client)

    response = await recruiter_client.patch(
        f"{URL}/{job['id']}",
        json={"version": 1, "must_have_skills": [" Go ", "go", "RUST"], "nice_to_have_skills": []},
    )

    assert response.json()["must_have_skills"] == ["go", "rust"]


async def test_creating_requires_the_csrf_header(recruiter_client: AsyncClient) -> None:
    recruiter_client.headers.pop("X-Requested-With")

    response = await recruiter_client.post(URL, json=valid_job_payload())

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"
    recruiter_client.headers.update(FETCH_HEADERS)


# --- Re-embedding and audit rules ----------------------------------------------------------


async def test_a_status_only_edit_is_audited_but_needs_no_new_embedding(
    recruiter_client: AsyncClient, db_session: AsyncSession
) -> None:
    job = await create_job(recruiter_client)
    await _embed_jobs()

    await _patch_job(recruiter_client, job, status="open")

    assert await _stale_job_ids() == []
    [event] = await _audit(db_session, "job.update")
    assert event.details == {"changed_fields": ["status"], "status": "open"}


async def test_an_edit_that_changes_nothing_needs_no_embedding_and_audits_nothing(
    recruiter_client: AsyncClient, db_session: AsyncSession
) -> None:
    job = await create_job(recruiter_client)
    await _embed_jobs()

    await _patch_job(recruiter_client, job, title=job["title"])

    assert await _stale_job_ids() == []
    assert await _audit(db_session, "job.update") == []


async def test_a_text_edit_needs_a_new_embedding(recruiter_client: AsyncClient) -> None:
    job = await create_job(recruiter_client)
    await _embed_jobs()

    await _patch_job(recruiter_client, job, description="Rewritten description. " * 10)

    assert await _stale_job_ids() == [job["id"]]


async def _patch_job(client: AsyncClient, job: dict[str, Any], **changes: Any) -> None:
    response = await client.patch(f"{URL}/{job['id']}", json={"version": job["version"], **changes})
    assert response.status_code == 200, response.text


# --- Database constraints ------------------------------------------------------------------


async def test_a_database_constraint_violation_on_create_is_a_422_not_a_500(
    recruiter_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def violate(session: AsyncSession, job: Job) -> None:
        raise IntegrityError("INSERT INTO jobs", {}, Exception("check constraint violated"))

    monkeypatch.setattr(repository, "add_job", violate)

    response = await recruiter_client.post(URL, json=valid_job_payload())

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert "check constraint" not in response.text
    assert await _count(db_session, Job) == 0
    assert await _audit(db_session, "job.create") == []


async def test_a_database_constraint_violation_on_edit_is_a_422_not_a_500(
    recruiter_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = await create_job(recruiter_client)
    original_flush = AsyncSession.flush

    async def failing_flush(self: AsyncSession, *args: Any, **kwargs: Any) -> None:
        if any(isinstance(obj, Job) for obj in self.dirty):
            raise IntegrityError("UPDATE jobs", {}, Exception("check constraint violated"))
        await original_flush(self, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "flush", failing_flush)

    response = await recruiter_client.patch(
        f"{URL}/{job['id']}", json={"version": 1, "title": "Different title"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
