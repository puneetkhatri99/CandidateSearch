import json
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import httpx2
import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, update

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
)
from app.features.candidates.models import Candidate
from app.features.candidates.tests.factories import valid_candidate_payload
from app.features.embeddings import CANDIDATES, JOBS, embed_stale
from app.features.semantic_search import ranking, service
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
    """Answers /v1/chat/completions like the ranking model would, from `judge`."""

    judge: Judge = _judge_everyone_the_same
    payloads: list[dict[str, Any]] = field(default_factory=list)
    statuses: list[int] = field(default_factory=list)
    # Set to answer with a refusal instead of judgements (still billed by OpenAI).
    refusal: str | None = None

    @staticmethod
    def profiles(payload: dict[str, Any]) -> list[dict[str, Any]]:
        content: str = payload["messages"][1]["content"]
        parsed: list[dict[str, Any]] = json.loads(content.split("Candidates:\n", 1)[1])
        return parsed

    async def handler(self, request: httpx2.Request) -> httpx2.Response:
        payload = json.loads(request.content)
        self.payloads.append(payload)
        if self.statuses:
            body = {"error": {"message": "mocked failure", "type": "mock_error", "code": None}}
            return httpx2.Response(self.statuses.pop(0), json=body)
        judgements = [self.judge(p) for p in self.profiles(payload)]
        answer = {
            "search_names_place": any(j["location"] != "not_required" for j in judgements),
            "search_states_pay": any(j["salary"] != "not_required" for j in judgements),
            "judgements": judgements,
        }
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
                            "content": None if self.refusal else json.dumps(answer),
                            "refusal": self.refusal,
                        },
                    }
                ],
                "usage": {"prompt_tokens": 1200, "completion_tokens": 300, "total_tokens": 1500},
            },
        )


@pytest.fixture(autouse=True)
def empty_cache() -> Iterator[None]:
    ranking.clear_ranking_cache()
    yield
    ranking.clear_ranking_cache()


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
        "rank_v3",
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
        "limit": 20,
        "result_count": 2,
        "filtered_out_count": 0,
        "ranked_by": "ai",
    }
    assert "payments" not in json.dumps(audit.details)


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


async def test_a_filter_finds_a_perfect_match_outside_the_unfiltered_top_20(
    admin_client: AsyncClient,
) -> None:
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

    response = await admin_client.get(URL, params={"q": "fastapi developer in ghaziabad"})

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
    assert [e.status for e in await _events("search_query")] == ["succeeded"]
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
        {"q": QUERY, "limit": 21},
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
    assert stages == [
        (stage, state)
        for stage in ("embedding", "retrieval", "augmentation", "ranking", "filtering")
        for state in ("started", "done")
    ]
    details = {d["stage"]: d["detail"] for n, d in events if n == "stage" and d["state"] == "done"}
    assert details["retrieval"] == "Found 2 profiles, 2 meeting every filter"
    assert details["ranking"] == "Ranked by gpt-5.4-mini"
    assert all(d["elapsed_ms"] >= 0 for n, d in events if n == "stage" and d["state"] == "done")
    name, result = events[-1]
    assert name == "result"
    assert len(result["items"]) == 2
    # The query text is never echoed in the progress.
    assert "payments" not in response.text.split("event: result")[0]


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
    assert embedding_done["detail"] == "Used the job's saved embedding, no new AI call"
    assert events[-1][0] == "result"


async def test_streams_need_a_signed_in_user(client: AsyncClient) -> None:
    response = await client.get(f"{URL}/stream", params={"q": QUERY}, headers=FETCH_HEADERS)
    assert response.status_code == 401


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
