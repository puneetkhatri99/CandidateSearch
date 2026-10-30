from datetime import date
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.features.candidates import service
from app.features.candidates.models import Candidate, CandidateEducation, CandidateExperience
from app.features.candidates.schemas import CandidateCreate, ExperienceIn
from app.features.candidates.tests.factories import valid_candidate_payload

URL = "/api/v1/candidates"


async def _count(session: AsyncSession, model: Any) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def test_create_candidate_saves_profile(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    response = await client.post(URL, json=valid_candidate_payload())

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "created_at"}

    candidate = await db_session.scalar(
        select(Candidate)
        .options(selectinload(Candidate.experiences), selectinload(Candidate.educations))
        .where(Candidate.id == body["id"])
    )
    assert candidate is not None
    assert candidate.email == "asha.verma@example.com"
    assert candidate.skills == ["python", "fastapi", "postgresql"]
    assert candidate.source == "manual"
    assert candidate.consent_version == get_settings().privacy_notice_version
    assert candidate.consent_given_at is not None
    assert "asha" not in candidate.search_document.lower()
    assert [e.company for e in candidate.experiences] == ["Acme Payments", "Globex"]
    assert candidate.experiences[0].end_month is None
    assert candidate.experiences[1].end_month == date(2021, 2, 1)
    assert [e.institution for e in candidate.educations] == ["IIT Delhi"]


async def test_duplicate_email_any_case_returns_409(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await client.post(URL, json=valid_candidate_payload())

    response = await client.post(URL, json=valid_candidate_payload(email="ASHA.Verma@example.com"))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "candidate_exists"
    assert await _count(db_session, Candidate) == 1
    assert await _count(db_session, CandidateExperience) == 2


async def test_invalid_payload_returns_field_errors(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    response = await client.post(URL, json=valid_candidate_payload(email="nope", consent=False))

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    locs = [e["loc"] for e in error["details"]["errors"]]
    assert ["body", "email"] in locs
    assert ["body", "consent"] in locs
    assert all(set(e) == {"loc", "msg", "type"} for e in error["details"]["errors"])
    assert await _count(db_session, Candidate) == 0


async def test_honeypot_pretends_success_but_saves_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    response = await client.post(URL, json=valid_candidate_payload(website="http://spam.example"))

    assert response.status_code == 201
    assert await _count(db_session, Candidate) == 0


async def test_rate_limit_blocks_after_limit(app: FastAPI, client: AsyncClient) -> None:
    limit = get_settings().candidate_submit_limit
    for i in range(limit):
        ok = await client.post(URL, json=valid_candidate_payload(email=f"user{i}@example.com"))
        assert ok.status_code == 201

    response = await client.post(URL, json=valid_candidate_payload(email="extra@example.com"))

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert int(response.headers["Retry-After"]) > 0


async def test_oversized_body_rejected(client: AsyncClient, db_session: AsyncSession) -> None:
    response = await client.post(URL, json=valid_candidate_payload(summary="x" * 70_000))

    assert response.status_code == 413
    assert await _count(db_session, Candidate) == 0


async def test_failed_child_insert_rolls_back_candidate(db_session: AsyncSession) -> None:
    # Bypass schema validation to force a DB check-constraint failure on an experience row.
    bad_experience = ExperienceIn.model_construct(
        company="A",
        title="T",
        start_month=date(2020, 5, 1),
        end_month=date(2020, 1, 1),
        is_current=False,
        description=None,
    )
    valid = CandidateCreate.model_validate(valid_candidate_payload())
    data = valid.model_copy(update={"experiences": [bad_experience]})

    with pytest.raises(IntegrityError):
        await service.create_candidate(db_session, data, consent_version="test")

    assert await _count(db_session, Candidate) == 0
    assert await _count(db_session, CandidateEducation) == 0
