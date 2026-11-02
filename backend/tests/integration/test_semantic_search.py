import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import httpx2
import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError

from app.core.db import get_sessionmaker
from app.core.embeddings import get_embedding_provider
from app.core.llm import OpenAIChatClient, use_llm_client
from app.features.ai_usage.models import AiBudget, AiUsageEvent
from app.features.audit.models import AuditEvent
from app.features.candidates import (
    CandidateCreate,
    candidate_ids_passing,
    create_candidate,
    full_text_candidate_ids,
    get_rankable_candidates,
    rebuild_search_documents,
)
from app.features.candidates import repository as candidates_repository
from app.features.candidates.models import Candidate
from app.features.candidates.tests.factories import valid_candidate_payload
from app.features.embeddings import CANDIDATES, JOBS, embed_stale
from app.features.embeddings.repository import nearest_neighbours
from app.features.semantic_search import ranking, service, understanding
from app.features.semantic_search.schemas import HardFilters
from app.shared.validation import split_tags
from tests.integration.conftest import FETCH_HEADERS, create_job
from tests.openai_mock import OpenAIEmbeddingsMock

URL = "/api/v1/semantic-search/candidates"
QUERY = "senior backend engineer payments"

type Judge = Callable[[dict[str, Any]], dict[str, Any]]


def _judge_everyone_the_same(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate": profile["candidate"],
        "skills_score": 70,
        "skills_note": "Python, FastAPI",
        "location": "not_required",
        "location_note": "No place named",
        "experience_score": 70,
        "experience_note": "6 years backend",
        "salary": "not_required",
        "salary_note": "No pay stated",
    }


@dataclass
class ChatMock:
    """Answers /v1/chat/completions like the models would: rankings from `judge`, and the facts
    of a search from `facts`. `payloads` and `statuses` are about the ranking calls only."""

    judge: Judge = _judge_everyone_the_same
    payloads: list[dict[str, Any]] = field(default_factory=list)
    statuses: list[int] = field(default_factory=list)
    # Set to answer with a refusal instead of judgements (still billed by OpenAI).
    refusal: str | None = None
    facts: dict[str, Any] = field(
        default_factory=lambda: {"city": None, "country_code": None, "min_years": None}
    )
    understanding_payloads: list[dict[str, Any]] = field(default_factory=list)
    understanding_statuses: list[int] = field(default_factory=list)
    understanding_delay_seconds: float = 0.0

    @staticmethod
    def profiles(payload: dict[str, Any]) -> list[dict[str, Any]]:
        content: str = payload["messages"][1]["content"]
        parsed: list[dict[str, Any]] = json.loads(content.split("Candidates:\n", 1)[1])
        return parsed

    async def handler(self, request: httpx2.Request) -> httpx2.Response:
        payload = json.loads(request.content)
        ranking_call = "Candidates:\n" in payload["messages"][1]["content"]
        (self.payloads if ranking_call else self.understanding_payloads).append(payload)
        statuses = self.statuses if ranking_call else self.understanding_statuses
        if statuses:
            body = {"error": {"message": "mocked failure", "type": "mock_error", "code": None}}
            return httpx2.Response(statuses.pop(0), json=body)
        answer: dict[str, Any]
        if ranking_call:
            judgements = [self.judge(p) for p in self.profiles(payload)]
            answer = {
                "search_names_place": any(j["location"] != "not_required" for j in judgements),
                "search_states_pay": any(j["salary"] != "not_required" for j in judgements),
                "search_wants_junior": False,
                "judgements": judgements,
            }
        else:
            await asyncio.sleep(self.understanding_delay_seconds)
            answer = self.facts
        refusal = self.refusal if ranking_call else None
        if payload.get("stream"):
            return self._streamed(
                payload["model"], None if refusal else json.dumps(answer), refusal
            )
        return httpx2.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 0,
                "model": payload["model"],
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": None if refusal else json.dumps(answer),
                            "refusal": refusal,
                        },
                    }
                ],
                "usage": {"prompt_tokens": 1200, "completion_tokens": 300, "total_tokens": 1500},
            },
        )

    @staticmethod
    def _streamed(model: str, content: str | None, refusal: str | None) -> httpx2.Response:
        """The same answer as server-sent chunks, in small pieces, then the usage chunk."""

        def chunk(delta: dict[str, Any], finish: str | None = None) -> dict[str, Any]:
            choice = {"index": 0, "delta": delta, "finish_reason": finish}
            return {"id": "chatcmpl-test", "object": "chat.completion.chunk", "created": 0,
                    "model": model, "choices": [choice]}  # fmt: skip

        text = content if content is not None else refusal or ""
        field_name = "content" if content is not None else "refusal"
        chunks = [chunk({"role": "assistant", field_name: ""})]
        chunks += [chunk({field_name: text[i : i + 40]}) for i in range(0, len(text), 40)]
        chunks.append(chunk({}, "stop"))
        usage = {"prompt_tokens": 1200, "completion_tokens": 300, "total_tokens": 1500}
        chunks.append({"id": "chatcmpl-test", "object": "chat.completion.chunk", "created": 0,
                       "model": model, "choices": [], "usage": usage})  # fmt: skip
        body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
        return httpx2.Response(200, text=body, headers={"content-type": "text/event-stream"})


