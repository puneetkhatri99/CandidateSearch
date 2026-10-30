"""Edge cases for POST /api/v1/candidates found during Phase 1 QA.

Tests marked xfail(strict=True) document open bugs: they fail today and will turn into
an XPASS (which fails the suite) once the bug is fixed, so remove the marker then.
"""

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.features.candidates.models import Candidate
from app.features.candidates.tests.factories import valid_candidate_payload

URL = "/api/v1/candidates"


async def _count(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count()).select_from(Candidate)) or 0)


def _error_locs(body: dict[str, Any]) -> list[list[str | int]]:
    return [e["loc"] for e in body["error"]["details"]["errors"]]


async def test_malformed_json_returns_standard_422(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    response = await client.post(
        URL, content=b"{not json", headers={"content-type": "application/json"}
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"]["errors"][0]["type"] == "json_invalid"
    assert await _count(db_session) == 0


async def test_wrong_types_report_each_field(client: AsyncClient) -> None:
    payload = valid_candidate_payload(
        years_experience="abc", skills="python", work_modes="remote", experiences={}
    )

    response = await client.post(URL, json=payload)

    assert response.status_code == 422
    locs = _error_locs(response.json())
    for field in ("years_experience", "skills", "work_modes", "experiences"):
        assert ["body", field] in locs


async def test_unknown_nested_field_rejected(client: AsyncClient) -> None:
    experience = {"company": "A", "title": "T", "start_month": "2020-01", "is_current": True}
    payload = valid_candidate_payload(experiences=[{**experience, "salary": 1}])

    response = await client.post(URL, json=payload)

    assert response.status_code == 422
    assert ["body", "experiences", 0, "salary"] in _error_locs(response.json())


async def test_validation_errors_do_not_echo_input(client: AsyncClient) -> None:
    submitted = "do-not-echo-this-value"
    response = await client.post(URL, json=valid_candidate_payload(phone=submitted))

    assert response.status_code == 422
    assert submitted not in response.text


async def test_email_trimmed_and_lowercased_and_dedupe_uses_normalized_value(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    first = await client.post(URL, json=valid_candidate_payload(email="  Mixed.Case@Example.COM "))
    second = await client.post(URL, json=valid_candidate_payload(email="MIXED.case@example.com"))

    assert first.status_code == 201
    assert second.status_code == 409
    stored = await db_session.scalar(select(Candidate.email))
    assert stored == "mixed.case@example.com"
    assert await _count(db_session) == 1


async def test_unicode_name_and_city_round_trip(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    response = await client.post(
        URL, json=valid_candidate_payload(full_name="José Ñúñez 李小龍", city="São Paulo")
    )

    assert response.status_code == 201
    candidate = await db_session.scalar(select(Candidate))
    assert candidate is not None
    assert candidate.full_name == "José Ñúñez 李小龍"
    assert candidate.city == "São Paulo"
    assert "josé" not in candidate.search_document.lower()


async def test_skills_stored_trimmed_lowercased_and_deduplicated(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    skills = ["  Machine   Learning ", "machine learning", "MACHINE\tLEARNING", "C++", "", "  "]

    response = await client.post(URL, json=valid_candidate_payload(skills=skills))

    assert response.status_code == 201
    assert await db_session.scalar(select(Candidate.skills)) == ["machine learning", "c++"]


async def test_honeypot_submission_still_counts_toward_rate_limit(client: AsyncClient) -> None:
    limit = get_settings().candidate_submit_limit
    for _ in range(limit):
        bot = await client.post(URL, json=valid_candidate_payload(website="spam"))
        assert bot.status_code == 201

    response = await client.post(URL, json=valid_candidate_payload())

    assert response.status_code == 429


async def test_rate_limited_request_saves_nothing_and_retry_after_is_within_window(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    settings = get_settings()
    for i in range(settings.candidate_submit_limit):
        await client.post(URL, json=valid_candidate_payload(email=f"rl{i}@example.com"))

    response = await client.post(URL, json=valid_candidate_payload(email="late@example.com"))

    assert response.status_code == 429
    retry_after = int(response.headers["Retry-After"])
    assert 0 < retry_after <= settings.candidate_submit_window_seconds
    assert await _count(db_session) == settings.candidate_submit_limit


async def test_chunked_oversized_body_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    body = valid_candidate_payload(summary="y" * 70_000)

    async def chunks() -> AsyncIterator[bytes]:
        # A generator body makes httpx send it chunked, without a Content-Length header.
        yield json.dumps(body).encode()

    response = await client.post(
        URL, content=chunks(), headers={"content-type": "application/json"}
    )

    assert response.status_code == 413
    assert await _count(db_session) == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"full_name": "Asha\u0000Verma"},
        {"summary": "x" * 60 + "\u0000"},
        {"skills": ["py\u0000thon"]},
    ],
    ids=["full_name", "summary", "skills"],
)
async def test_nul_character_is_a_validation_error_not_500(
    client: AsyncClient, overrides: dict[str, Any]
) -> None:
    response = await client.post(URL, json=valid_candidate_payload(**overrides))

    assert response.status_code == 422


async def test_oversized_malformed_body_returns_413(client: AsyncClient) -> None:
    response = await client.post(
        URL, content=b"x" * 100_000, headers={"content-type": "application/json"}
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


async def test_chunked_malformed_body_returns_413_with_standard_code(client: AsyncClient) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(13):
            yield b"x" * 8192

    response = await client.post(
        URL, content=chunks(), headers={"content-type": "application/json"}
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


@pytest.mark.parametrize(
    "overrides",
    [
        {"experiences": [{"company": "Ac\u0000me", "title": "T", "start_month": "2020-01"}]},
        {"educations": [{"institution": "I\u0000T"}]},
        {"desired_roles": ["x\u0000"]},
        {"email": "a\u0000b@example.com"},
    ],
    ids=["experience", "education", "desired_roles", "email"],
)
async def test_nul_character_in_nested_and_list_fields_is_422(
    client: AsyncClient, db_session: AsyncSession, overrides: dict[str, Any]
) -> None:
    response = await client.post(URL, json=valid_candidate_payload(**overrides))

    assert response.status_code == 422
    assert await _count(db_session) == 0
