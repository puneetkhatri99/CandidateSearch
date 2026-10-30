"""Integration tests run against a real PostgreSQL test database, migrated with Alembic."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import Base, get_engine, get_sessionmaker
from app.features.auth import Role, StaffUser, create_user
from app.features.jobs.tests.factories import valid_job_payload

BACKEND_DIR = Path(__file__).resolve().parents[2]


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def migrated_database() -> None:
    # Running real migrations (not create_all) also tests the migrations themselves.
    command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")


@pytest.fixture(autouse=True)
async def clean_database(migrated_database: None) -> AsyncIterator[None]:
    engine = get_engine()
    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield
    # Each test gets its own event loop; pooled connections must not outlive it.
    await engine.dispose()


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


# --- Staff sessions ---------------------------------------------------------------------

STAFF_PASSWORD = "correct-horse-battery"
FETCH_HEADERS = {"X-Requested-With": "fetch"}


async def create_staff(email: str, role: Role = "admin") -> StaffUser:
    async with get_sessionmaker()() as session:
        return await create_user(
            session, email=email, full_name="Staff Member", password=STAFF_PASSWORD, role=role
        )


async def login(client: AsyncClient, email: str) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": STAFF_PASSWORD},
        headers=FETCH_HEADERS,
    )
    assert response.status_code == 200, response.text
    client.headers.update(FETCH_HEADERS)


@asynccontextmanager
async def signed_in_client(app: FastAPI, email: str) -> AsyncIterator[AsyncClient]:
    """A separate cookie jar signed in as an existing staff user (a second browser)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other:
        await login(other, email)
        yield other


async def create_job(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    response = await client.post("/api/v1/jobs", json=valid_job_payload(**overrides))
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


@pytest.fixture
async def admin_client(client: AsyncClient) -> AsyncClient:
    await create_staff("admin@example.com", "admin")
    await login(client, "admin@example.com")
    return client


@pytest.fixture
async def recruiter_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    await create_staff("recruiter@example.com", "recruiter")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await login(client, "recruiter@example.com")
        yield client
