import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.features.audit.models import AuditEvent
from app.features.candidates import CandidateCreate, create_candidate
from app.features.candidates.models import Candidate, CandidateExperience
from app.features.candidates.tests.factories import valid_candidate_payload

URL = "/api/v1/admin/candidates"


async def _seed(**overrides: Any) -> uuid.UUID:
    async with get_sessionmaker()() as session:
        created = await create_candidate(
            session,
            CandidateCreate.model_validate(valid_candidate_payload(**overrides)),
            consent_version="test",
        )
    return created.id


async def _seed_people() -> dict[str, uuid.UUID]:
    return {
        "asha": await _seed(),
        "ravi": await _seed(
            full_name="Ravi Kumar",
            email="ravi@example.com",
            city="Pune",
            skills=["Java", "Kafka"],
            years_experience=3,
            work_modes=["onsite"],
        ),
        "lena": await _seed(
            full_name="Lena Schmidt",
            email="lena@example.de",
            city="Berlin",
            country_code="DE",
            headline="Data Engineer",
            skills=["Python", "Spark"],
            years_experience=9,
        ),
    }


def _names(response_json: dict[str, Any]) -> list[str]:
    return [item["full_name"] for item in response_json["items"]]


def _update_body(detail: dict[str, Any], **changes: Any) -> dict[str, Any]:
    body = {
        key: detail[key]
        for key in (
            "full_name", "email", "phone", "city", "country_code", "linkedin_url",
            "github_url", "portfolio_url", "headline", "years_experience", "skills",
            "summary", "experiences", "educations", "desired_roles", "work_modes",
            "open_to_relocation", "notice_period_days", "version",
        )
    }  # fmt: skip
    body.update(changes)
    return body


# --- Access control ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", URL),
        ("GET", f"{URL}/{uuid.uuid4()}"),
        ("POST", URL),
        ("PUT", f"{URL}/{uuid.uuid4()}"),
        ("DELETE", f"{URL}/{uuid.uuid4()}"),
    ],
)
async def test_every_endpoint_requires_login(client: AsyncClient, method: str, path: str) -> None:
    response = await client.request(method, path, headers={"X-Requested-With": "fetch"}, json={})

    assert response.status_code == 401


async def test_state_changes_require_csrf_header(admin_client: AsyncClient) -> None:
    candidate_id = await _seed()

    response = await admin_client.delete(f"{URL}/{candidate_id}", headers={"X-Requested-With": ""})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"


# --- Search -----------------------------------------------------------------------------


async def test_filters(admin_client: AsyncClient) -> None:
    await _seed_people()

    async def names(**params: Any) -> list[str]:
        return sorted(_names((await admin_client.get(URL, params=params)).json()))

    assert await names(country="de") == ["Lena Schmidt"]
    assert await names(min_years=5) == ["Asha Verma", "Lena Schmidt"]
    assert await names(skill="  JAVA ") == ["Ravi Kumar"]
    # Comma-separated skills: a candidate needs every one.
    assert await names(skill="Python") == ["Asha Verma", "Lena Schmidt"]
    assert await names(skill="python, Spark") == ["Lena Schmidt"]
    assert await names(city=" berlin ") == ["Lena Schmidt"]
    assert await names(city="Ber") == []  # the whole city, not part of it
    assert await names(source="manual") == ["Asha Verma", "Lena Schmidt", "Ravi Kumar"]
    assert await names(source="github") == []


async def test_summary_rows_contain_only_listed_fields(admin_client: AsyncClient) -> None:
    await _seed()

    item = (await admin_client.get(URL)).json()["items"][0]

    assert set(item) == {
        "id", "full_name", "email", "headline", "city", "country_code",
        "years_experience", "top_skills", "expected_salary", "salary_currency", "source",
        "created_at",
    }  # fmt: skip
    assert item["years_experience"] == 6.5