@pytest.fixture(autouse=True)
def empty_cache() -> Iterator[None]:
    ranking.clear_ranking_cache()
    understanding.clear_understanding_cache()
    yield
    ranking.clear_ranking_cache()
    understanding.clear_understanding_cache()


@pytest.fixture(autouse=True)
async def chat_mock() -> AsyncIterator[ChatMock]:
    mock = ChatMock()
    http_client = httpx2.AsyncClient(transport=httpx2.MockTransport(mock.handler))
    client = OpenAIChatClient(api_key="sk-test-dummy", http_client=http_client)
    use_llm_client(client)
    yield mock
    use_llm_client(None)
    await client.aclose()


async def _seed_embedded(count: int, **overrides: Any) -> list[uuid.UUID]:
    ids = []
    async with get_sessionmaker()() as session:
        for i in range(count):
            payload = valid_candidate_payload(
                full_name=f"Semantic Person{i}",
                email=f"semantic{i}@example.com",
                headline=f"Specialist number {i}",
                summary=f"Works on problem area {i} with a distinct focus on topic {i * 11}.",
                **overrides,
            )
            created = await create_candidate(
                session, CandidateCreate.model_validate(payload), consent_version="test"
            )
            ids.append(created.id)
    async with get_sessionmaker()() as session:
        await embed_stale(session, get_embedding_provider(), CANDIDATES)
    return ids


async def _set_limit(limit: str) -> None:
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(delete(AiBudget))
        session.add(AiBudget(limit_usd=Decimal(limit)))


async def _events(operation: str) -> list[AiUsageEvent]:
    async with get_sessionmaker()() as session, session.begin():
        result = await session.scalars(
            select(AiUsageEvent).where(AiUsageEvent.operation == operation)
        )
        return list(result)


async def _search_audits() -> list[AuditEvent]:
    async with get_sessionmaker()() as session, session.begin():
        result = await session.scalars(
            select(AuditEvent).where(AuditEvent.action == "candidate.search")
        )
        return list(result)


async def test_the_llm_judgements_decide_the_order(
    admin_client: AsyncClient, chat_mock: ChatMock
) -> None:
    ids = await _seed_embedded(3)

    def judge(profile: dict[str, Any]) -> dict[str, Any]:
        fits = "Specialist number 2" in profile["profile"]
        return {
            **_judge_everyone_the_same(profile),
            "skills_score": 90 if fits else 30,
            "location": "same_city" if fits else "elsewhere",
        }

    chat_mock.judge = judge

    response = await admin_client.get(URL, params={"q": QUERY})

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["ranked_by"], body["ranking_model"], body["prompt_version"]) == (
        "ai",
        "gpt-5.4-mini",
        "rank_v5",
    )
    first = body["items"][0]
    assert first["candidate"]["id"] == str(ids[2])
    assert first["fit"] == "strong"
    assert [c["name"] for c in first["criteria"]] == ["skills", "location", "experience"]
    assert {item["fit"] for item in body["items"][1:]} == {"weak"}


@pytest.mark.parametrize(
    "path", [URL, f"{URL}/stream", f"/api/v1/semantic-search/jobs/{uuid.uuid4()}/candidates/stream"]
)
async def test_a_link_from_another_site_cannot_start_a_paid_search(
    admin_client: AsyncClient, path: str
) -> None:
    # A cross-site link sends the Lax session cookie but can't add the fetch header.
    del admin_client.headers["X-Requested-With"]

    response = await admin_client.get(path, params={"q": QUERY})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"
    assert await _events("search_query") == []


async def test_the_llm_never_sees_names_or_contact_details(
    admin_client: AsyncClient, chat_mock: ChatMock
) -> None:
    await _seed_embedded(2)

    response = await admin_client.get(URL, params={"q": QUERY})

    assert response.status_code == 200, response.text
    [payload] = chat_mock.payloads
    sent = json.dumps(payload)
    for leaked in ("Semantic Person", "@example.com", "+91 98765", "linkedin", "github.com"):
        assert leaked not in sent
    assert payload["model"] == "gpt-5.4-mini"
    assert payload["reasoning_effort"] == "low"
    assert payload["response_format"]["type"] == "json_schema"
    assert {p["city"] for p in ChatMock.profiles(payload)} == {"Bengaluru"}


