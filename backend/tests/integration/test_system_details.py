from decimal import Decimal

from httpx import AsyncClient

from app.core.db import get_sessionmaker
from app.core.embeddings import get_embedding_provider
from app.features.candidates import CandidateCreate, create_candidate
from app.features.candidates.models import Candidate
from app.features.candidates.tests.factories import valid_candidate_payload
from app.features.embeddings import CANDIDATES, embed_stale
from app.features.embeddings.models import EmbeddingFailure
from app.features.embeddings.service import hash_document
from tests.integration.conftest import FETCH_HEADERS

URL = "/api/v1/admin/system"


async def _seed(count: int) -> list[Candidate]:
    async with get_sessionmaker()() as session:
        created = [
            await create_candidate(
                session,
                CandidateCreate.model_validate(
                    valid_candidate_payload(
                        full_name=f"System Person{i}", email=f"system{i}@example.com"
                    )
                ),
                consent_version="test",
            )
            for i in range(count)
        ]
    async with get_sessionmaker()() as session:
        await embed_stale(session, get_embedding_provider(), CANDIDATES)
    async with get_sessionmaker()() as session, session.begin():
        return [await session.get_one(Candidate, c.id) for c in created]


async def test_counts_up_to_date_stale_and_failed_profiles(admin_client: AsyncClient) -> None:
    edited, failing, _ = await _seed(3)
    async with get_sessionmaker()() as session, session.begin():
        (await session.get_one(Candidate, edited.id)).search_document = "Edited since embedding."
        document = "Text that could not be embedded."
        (await session.get_one(Candidate, failing.id)).search_document = document
        session.add(
            EmbeddingFailure(
                candidate_id=failing.id,
                model="text-embedding-3-small",
                content_hash=hash_document(document),
                attempts=1,
                last_error="PermanentEmbeddingError status=400",
            )
        )

    response = await admin_client.get(URL)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["candidates"] == {"total": 3, "current": 1, "failed": 1}
    assert body["jobs"] == {"total": 0, "current": 0, "failed": 0}
    assert body["models"] == {
        "embedding_model": "text-embedding-3-small",
        "ranking_model": "gpt-5.4-mini",
        "ranking_prompt_version": "rank_v7",
        "understanding_prompt_version": "understand_v3",
    }
    assert Decimal(body["budget"]["limit_usd"]) == Decimal("5.00")
    assert body["budget"]["limit_reached"] is False
    # Counts only: no candidate names, emails or ids.
    assert "System Person" not in response.text
    assert "@example.com" not in response.text
    assert str(edited.id) not in response.text


async def test_recruiters_see_it_and_anonymous_users_do_not(
    client: AsyncClient, recruiter_client: AsyncClient
) -> None:
    assert (await recruiter_client.get(URL)).status_code == 200
    assert (await client.get(URL, headers=FETCH_HEADERS)).status_code == 401
