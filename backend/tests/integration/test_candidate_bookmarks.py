import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.db import get_sessionmaker
from app.features.audit.models import AuditEvent
from app.features.auth.service import create_user
from app.features.candidates import CandidateCreate, create_candidate
from app.features.candidates.models import CandidateBookmark
from app.features.candidates.tests.factories import valid_candidate_payload
from tests.integration.conftest import STAFF_PASSWORD, signed_in_client

URL = "/api/v1/admin/candidates"
BOOKMARKS = f"{URL}/bookmarks"


async def _seed(**overrides: Any) -> uuid.UUID:
    async with get_sessionmaker()() as session:
        created = await create_candidate(
            session,
            CandidateCreate.model_validate(valid_candidate_payload(**overrides)),
            consent_version="test",
        )
    return created.id


async def _named_staff(email: str, full_name: str) -> None:
    async with get_sessionmaker()() as session:
        await create_user(
            session, email=email, full_name=full_name, password=STAFF_PASSWORD, role="recruiter"
        )


async def _count(model: Any, *where: Any) -> int:
    async with get_sessionmaker()() as session:
        return await session.scalar(select(func.count()).select_from(model).where(*where)) or 0


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", BOOKMARKS),
        ("PUT", f"{URL}/{uuid.uuid4()}/bookmark"),
        ("DELETE", f"{URL}/{uuid.uuid4()}/bookmark"),
    ],
)
async def test_bookmarks_require_login(client: AsyncClient, method: str, path: str) -> None:
    response = await client.request(method, path, headers={"X-Requested-With": "fetch"})

    assert response.status_code == 401


async def test_recruiter_adds_lists_and_removes_a_bookmark(recruiter_client: AsyncClient) -> None:
    candidate_id = await _seed()

    assert (await recruiter_client.get(BOOKMARKS)).json() == {"items": []}
    assert (await recruiter_client.put(f"{URL}/{candidate_id}/bookmark")).status_code == 204

    items = (await recruiter_client.get(BOOKMARKS)).json()["items"]
    assert [item["candidate"]["id"] for item in items] == [str(candidate_id)]
    assert items[0]["candidate"]["full_name"] == "Asha Verma"

    assert (await recruiter_client.delete(f"{URL}/{candidate_id}/bookmark")).status_code == 204
    assert (await recruiter_client.get(BOOKMARKS)).json() == {"items": []}
    actions = await _count(
        AuditEvent, AuditEvent.action.in_(["candidate.bookmark", "candidate.unbookmark"])
    )
    assert actions == 2


async def test_the_list_is_shared_and_keeps_the_first_adder(app: FastAPI) -> None:
    candidate_id = await _seed()
    await _named_staff("priya@example.com", "Priya Shah")
    await _named_staff("omar@example.com", "Omar Ali")

    async with (
        signed_in_client(app, "priya@example.com") as priya,
        signed_in_client(app, "omar@example.com") as omar,
    ):
        assert (await priya.put(f"{URL}/{candidate_id}/bookmark")).status_code == 204
        # Starring again, by anyone, is a no-op.
        assert (await omar.put(f"{URL}/{candidate_id}/bookmark")).status_code == 204

        items = (await omar.get(BOOKMARKS)).json()["items"]
        assert [item["added_by_name"] for item in items] == ["Priya Shah"]
        assert await _count(CandidateBookmark) == 1

        # Anyone on the team can remove it; removing twice is fine.
        assert (await omar.delete(f"{URL}/{candidate_id}/bookmark")).status_code == 204
        assert (await omar.delete(f"{URL}/{candidate_id}/bookmark")).status_code == 204
        assert (await priya.get(BOOKMARKS)).json() == {"items": []}
        assert await _count(AuditEvent, AuditEvent.action == "candidate.unbookmark") == 1


async def test_bookmarking_an_unknown_candidate_is_404(admin_client: AsyncClient) -> None:
    response = await admin_client.put(f"{URL}/{uuid.uuid4()}/bookmark")

    assert response.status_code == 404
    assert await _count(CandidateBookmark) == 0


async def test_deleting_the_candidate_removes_the_bookmark(admin_client: AsyncClient) -> None:
    candidate_id = await _seed()
    await admin_client.put(f"{URL}/{candidate_id}/bookmark")

    assert (await admin_client.delete(f"{URL}/{candidate_id}")).status_code == 204

    assert (await admin_client.get(BOOKMARKS)).json() == {"items": []}
    assert await _count(CandidateBookmark) == 0


async def test_newest_bookmark_comes_first(admin_client: AsyncClient) -> None:
    first = await _seed()
    second = await _seed(email="ravi@example.com", full_name="Ravi Kumar")
    await admin_client.put(f"{URL}/{first}/bookmark")
    await admin_client.put(f"{URL}/{second}/bookmark")

    items = (await admin_client.get(BOOKMARKS)).json()["items"]

    assert [item["candidate"]["full_name"] for item in items] == ["Ravi Kumar", "Asha Verma"]