async def test_ranking_is_metered_with_output_tokens_and_audited(
    admin_client: AsyncClient,
) -> None:
    await _seed_embedded(2)

    response = await admin_client.get(URL, params={"q": QUERY})

    assert response.status_code == 200, response.text
    [event] = await _events("search_rank")
    assert (event.status, event.model, event.item_count) == ("succeeded", "gpt-5.4-mini", 2)
    assert (event.input_tokens, event.output_tokens) == (1200, 300)
    # 1,200 x $0.75 + 300 x $4.50 per million tokens.
    assert event.cost_usd == Decimal("0.002250")
    [query_event] = await _events("search_query")
    assert query_event.status == "succeeded"
    [audit] = await _search_audits()
    assert audit.details == {
        "mode": "semantic",
        "filters": ["q"],
        "limit": 25,
        "understood": [],
        "understanding_prompt_version": "understand_v1",
        "result_count": 2,
        "filtered_out_count": 0,
        "ranked_by": "ai",
    }
    assert "payments" not in json.dumps(audit.details)


async def test_the_ai_judges_the_whole_shortlist_but_only_the_top_25_are_returned(
    admin_client: AsyncClient, chat_mock: ChatMock
) -> None:
    ids = await _seed_embedded(30)

    def judge(profile: dict[str, Any]) -> dict[str, Any]:
        number = int(profile["profile"].split("Specialist number ")[1].split(".")[0].split()[0])
        return {**_judge_everyone_the_same(profile), "skills_score": 90 if number < 25 else 10}

    chat_mock.judge = judge

    body = (await admin_client.get(URL, params={"q": QUERY})).json()

    [payload] = chat_mock.payloads
    assert len(ChatMock.profiles(payload)) == 30
    # Set by what the AI judged, not by the order the search fetched them in.
    assert {m["candidate"]["id"] for m in body["items"]} == {str(cid) for cid in ids[:25]}


async def test_a_place_in_the_search_text_brings_in_people_from_outside_the_shortlist(
    admin_client: AsyncClient, chat_mock: ChatMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "POOL_SIZE", 20)  # so 25 profiles overflow it
    ids = await _seed_embedded(25)
    unfiltered = (await admin_client.get(URL, params={"q": QUERY})).json()
    shown = {m["candidate"]["id"] for m in unfiltered["items"]}
    hidden = next(cid for cid in ids if str(cid) not in shown)
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(update(Candidate).values(city="Chennai"))
        (await session.get_one(Candidate, hidden)).city = "New Delhi"
    understanding.clear_understanding_cache()
    chat_mock.facts = {"city": "delhi", "country_code": None, "min_years": None}

    body = (await admin_client.get(URL, params={"q": QUERY})).json()

    # Fetched first, and nobody else is removed: the text isn't a filter.
    assert ChatMock.profiles(chat_mock.payloads[-1])[0]["city"] == "New Delhi"
    assert str(hidden) in {m["candidate"]["id"] for m in body["items"]}
    assert len(body["items"]) == 20
    assert body["filtered_out"] == []
    assert all(m["failed_filters"] == [] for m in body["items"])
    audit = (await _search_audits())[-1]
    assert audit.details["understood"] == ["city"]
    assert "delhi" not in json.dumps(audit.details).lower()


async def test_a_filter_the_recruiter_set_wins_over_the_search_text(
    admin_client: AsyncClient, chat_mock: ChatMock
) -> None:
    ids = await _seed_embedded(3)
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(update(Candidate).values(city="Chennai"))
        (await session.get_one(Candidate, ids[0])).city = "Delhi"
    chat_mock.facts = {"city": "delhi", "country_code": None, "min_years": None}

    body = (await admin_client.get(URL, params={"q": QUERY, "city": "chennai"})).json()

    assert {m["candidate"]["id"] for m in body["items"]} == {str(ids[1]), str(ids[2])}
    assert [m["failed_filters"] for m in body["filtered_out"]] == [["city"]]
    assert [p["city"] for p in ChatMock.profiles(chat_mock.payloads[0])][:2] == ["Chennai"] * 2


