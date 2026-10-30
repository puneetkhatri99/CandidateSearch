"""Hostile and unusual input for the jobs API."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.pagination import encode_cursor
from app.features.jobs.tests.factories import valid_job_payload
from tests.integration.conftest import create_job

URL = "/api/v1/jobs"


async def test_anonymous_requests_get_401(client: AsyncClient) -> None:
    assert (await client.get(URL)).status_code == 401
    assert (await client.get(f"{URL}/{uuid.uuid4()}")).status_code == 401


@pytest.mark.parametrize("field", ["title", "department", "city", "description"])
async def test_nul_characters_in_a_create_body_are_422_not_500(
    recruiter_client: AsyncClient, field: str
) -> None:
    value = "ab\x00cd" + ("x" * 120 if field == "description" else "")

    response = await recruiter_client.post(URL, json=valid_job_payload(**{field: value}))

    assert response.status_code == 422


async def test_nul_in_a_patch_is_422_not_500(recruiter_client: AsyncClient) -> None:
    job = await create_job(recruiter_client)

    response = await recruiter_client.patch(
        f"{URL}/{job['id']}", json={"version": 1, "title": "bad\x00title"}
    )

    assert response.status_code == 422


async def test_unknown_fields_are_422(recruiter_client: AsyncClient) -> None:
    response = await recruiter_client.post(URL, json=valid_job_payload(salary=100_000))
    job = await create_job(recruiter_client)
    patch = await recruiter_client.patch(f"{URL}/{job['id']}", json={"version": 1, "owner": "x"})

    assert (response.status_code, patch.status_code) == (422, 422)


async def test_a_patch_without_a_version_is_422(recruiter_client: AsyncClient) -> None:
    job = await create_job(recruiter_client)

    response = await recruiter_client.patch(f"{URL}/{job['id']}", json={"title": "No version"})

    assert response.status_code == 422


async def test_oversized_bodies_are_413(recruiter_client: AsyncClient) -> None:
    response = await recruiter_client.post(URL, json=valid_job_payload(description="x" * 70_000))

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


async def test_unknown_jobs_are_404_and_malformed_ids_are_422(
    recruiter_client: AsyncClient,
) -> None:
    missing = uuid.uuid4()

    get = await recruiter_client.get(f"{URL}/{missing}")
    patch = await recruiter_client.patch(f"{URL}/{missing}", json={"version": 1, "title": "x"})

    assert (get.status_code, patch.status_code) == (404, 404)
    assert get.json()["error"]["code"] == "not_found"
    assert (await recruiter_client.get(f"{URL}/not-a-uuid")).status_code == 422
    assert (
        await recruiter_client.patch(f"{URL}/not-a-uuid", json={"version": 1})
    ).status_code == 422


@pytest.mark.parametrize(
    "cursor",
    [
        "garbage",
        encode_cursor({"key": "2026-10-29T12:00:00", "id": str(uuid.uuid4())}),
        encode_cursor({"key": "2026-10-29T12:00:00+00:00", "id": "nope"}),
        encode_cursor({"key": "2026-10-29T12:00:00+00:00", "id": str(uuid.uuid4()) + "\x00"}),
        encode_cursor({"key": 5, "id": 6}),
        encode_cursor({"key": "0001-01-01T00:00:00+00:00", "id": str(uuid.uuid4())}),
        encode_cursor({}),
    ],
)
async def test_tampered_cursors_are_400(recruiter_client: AsyncClient, cursor: str) -> None:
    response = await recruiter_client.get(URL, params={"cursor": cursor})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_cursor"


@pytest.mark.parametrize(
    "overrides",
    [
        {"min_years": True, "max_years": None},
        {"must_have_skills": "python"},
        {"nice_to_have_skills": None},
        {"work_mode": "Remote"},
        {"description": "short"},
        {"country_code": "ZZ"},
    ],
)
async def test_invalid_values_are_422(
    recruiter_client: AsyncClient, overrides: dict[str, Any]
) -> None:
    response = await recruiter_client.post(URL, json=valid_job_payload(**overrides))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_html_in_a_description_is_stored_as_plain_text(
    recruiter_client: AsyncClient,
) -> None:
    description = "<script>alert(1)</script> " + "Build things. " * 10

    job = await create_job(recruiter_client, description=description)

    assert job["description"].startswith("<script>alert(1)</script>")
