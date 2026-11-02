"""Saved searches (user decisions 2026-11-02): every search by meaning is saved with its result,
each person sees only their own, the newest 50 un-starred are kept, and starred ones stay."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.db import get_sessionmaker
from app.features.semantic_search import history
from app.features.semantic_search.models import SavedSearch, SavedSearchMatch
from tests.integration import test_semantic_search as search_tests
from tests.integration.test_semantic_search import (
    QUERY,
    URL,
    ChatMock,
    _judge_everyone_the_same,
    _seed_embedded,
)

# The search tests' autouse fixtures (mocked OpenAI chat, empty caches) apply here too.
chat_mock = search_tests.chat_mock
empty_cache = search_tests.empty_cache

HISTORY = "/api/v1/semantic-search/history"


async def _search(client: AsyncClient, **params: Any) -> dict[str, Any]:
    response = await client.get(URL, params={"q": QUERY, **params})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_a_search_is_saved_and_reopens_without_an_ai_call(
    admin_client: AsyncClient, chat_mock: ChatMock
) -> None:
    ids = await _seed_embedded(3)

    def judge(profile: dict[str, Any]) -> dict[str, Any]:
        fits = "Specialist number 1" in profile["profile"]
        return {**_judge_everyone_the_same(profile), "skills_score": 90 if fits else 30}

    chat_mock.judge = judge
    searched = await _search(admin_client, country="IN")
    calls = len(chat_mock.payloads) + len(chat_mock.understanding_payloads)

    response = await admin_client.get(f"{HISTORY}/{searched['saved_search_id']}")

    assert response.status_code == 200, response.text
    saved = response.json()
    assert len(chat_mock.payloads) + len(chat_mock.understanding_payloads) == calls  # free
    assert (saved["query"], saved["filters"], saved["starred"]) == (QUERY, {"country": "IN"}, False)
    assert saved["result"] == searched  # the same order, verdicts and counts as shown
    assert saved["result"]["items"][0]["candidate"]["id"] == str(ids[1])


async def test_another_persons_saved_search_looks_missing(
    admin_client: AsyncClient, recruiter_client: AsyncClient
) -> None:
    await _seed_embedded(1)
    saved_id = (await _search(admin_client))["saved_search_id"]

    reads = [
        await recruiter_client.get(f"{HISTORY}/{saved_id}"),
        await recruiter_client.put(f"{HISTORY}/{saved_id}/star", json={"starred": True}),
        await recruiter_client.delete(f"{HISTORY}/{saved_id}"),
        await admin_client.get(f"{HISTORY}/{uuid.uuid4()}"),
    ]

    assert [r.status_code for r in reads] == [404] * 4
    assert {r.json()["error"]["code"] for r in reads} == {"saved_search_not_found"}
    assert (await recruiter_client.get(HISTORY)).json() == {"items": [], "next_cursor": None}
    assert (await admin_client.get(f"{HISTORY}/{saved_id}")).status_code == 200  # untouched


async def test_star_and_delete(admin_client: AsyncClient) -> None:
    await _seed_embedded(1)
    saved_id = (await _search(admin_client))["saved_search_id"]
    star = f"{HISTORY}/{saved_id}/star"

    assert (await admin_client.put(star, json={"starred": True})).status_code == 204
    [listed] = (await admin_client.get(HISTORY)).json()["items"]
    assert (listed["id"], listed["starred"], listed["result_count"]) == (saved_id, True, 1)
    assert (await admin_client.put(star, json={"starred": "yes"})).status_code == 422
    assert (await admin_client.put(star, json={"starred": True, "x": 1})).status_code == 422

    assert (await admin_client.delete(f"{HISTORY}/{saved_id}")).status_code == 204
    assert (await admin_client.get(f"{HISTORY}/{saved_id}")).status_code == 404


async def test_only_the_newest_unstarred_searches_are_kept(
    admin_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(history, "HISTORY_LIMIT", 2)
    await _seed_embedded(1)
    starred = (await _search(admin_client, country="IN"))["saved_search_id"]
    await admin_client.put(f"{HISTORY}/{starred}/star", json={"starred": True})
    oldest = (await _search(admin_client, source="manual"))["saved_search_id"]
    await _search(admin_client, city="Bengaluru")
    await _search(admin_client)

    kept = [item["id"] for item in (await admin_client.get(HISTORY)).json()["items"]]

    # The starred one stays however old it is; the oldest un-starred one went.
    assert len(kept) == 3
    assert starred in kept and oldest not in kept
    async with get_sessionmaker()() as session, session.begin():
        orphans = await session.scalar(
            select(func.count())
            .select_from(SavedSearchMatch)
            .where(SavedSearchMatch.saved_search_id == uuid.UUID(oldest))
        )
    assert orphans == 0


async def test_a_deleted_candidate_leaves_every_saved_search(admin_client: AsyncClient) -> None:
    ids = await _seed_embedded(2)
    saved_id = (await _search(admin_client))["saved_search_id"]

    assert (await admin_client.delete(f"/api/v1/admin/candidates/{ids[0]}")).status_code == 204
    saved = (await admin_client.get(f"{HISTORY}/{saved_id}")).json()

    assert [m["candidate"]["id"] for m in saved["result"]["items"]] == [str(ids[1])]
    async with get_sessionmaker()() as session, session.begin():
        notes = await session.scalar(
            select(func.count())
            .select_from(SavedSearchMatch)
            .where(SavedSearchMatch.candidate_id == ids[0])
        )
    assert notes == 0  # the AI's notes about them went too (RULES §10)


async def test_history_pages_newest_first(
    admin_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(history, "PAGE_SIZE", 1)
    await _seed_embedded(1)
    first = (await _search(admin_client, country="IN"))["saved_search_id"]
    second = (await _search(admin_client))["saved_search_id"]

    page_one = (await admin_client.get(HISTORY)).json()
    page_two = (await admin_client.get(HISTORY, params={"cursor": page_one["next_cursor"]})).json()

    assert [i["id"] for i in page_one["items"]] == [second]
    assert [i["id"] for i in page_two["items"]] == [first]
    assert page_two["next_cursor"] is None
    assert (await admin_client.get(HISTORY, params={"cursor": "nope"})).status_code == 400


async def test_the_saved_query_is_the_only_copy_of_the_text(admin_client: AsyncClient) -> None:
    await _seed_embedded(1)
    await _search(admin_client)

    async with get_sessionmaker()() as session, session.begin():
        [saved] = list(await session.scalars(select(SavedSearch)))
    assert saved.query == QUERY  # stored for its owner; audit rows still never carry it