@pytest.mark.parametrize(
    ("failure", "status"),
    [("provider", "failed"), ("timeout", "failed"), ("invalid", "succeeded")],
)
async def test_a_search_still_works_when_its_text_cannot_be_understood(
    admin_client: AsyncClient,
    chat_mock: ChatMock,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    status: str,
) -> None:
    await _seed_embedded(2)
    if failure == "provider":
        chat_mock.understanding_statuses.append(500)
    elif failure == "timeout":
        monkeypatch.setattr(understanding, "TIMEOUT_SECONDS", 0.01)
        chat_mock.understanding_delay_seconds = 1.0
    else:
        chat_mock.facts = {"city": "delhi", "country_code": "NOT-A-COUNTRY", "min_years": 999}

    response = await admin_client.get(URL, params={"q": QUERY})

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["ranked_by"], len(body["items"])) == ("ai", 2)
    assert [e.status for e in await _events("search_understand")] == [status]
    [audit] = await _search_audits()
    assert audit.details["understood"] == []


async def test_hard_filters_split_the_ranked_list_and_keep_its_order(
    admin_client: AsyncClient, chat_mock: ChatMock
) -> None:
    ids = await _seed_embedded(3)
    async with get_sessionmaker()() as session, session.begin():
        (await session.get_one(Candidate, ids[2])).city = "Delhi"

    def judge(profile: dict[str, Any]) -> dict[str, Any]:
        number = int(profile["profile"].split("Specialist number ")[1][0])
        return {**_judge_everyone_the_same(profile), "skills_score": 50 + 20 * number}

    chat_mock.judge = judge

    response = await admin_client.get(
        URL, params={"q": QUERY, "city": " bengaluru ", "skill": "FastAPI, python", "min_years": 6}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    # The best-ranked profile lives elsewhere: shown apart, with the reason, not dropped.
    assert [m["candidate"]["id"] for m in body["filtered_out"]] == [str(ids[2])]
    assert body["filtered_out"][0]["failed_filters"] == ["city"]
    assert [m["candidate"]["id"] for m in body["items"]] == [str(ids[1]), str(ids[0])]
    assert all(m["failed_filters"] == [] for m in body["items"])
    [audit] = await _search_audits()
    assert audit.details["filters"] == ["q", "min_years", "skill", "city"]
    assert (audit.details["result_count"], audit.details["filtered_out_count"]) == (2, 1)

    stricter = await admin_client.get(
        URL, params={"q": QUERY, "min_years": 7, "skill": "rust", "country": "us", "source": "x"}
    )

    assert stricter.json()["items"] == []
    assert {tuple(m["failed_filters"]) for m in stricter.json()["filtered_out"]} == {
        ("min_years", "skill", "country", "source")
    }


async def test_a_filter_finds_a_perfect_match_outside_the_unfiltered_shortlist(
    admin_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "POOL_SIZE", 20)  # so 25 profiles overflow it
    ids = await _seed_embedded(25)
    unfiltered = (await admin_client.get(URL, params={"q": QUERY})).json()
    shown = {m["candidate"]["id"] for m in unfiltered["items"]}
    [hidden] = [cid for cid in ids if str(cid) not in shown][:1]
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(update(Candidate).values(city="Chennai"))
        (await session.get_one(Candidate, hidden)).city = "Bangalore"  # an alias spelling

    body = (await admin_client.get(URL, params={"q": QUERY, "city": "bengaluru"})).json()

    # The only profile passing was outside the unfiltered top 20; it is found because the
    # filter is applied before fetching, and the best of the rest are still shown apart.
    assert [m["candidate"]["id"] for m in body["items"]] == [str(hidden)]
    assert len(body["filtered_out"]) == 10
    assert {tuple(m["failed_filters"]) for m in body["filtered_out"]} == {("city",)}


async def test_nothing_to_rank_makes_no_paid_call(admin_client: AsyncClient) -> None:
    await _seed_embedded(2)

    response = await admin_client.get(URL, params={"q": QUERY, "country": "DE"})

    body = response.json()
    assert (body["items"], len(body["filtered_out"])) == ([], 2)
    job_id = await _embedded_job(admin_client, city="Berlin", country_code="DE")
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(delete(Candidate))

    empty = (await admin_client.get(_job_url(job_id))).json()

    assert (empty["items"], empty["filtered_out"]) == ([], [])
    assert len(await _events("search_rank")) == 1  # the search above, not the empty match


async def test_a_repeated_search_reuses_the_ranking(
    admin_client: AsyncClient, chat_mock: ChatMock
) -> None:
    await _seed_embedded(1)

    first = await admin_client.get(URL, params={"q": QUERY})
    second = await admin_client.get(URL, params={"q": f"  {QUERY.upper()} "})

    assert first.status_code == second.status_code == 200
    assert first.json()["items"] == second.json()["items"]
    assert len(chat_mock.payloads) == 1
    assert len(chat_mock.understanding_payloads) == 1


async def test_an_edited_profile_is_ranked_again(
    admin_client: AsyncClient, chat_mock: ChatMock
) -> None:
    [candidate_id] = await _seed_embedded(1)
    assert (await admin_client.get(URL, params={"q": QUERY})).status_code == 200
    async with get_sessionmaker()() as session, session.begin():
        (await session.get_one(Candidate, candidate_id)).headline = "Staff Engineer"

    assert (await admin_client.get(URL, params={"q": QUERY})).status_code == 200

    assert len(chat_mock.payloads) == 2


async def test_when_the_llm_fails_results_keep_the_search_order(
    admin_client: AsyncClient, chat_mock: ChatMock
) -> None:
    ids = await _seed_embedded(2)
    async with get_sessionmaker()() as session, session.begin():
        fits = await session.get_one(Candidate, ids[1])
        fits.city = "Ghaziabad"
    chat_mock.statuses.append(500)

    # Only the city is a keyword, so only that profile is in both halves of the fetch.
    response = await admin_client.get(URL, params={"q": "ghaziabad"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["ranked_by"], body["ranking_model"]) == ("search", None)
    [first, second] = body["items"]
    # Full text also matches the city, so the hybrid fetch puts that profile first.
    assert first["candidate"]["id"] == str(ids[1])
    assert (first["fit"], first["criteria"]) == (None, [])
    assert second["candidate"]["id"] == str(ids[0])
    [event] = await _events("search_rank")
    assert (event.status, event.error) == ("failed", "LLMError status=500")


async def test_a_refused_answer_is_billed_at_input_and_output_prices(
    admin_client: AsyncClient, chat_mock: ChatMock
) -> None:
    await _seed_embedded(1)
    chat_mock.refusal = "I can't help with that."

    response = await admin_client.get(URL, params={"q": QUERY})

    assert response.json()["ranked_by"] == "search"
    [event] = await _events("search_rank")
    assert (event.status, event.input_tokens, event.output_tokens) == ("failed", 1200, 300)
    # 1,200 x $0.75 + 300 x $4.50 per million tokens, not all 1,500 at the input price.
    assert event.cost_usd == Decimal("0.002250")


async def test_a_spent_budget_after_the_embedding_still_returns_results(
    admin_client: AsyncClient, chat_mock: ChatMock
) -> None:
    await _seed_embedded(1)
    # $0.000001 short of the limit: the query embedding (about $0.000001) is the last call
    # allowed, so the ranking call is the one refused.
    await _set_limit("0.01")
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(delete(AiUsageEvent))  # the seeding embedding's spend
        session.add(
            AiUsageEvent(
                provider="openai",
                model="text-embedding-3-small",
                operation="candidate_embedding",
                trigger="worker",
                item_count=1,
                input_tokens=0,
                output_tokens=0,
                cost_usd=Decimal("0.009999"),
                status="succeeded",
            )
        )

    response = await admin_client.get(URL, params={"q": QUERY})

    assert response.status_code == 200, response.text
    assert response.json()["ranked_by"] == "search"
    assert chat_mock.payloads == []
    assert chat_mock.understanding_payloads == []
    assert [e.status for e in await _events("search_query")] == ["succeeded"]
    assert [e.status for e in await _events("search_understand")] == ["blocked"]
    assert [e.status for e in await _events("search_rank")] == ["blocked"]


async def test_full_text_finds_the_city_and_follows_edits() -> None:
    ids = await _seed_embedded(3)
    async with get_sessionmaker()() as session, session.begin():
        (await session.get_one(Candidate, ids[2])).city = "Ghaziabad"

    async with get_sessionmaker()() as session:
        found = await full_text_candidate_ids(session, "fastapi developer in ghaziabad", count=20)

    # Every profile mentions FastAPI, but only one also matches the city.
    assert found[0] == ids[2]
    assert set(found) == set(ids)


@pytest.mark.parametrize(
    "query",
    ["asha@example.com", "call +91 98765 43210", "https://github.com/someone", "www.site.dev"],
)
async def test_personal_looking_queries_never_reach_openai(
    admin_client: AsyncClient,
    openai_mock: OpenAIEmbeddingsMock,
    chat_mock: ChatMock,
    query: str,
) -> None:
    calls_before = len(openai_mock.requests)

    response = await admin_client.get(URL, params={"q": query})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "query_not_searchable_by_meaning"
    assert len(openai_mock.requests) == calls_before
    assert chat_mock.payloads == []


async def test_exhausted_budget_blocks_the_query_without_a_call(
    admin_client: AsyncClient, openai_mock: OpenAIEmbeddingsMock, chat_mock: ChatMock
) -> None:
    await _seed_embedded(1)
    await _set_limit("0.00")
    calls_before = len(openai_mock.requests)

    response = await admin_client.get(URL, params={"q": QUERY})

    assert response.status_code == 402
    assert response.json()["error"]["code"] == "budget_exceeded"
    assert len(openai_mock.requests) == calls_before
    assert chat_mock.payloads == []
    assert await _search_audits() == []


async def test_embedding_failure_is_a_clean_503(
    admin_client: AsyncClient, openai_mock: OpenAIEmbeddingsMock
) -> None:
    openai_mock.queue_status(400)

    response = await admin_client.get(URL, params={"q": QUERY})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "semantic_search_unavailable"
    [event] = await _events("search_query")
    assert (event.status, event.cost_usd) == ("failed", Decimal(0))


async def test_recruiters_can_search_and_anonymous_users_cannot(
    client: AsyncClient, recruiter_client: AsyncClient
) -> None:
    await _seed_embedded(1)

    assert (await recruiter_client.get(URL, params={"q": QUERY})).status_code == 200
    anonymous = await client.get(URL, params={"q": QUERY}, headers=FETCH_HEADERS)
    assert anonymous.status_code == 401


@pytest.mark.parametrize(
    "params",
    [
        {"q": "a"},
        {"q": "x" * 501},
        {"q": QUERY, "limit": 0},
        {"q": QUERY, "limit": 26},
        {},
        {"q": QUERY, "min_years": -1},
        {"q": QUERY, "country": "ZZ"},
        {"q": QUERY, "city": "a\x00b"},
    ],
)
async def test_invalid_parameters_are_rejected(
    admin_client: AsyncClient, openai_mock: OpenAIEmbeddingsMock, params: dict[str, Any]
) -> None:
    calls_before = len(openai_mock.requests)

    response = await admin_client.get(URL, params=params)

    assert response.status_code == 422
    assert len(openai_mock.requests) == calls_before


# --- Matching candidates to a job ----------------------------------------------------------


async def _embedded_job(client: AsyncClient, **overrides: Any) -> str:
    job = await create_job(client, **overrides)
    async with get_sessionmaker()() as session:
        await embed_stale(session, get_embedding_provider(), JOBS)
    job_id: str = job["id"]
    return job_id


def _job_url(job_id: str) -> str:
    return f"/api/v1/semantic-search/jobs/{job_id}/candidates"


async def test_a_job_is_matched_by_its_stored_embedding_and_split_by_its_requirements(
    admin_client: AsyncClient, chat_mock: ChatMock, openai_mock: OpenAIEmbeddingsMock
) -> None:
    ids = await _seed_embedded(3)  # Bengaluru, IN, 6.5 years, python/fastapi/postgresql
    async with get_sessionmaker()() as session, session.begin():
        (await session.get_one(Candidate, ids[1])).city = "Pune"
        (await session.get_one(Candidate, ids[2])).years_experience = Decimal(2)
    job_id = await _embedded_job(
        admin_client,
        work_mode="onsite",
        city="Bengaluru",
        country_code="IN",
        min_years=5,
        must_have_skills=["Python"],
        salary_min=1_500_000,
        salary_max=2_400_000,
        salary_currency="inr",
    )
    embedding_calls = len(openai_mock.requests)

    response = await admin_client.get(_job_url(job_id))

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(openai_mock.requests) == embedding_calls  # the job's stored vector, no new call
    assert [m["candidate"]["id"] for m in body["items"]] == [str(ids[0])]
    assert {m["candidate"]["id"]: m["failed_filters"] for m in body["filtered_out"]} == {
        str(ids[1]): ["city"],
        str(ids[2]): ["min_years"],
    }
    # The LLM sees the job brief and its pay, never the job owner's name.
    [payload] = chat_mock.payloads
    prompt = payload["messages"][1]["content"]
    assert "Pay: 1500000-2400000 INR per year." in prompt
    assert "Must-have skills: python" in prompt
    [audit] = [a for a in await _all_audits() if a.action == "job.match"]
    assert audit.entity_id == uuid.UUID(job_id)
    assert audit.details == {"result_count": 1, "filtered_out_count": 2, "ranked_by": "ai"}


async def test_a_remote_job_does_not_filter_by_city(admin_client: AsyncClient) -> None:
    ids = await _seed_embedded(1)
    job_id = await _embedded_job(
        admin_client, work_mode="remote", city="Pune", country_code="IN", min_years=1
    )

    body = (await admin_client.get(_job_url(job_id))).json()

    assert [m["candidate"]["id"] for m in body["items"]] == [str(ids[0])]


async def test_a_job_without_a_current_embedding_is_not_ready(admin_client: AsyncClient) -> None:
    job = await create_job(admin_client)  # saved, not embedded yet

    response = await admin_client.get(_job_url(job["id"]))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "job_not_ready_for_matching"
    assert await _events("search_rank") == []


async def test_an_unknown_job_is_404(admin_client: AsyncClient) -> None:
    response = await admin_client.get(_job_url(str(uuid.uuid4())))

    assert response.status_code == 404


# --- Streamed progress (server-sent events) ---------------------------------------------------


def _sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for block in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((fields["event"], json.loads(fields["data"])))
    return events


async def test_a_streamed_search_reports_each_stage_then_the_result(
    admin_client: AsyncClient,
) -> None:
    await _seed_embedded(2)

    response = await admin_client.get(f"{URL}/stream", params={"q": QUERY, "country": "IN"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _sse(response.text)
    stages = [(data["stage"], data["state"]) for name, data in events if name == "stage"]
    assert [step for step in stages if step[1] != "progress"] == [
        (stage, state)
        for stage in ("embedding", "retrieval", "augmentation", "ranking", "filtering")
        for state in ("started", "done")
    ]
    # The AI's answer is streamed and counted: one count at the last profile, inside ranking.
    counts = [d for n, d in events if n == "stage" and d["state"] == "progress"]
    assert [(c["stage"], c["completed"], c["total"], c["detail"]) for c in counts] == [
        ("ranking", 2, 2, "Read 2 of 2 profiles")
    ]
    assert stages.index(("ranking", "progress")) == stages.index(("ranking", "started")) + 1
    details = {d["stage"]: d["detail"] for n, d in events if n == "stage" and d["state"] == "done"}
    assert details["retrieval"] == "Found 2 profiles, 2 meeting every filter"
    assert details["ranking"] == "Every profile judged"
    assert all(d["elapsed_ms"] >= 0 for n, d in events if n == "stage" and d["state"] == "done")
    name, result = events[-1]
    assert name == "result"
    assert (len(result["items"]), result["checked"], result["ranked_by"]) == (2, 2, "ai")
    [event] = await _events("search_rank")
    # Streaming still records the tokens, so the call is priced like a plain one.
    assert (event.input_tokens, event.output_tokens) == (1200, 300)
    # The query text is never echoed in the progress.
    assert "payments" not in json.dumps([d for n, d in events if n == "stage"])


async def test_a_streamed_search_says_back_the_place_and_years_it_read(
    admin_client: AsyncClient, chat_mock: ChatMock
) -> None:
    await _seed_embedded(1)
    chat_mock.facts = {"city": "new delhi", "country_code": "IN", "min_years": 5}

    events = _sse((await admin_client.get(f"{URL}/stream", params={"q": QUERY})).text)

    [understood] = [
        d for n, d in events if n == "stage" and d["stage"] == "embedding" and d["state"] == "done"
    ]
    assert understood["detail"] == "Looking first in New Delhi, India, 5+ years"


async def test_a_streamed_search_sends_profiles_only_in_the_final_result(
    admin_client: AsyncClient,
) -> None:
    await _seed_embedded(2)

    response = await admin_client.get(f"{URL}/stream", params={"q": QUERY, "city": "Nowhere"})

    events = _sse(response.text)
    assert {name for name, _ in events[:-1]} == {"stage"}
    assert "Semantic Person" not in json.dumps([data for _, data in events[:-1]])
    name, result = events[-1]
    assert name == "result"
    assert all(m["fit"] is not None for m in result["filtered_out"])


async def test_a_streamed_job_match_reports_errors_in_the_stream(
    admin_client: AsyncClient,
) -> None:
    job = await create_job(admin_client)  # not embedded yet

    response = await admin_client.get(f"{_job_url(job['id'])}/stream")

    assert response.status_code == 200  # the stream had started; the error is an event
    [(started, stage), (name, error)] = _sse(response.text)
    assert (started, stage["stage"], stage["state"]) == ("stage", "embedding", "started")
    assert (name, error["status"], error["code"]) == ("error", 409, "job_not_ready_for_matching")


async def test_a_streamed_job_match_says_it_reused_the_saved_embedding(
    admin_client: AsyncClient,
) -> None:
    await _seed_embedded(1)
    job_id = await _embedded_job(admin_client, city="Bengaluru", country_code="IN")

    events = _sse((await admin_client.get(f"{_job_url(job_id)}/stream")).text)

    [embedding_done] = [
        d for n, d in events if n == "stage" and d["stage"] == "embedding" and d["state"] == "done"
    ]
    assert embedding_done["detail"] == "Job understood from its saved profile, no new AI call"
    assert events[-1][0] == "result"


async def test_streams_need_a_signed_in_user(client: AsyncClient) -> None:
    response = await client.get(f"{URL}/stream", params={"q": QUERY}, headers=FETCH_HEADERS)
    assert response.status_code == 401


async def test_the_shortlist_is_not_cut_at_the_old_size_of_20(
    admin_client: AsyncClient, chat_mock: ChatMock
) -> None:
    await _seed_embedded(25)

    body = (await admin_client.get(URL, params={"q": QUERY})).json()

    assert len(ChatMock.profiles(chat_mock.payloads[0])) == 25
    assert len(body["items"]) == 25


async def test_a_large_nearest_search_widens_the_index_scan() -> None:
    # The HNSW index returns at most ef_search rows (40 by default), whatever the LIMIT says.
    async with get_sessionmaker()() as session, session.begin():
        await nearest_neighbours(session, [0.0] * 1536, "text-embedding-3-small", 100)
        assert await session.scalar(text("SHOW hnsw.ef_search")) == "100"


async def test_rebuilding_documents_updates_old_ones_without_touching_the_profile() -> None:
    [old_format, _] = await _seed_embedded(2, city="Noida", country_code="IN")
    async with get_sessionmaker()() as session, session.begin():
        row = await session.get_one(Candidate, old_format)
        row.search_document = "Document in an old format."
    async with get_sessionmaker()() as session:
        await embed_stale(session, get_embedding_provider(), CANDIDATES)
    async with get_sessionmaker()() as session, session.begin():
        before = await session.get_one(Candidate, old_format)
        version, updated_at = before.version, before.updated_at

    async with get_sessionmaker()() as session:
        assert await rebuild_search_documents(session) == 1
    async with get_sessionmaker()() as session:
        assert await rebuild_search_documents(session) == 0  # nothing left to do

    async with get_sessionmaker()() as session, session.begin():
        rebuilt = await session.get_one(Candidate, old_format)
        assert "Location: Noida, India." in rebuilt.search_document
        assert (rebuilt.version, rebuilt.updated_at) == (version, updated_at)
    # Only the changed one is embedded again.
    async with get_sessionmaker()() as session:
        outcome = await embed_stale(session, get_embedding_provider(), CANDIDATES)
    assert outcome.embedded == 1


async def test_rebuilding_documents_locks_the_profiles_it_reads() -> None:
    """An edit saved while the rebuild runs must wait, not be overwritten by old text."""
    [candidate_id] = await _seed_embedded(1)
    async with get_sessionmaker()() as reader, reader.begin():
        await candidates_repository.list_candidates_with_children(reader)
        async with get_sessionmaker()() as writer:
            await writer.execute(text("SET lock_timeout = '200ms'"))
            with pytest.raises(DBAPIError, match="lock timeout"):
                await writer.execute(
                    update(Candidate)
                    .where(Candidate.id == candidate_id)
                    .values(headline="Edited meanwhile")
                )
            await writer.rollback()


async def _all_audits() -> list[AuditEvent]:
    async with get_sessionmaker()() as session, session.begin():
        return list(await session.scalars(select(AuditEvent)))


@pytest.mark.parametrize(
    ("skill", "city", "passes"),
    [
        ("postgres", "bangalore", True),  # other spellings of the stored values
        ("PostgreSQL", "Bengaluru", True),
        ("postgres", "noida", False),  # a different city
        ("mysql", "bangalore", False),  # a missing skill
    ],
)
async def test_sql_and_python_filters_agree_on_spellings(
    skill: str, city: str, passes: bool
) -> None:
    """The SQL prefilter and the Python split must agree, or a perfect match shows as filtered."""
    [candidate_id] = await _seed_embedded(1, skills=["postgresql", "python"], city="Bengaluru")
    filters = HardFilters(skill=skill, city=city)

    async with get_sessionmaker()() as session, session.begin():
        passing_sql = candidate_id in set(
            await session.scalars(
                candidate_ids_passing(
                    min_years=None, skills=split_tags(skill), city=city, country=None, source=None
                )
            )
        )
    async with get_sessionmaker()() as session:
        rankable = (await get_rankable_candidates(session, [candidate_id]))[candidate_id]

    assert passing_sql is passes
    assert (service.failed_filters(rankable, filters) == []) is passes


def test_looks_personal() -> None:
    assert service.looks_personal("me@x.io")
    assert service.looks_personal("+91 98765 43210")
    assert service.looks_personal("(022) 555-0199")
    # A yearly salary is not a phone number (same 10-digit rule as redaction).
    assert not service.looks_personal("python developer budget 2500000 INR")
    assert not service.looks_personal("python engineer with 10 years in 2024")
    assert not service.looks_personal("react 18, node 20, 5+ years")
