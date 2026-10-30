"""Phase 2c item 6: every candidate search page is audited, without the search text."""

import json
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.features.audit.models import AuditEvent
from app.features.candidates import CandidateCreate, create_candidate
from app.features.candidates.tests.factories import valid_candidate_payload

URL = "/api/v1/admin/candidates"
MARKER = "zzqmarker"


async def _seed(count: int) -> None:
    for i in range(count):
        payload = valid_candidate_payload(
            full_name=f"Person Number{i}",
            email=f"person{i}@example.com",
            headline=f"{MARKER} backend engineer {i}",
        )
        async with get_sessionmaker()() as session:
            await create_candidate(
                session, CandidateCreate.model_validate(payload), consent_version="test"
            )


async def _search_events() -> list[AuditEvent]:
    async with get_sessionmaker()() as session:
        result = await session.scalars(
            select(AuditEvent)
            .where(AuditEvent.action == "candidate.search")
            .order_by(AuditEvent.created_at)
        )
        return list(result.all())


async def test_each_page_writes_one_event_with_filter_names_only(admin_client: AsyncClient) -> None:
    await _seed(3)

    first = await admin_client.get(URL, params={"city": "Bengaluru", "limit": 2})
    assert first.status_code == 200
    second = await admin_client.get(
        URL, params={"city": "Bengaluru", "limit": 2, "cursor": first.json()["next_cursor"]}
    )
    assert second.status_code == 200

    events = await _search_events()
    assert [e.details for e in events] == [
        {"filters": ["city"], "cursor_page": False, "limit": 2, "result_count": 2},
        {"filters": ["city"], "cursor_page": True, "limit": 2, "result_count": 1},
    ]
    assert all(e.entity_id is None and e.actor_user_id is not None for e in events)
    assert all(e.ip for e in events)


async def test_details_never_contain_query_text_or_filter_values(admin_client: AsyncClient) -> None:
    await _seed(1)

    response = await admin_client.get(
        URL, params={"city": MARKER, "skill": "rarebird-skill", "source": "manual"}
    )
    assert response.status_code == 200

    [event] = await _search_events()
    assert event.details["filters"] == ["city", "skill", "source"]
    text = json.dumps(event.details)
    assert MARKER not in text
    assert "rarebird" not in text
    assert "manual" not in text


async def test_a_search_without_filters_records_an_empty_filter_list(
    admin_client: AsyncClient,
) -> None:
    await admin_client.get(URL)
    [event] = await _search_events()
    details: dict[str, Any] = event.details
    assert details["filters"] == []
    assert details["result_count"] == 0


async def test_a_bad_cursor_and_an_unauthenticated_search_write_nothing(
    admin_client: AsyncClient, client: AsyncClient
) -> None:
    assert (await admin_client.get(URL, params={"cursor": "not-a-cursor"})).status_code == 400
    admin_client.cookies.clear()
    assert (await client.get(URL)).status_code == 401
    assert await _search_events() == []


async def test_recruiter_searches_are_audited_as_the_recruiter(
    recruiter_client: AsyncClient,
) -> None:
    assert (await recruiter_client.get(URL)).status_code == 200
    [event] = await _search_events()
    assert event.actor_user_id is not None