async def test_pagination_has_no_gaps_or_duplicates(admin_client: AsyncClient) -> None:
    for i in range(7):
        await _seed(full_name=f"Person {i % 3}", email=f"p{i}@example.com", years_experience=i % 2)

    seen: list[str] = []
    cursor = None
    while True:
        params: dict[str, Any] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = (await admin_client.get(URL, params=params)).json()
        seen += [item["id"] for item in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break

    assert len(seen) == len(set(seen)) == 7


async def test_invalid_cursor_is_400(admin_client: AsyncClient) -> None:
    for cursor in ("not-a-cursor", "eyJzb3J0IjoibmFtZSJ9"):
        response = await admin_client.get(URL, params={"cursor": cursor})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_cursor"


async def test_page_size_is_capped(admin_client: AsyncClient) -> None:
    assert (await admin_client.get(URL, params={"limit": 101})).status_code == 422


async def test_unknown_query_params_rejected(admin_client: AsyncClient) -> None:
    assert (await admin_client.get(URL, params={"bogus": "1"})).status_code == 422


# --- Detail / create / update / delete -------------------------------------------------


async def test_view_returns_full_profile_and_is_audited(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    candidate_id = await _seed()

    response = await admin_client.get(f"{URL}/{candidate_id}")

    assert response.status_code == 200
    detail = response.json()
    assert detail["version"] == 1
    assert detail["experiences"][0]["start_month"] == "2021-03"
    assert detail["experiences"][1]["end_month"] == "2021-02"
    views = await db_session.scalar(
        select(func.count()).where(
            AuditEvent.action == "candidate.view", AuditEvent.entity_id == candidate_id
        )
    )
    assert views == 1


async def test_view_unknown_candidate_is_404(admin_client: AsyncClient) -> None:
    assert (await admin_client.get(f"{URL}/{uuid.uuid4()}")).status_code == 404


async def test_staff_create_records_source_and_consent_actor(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    payload = valid_candidate_payload()
    del payload["consent"]

    response = await admin_client.post(URL, json={**payload, "consent_confirmed": True})

    assert response.status_code == 201
    assert response.json()["source"] == "admin"
    candidate = await db_session.scalar(select(Candidate))
    assert candidate is not None
    assert candidate.consent_recorded_by is not None


async def test_staff_create_requires_consent_confirmation(admin_client: AsyncClient) -> None:
    payload = valid_candidate_payload()
    del payload["consent"]

    response = await admin_client.post(URL, json={**payload, "consent_confirmed": False})

    assert response.status_code == 422


async def test_staff_create_duplicate_email_is_409(admin_client: AsyncClient) -> None:
    await _seed()
    payload = valid_candidate_payload(email="ASHA.VERMA@example.com")
    del payload["consent"]

    response = await admin_client.post(URL, json={**payload, "consent_confirmed": True})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "candidate_exists"


async def test_update_replaces_profile_and_bumps_version(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    candidate_id = await _seed()
    detail = (await admin_client.get(f"{URL}/{candidate_id}")).json()
    new_experience = {
        "company": "Initech",
        "title": "Staff Engineer",
        "start_month": "2022-01",
        "is_current": True,
        "end_month": None,
        "description": None,
    }

    response = await admin_client.put(
        f"{URL}/{candidate_id}",
        json=_update_body(detail, headline="Staff Engineer", experiences=[new_experience]),
    )

    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["version"] == 2
    assert updated["headline"] == "Staff Engineer"
    assert [e["company"] for e in updated["experiences"]] == ["Initech"]
    candidate = await db_session.scalar(select(Candidate))
    assert candidate is not None
    assert "Staff Engineer." in candidate.search_document
    assert await db_session.scalar(select(func.count()).select_from(CandidateExperience)) == 1


async def test_update_audit_lists_field_names_only(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    candidate_id = await _seed()
    detail = (await admin_client.get(f"{URL}/{candidate_id}")).json()

    await admin_client.put(
        f"{URL}/{candidate_id}", json=_update_body(detail, city="Mysuru", phone="+911234567890")
    )

    details = await db_session.scalar(
        select(AuditEvent.details).where(AuditEvent.action == "candidate.update")
    )
    assert details == {"changed_fields": ["phone", "city"]}


async def test_update_audit_names_an_edited_work_history(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    candidate_id = await _seed()
    detail = (await admin_client.get(f"{URL}/{candidate_id}")).json()
    experiences = [{**detail["experiences"][0], "description": "Rewrote the billing service."}]

    response = await admin_client.put(
        f"{URL}/{candidate_id}", json=_update_body(detail, experiences=experiences)
    )

    assert response.status_code == 200, response.text
    details = await db_session.scalar(
        select(AuditEvent.details).where(AuditEvent.action == "candidate.update")
    )
    assert details == {"changed_fields": ["experiences"]}


async def test_stale_version_is_rejected_without_changes(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    candidate_id = await _seed()
    detail = (await admin_client.get(f"{URL}/{candidate_id}")).json()
    first = await admin_client.put(f"{URL}/{candidate_id}", json=_update_body(detail, city="Pune"))
    assert first.status_code == 200

    second = await admin_client.put(
        f"{URL}/{candidate_id}", json=_update_body(detail, city="Chennai")
    )

    assert second.status_code == 409
    assert second.json()["error"]["code"] == "version_conflict"
    assert await db_session.scalar(select(Candidate.city)) == "Pune"


async def test_update_to_existing_email_is_409(admin_client: AsyncClient) -> None:
    people = await _seed_people()
    detail = (await admin_client.get(f"{URL}/{people['ravi']}")).json()

    response = await admin_client.put(
        f"{URL}/{people['ravi']}", json=_update_body(detail, email="asha.verma@example.com")
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "candidate_exists"


async def test_update_validates_like_the_public_form(admin_client: AsyncClient) -> None:
    candidate_id = await _seed()
    detail = (await admin_client.get(f"{URL}/{candidate_id}")).json()

    response = await admin_client.put(
        f"{URL}/{candidate_id}", json=_update_body(detail, skills=[], linkedin_url="bad")
    )

    assert response.status_code == 422
    locs = [e["loc"] for e in response.json()["error"]["details"]["errors"]]
    assert ["body", "skills"] in locs
    assert ["body", "linkedin_url"] in locs


async def test_admin_delete_removes_everything_and_keeps_pii_free_audit(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    candidate_id = await _seed()

    response = await admin_client.delete(f"{URL}/{candidate_id}")

    assert response.status_code == 204
    assert await db_session.scalar(select(func.count()).select_from(Candidate)) == 0
    assert await db_session.scalar(select(func.count()).select_from(CandidateExperience)) == 0
    assert (await admin_client.get(f"{URL}/{candidate_id}")).status_code == 404
    event = await db_session.scalar(
        select(AuditEvent).where(AuditEvent.action == "candidate.delete")
    )
    assert event is not None
    assert event.entity_id == candidate_id
    assert event.details == {}


async def test_delete_unknown_candidate_is_404(admin_client: AsyncClient) -> None:
    assert (await admin_client.delete(f"{URL}/{uuid.uuid4()}")).status_code == 404


async def test_recruiter_can_edit_but_not_delete(
    recruiter_client: AsyncClient, db_session: AsyncSession
) -> None:
    candidate_id = await _seed()
    detail = (await recruiter_client.get(f"{URL}/{candidate_id}")).json()

    edit = await recruiter_client.put(
        f"{URL}/{candidate_id}", json=_update_body(detail, city="Pune")
    )
    delete = await recruiter_client.delete(f"{URL}/{candidate_id}")

    assert edit.status_code == 200
    assert delete.status_code == 403
    assert await db_session.scalar(select(func.count()).select_from(Candidate)) == 1
