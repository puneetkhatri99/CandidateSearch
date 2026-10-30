"""Search candidates by meaning: hybrid fetch (embedding + full text), then an LLM ranking.

The query text is sent to OpenAI, so queries that look like personal identifiers are refused
here. The text is never logged or audited. Hard filters are applied after the ranking.
"""

import asyncio
import uuid
from typing import Literal

import structlog
from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.embeddings import (
    EmbeddingBatch,
    EmbeddingConfigurationError,
    EmbeddingError,
    OpenAIEmbeddingProvider,
    get_embedding_provider,
)
from app.core.llm import LLMError, get_llm_client
from app.features import ai_usage, candidates, embeddings, jobs
from app.features.audit import record_event
from app.features.auth import AuthContext
from app.features.semantic_search import ranking
from app.features.semantic_search.exceptions import (
    JobNotReadyForMatchingError,
    QueryLooksPersonalError,
    SemanticSearchUnavailableError,
)
from app.features.semantic_search.progress import Progress
from app.features.semantic_search.schemas import (
    MAX_RESULTS,
    FilterName,
    HardFilters,
    SemanticMatch,
    SemanticSearchParams,
    SemanticSearchResult,
)
from app.shared.aliases import city_spellings, skill_spellings
from app.shared.redaction import contains_phone_number
from app.shared.validation import split_tags

logger = structlog.get_logger(__name__)

OPERATION = "search_query"
RANK_OPERATION = "search_rank"
# Interactive: give up long before the SDK's own retries would (30 s x 4 attempts).
EMBED_TIMEOUT_SECONDS = 10.0

# Each half of the hybrid fetch, and the fused shortlist the LLM ranks (user's choice).
POOL_SIZE = 20
# Best hybrid hits that fail a hard filter, ranked too and shown apart ("Filtered out").
FILTERED_OUT_SIZE = 10


def looks_personal(query: str) -> bool:
    lowered = query.lower()
    if "@" in lowered or "://" in lowered or "www." in lowered:
        return True
    # The same phone rule as redaction, so a yearly salary like 2500000 is still searchable.
    return contains_phone_number(query)


def failed_filters(
    candidate: candidates.RankableCandidate, params: HardFilters
) -> list[FilterName]:
    """The hard filters this candidate fails. Same rules as candidates.candidate_ids_passing
    (in SQL); change both together."""
    failed: list[FilterName] = []
    if params.min_years is not None and candidate.years_experience < float(params.min_years):
        failed.append("min_years")
    owned = set(candidate.skills)
    if any(not skill_spellings(skill) & owned for skill in split_tags(params.skill)):
        failed.append("skill")
    if params.city and candidate.city.lower() not in city_spellings(params.city):
        failed.append("city")
    if params.country and candidate.country_code != params.country:
        failed.append("country")
    if params.source and candidate.summary.source != params.source:
        failed.append("source")
    return failed


def _active_filters(params: HardFilters) -> list[str]:
    names = ("min_years", "skill", "city", "country", "source")
    return [name for name in names if getattr(params, name) not in (None, "")]


async def _rank_with_llm(
    session: AsyncSession,
    query: str,
    pool: list[candidates.RankableCandidate],
    required: ranking.WorkMode | None,
    progress: Progress,
) -> list[SemanticMatch] | None:
    """The pool ordered by the LLM's judgements, or None when the AI ranking is unavailable
    (no key, budget used up, provider error or timeout); the caller then falls back."""
    await progress.start("augmentation", "Building an anonymised brief for the AI")
    content = ranking.build_prompt(query, pool)
    await progress.done("augmentation", f"{_profiles(len(pool))}, without names or contact details")
    await progress.start("ranking", "AI is judging each candidate")
    if not pool:
        await progress.done("ranking", "Nothing to rank")
        return []  # nothing to judge, so no paid call
    key = ranking.cache_key(ranking.RANK_MODEL, query, pool)
    answer = ranking.cached_answer(key)
    if answer is not None:
        await progress.done("ranking", "Reused the AI ranking from the last 10 minutes")
    else:
        try:
            client = get_llm_client()
            result = await ai_usage.metered_call(
                session,
                provider=client.provider_name,
                model=ranking.RANK_MODEL,
                operation=RANK_OPERATION,
                trigger="api",
                item_count=len(pool),
                call=lambda: client.parse(
                    model=ranking.RANK_MODEL,
                    instructions=ranking.INSTRUCTIONS,
                    content=content,
                    schema=ranking.RankingAnswer,
                    max_output_tokens=ranking.MAX_OUTPUT_TOKENS,
                ),
                tokens_of=lambda r: (r.input_tokens, r.output_tokens),
            )
        except (LLMError, ai_usage.BudgetExceededError, ai_usage.UnknownModelPriceError) as exc:
            logger.warning("semantic_search_ranking_unavailable", error_type=type(exc).__name__)
            await progress.done("ranking", "AI ranking unavailable, kept the search order")
            return None
        answer = result.parsed
        ranking.remember_answer(key, answer)
        await progress.done("ranking", f"Ranked by {ranking.RANK_MODEL}")
    return ranking.rank_by_judgements(answer, pool, required)


def _profiles(count: int) -> str:
    return f"{count} profile{'' if count == 1 else 's'}"


async def _embed_query(
    session: AsyncSession, provider: OpenAIEmbeddingProvider, query: str
) -> list[float]:
    try:
        batch = await ai_usage.metered_call(
            session,
            provider=provider.provider_name,
            model=provider.model_name,
            operation=OPERATION,
            trigger="api",
            item_count=1,
            # The timeout wraps only the call, so a slow answer is recorded as a failed event.
            call=lambda: asyncio.wait_for(
                provider.embed_documents([query]), timeout=EMBED_TIMEOUT_SECONDS
            ),
            tokens_of=EmbeddingBatch.billed_tokens,
        )
    except (EmbeddingError, TimeoutError, ai_usage.UnknownModelPriceError) as exc:
        logger.warning("semantic_search_embedding_failed", error_type=type(exc).__name__)
        raise SemanticSearchUnavailableError(
            "Search is unavailable right now. Try again, or clear the search to browse by filters."
        ) from exc

    return batch.vectors[0]


async def search_by_meaning(
    session: AsyncSession,
    params: SemanticSearchParams,
    actor: AuthContext,
    progress: Progress | None = None,
) -> SemanticSearchResult:
    """Fetch the best hybrid matches (meaning + full text), then let the LLM rank them.

    Raises BudgetExceededError (402) when the query can't even be embedded within the AI
    spending limit; a ranking that can't run returns the hybrid-search order instead.
    """
    if looks_personal(params.q):
        raise QueryLooksPersonalError(
            "Emails, phone numbers and links can't be searched. "
            "Describe the role or skills you need instead."
        )
    try:
        provider = get_embedding_provider()
    except EmbeddingConfigurationError as exc:
        raise SemanticSearchUnavailableError(
            "Search needs an OpenAI API key. Clear the search to browse by filters."
        ) from exc

    progress = progress or Progress()
    await progress.start("embedding", "Turning your search into an embedding")
    vector = await _embed_query(session, provider, params.q)
    await progress.done("embedding", "Search embedded")
    result = await _find_rank_and_filter(
        session,
        vector=vector,
        embedding_model=provider.model_name,
        keyword_text=params.q,
        brief=params.q,
        required=ranking.required_work_mode(params.q),
        filters=params,
        limit=params.limit,
        progress=progress,
    )
    # Who searched and how many profiles they saw; never the query text or the ids.
    async with session.begin():
        record_event(
            session,
            action="candidate.search",
            entity_type="candidate",
            entity_id=None,
            actor_user_id=actor.user_id,
            ip=actor.ip,
            details={
                "mode": "semantic",
                "filters": ["q", *_active_filters(params)],
                "limit": params.limit,
                **_counts(result),
            },
        )
    logger.info("semantic_search_completed", **_counts(result))
    return result


# Jobs store "onsite"; the ranking's work-mode rule calls it "office".
_JOB_WORK_MODES: dict[str, ranking.WorkMode] = {
    "remote": "remote",
    "hybrid": "hybrid",
    "onsite": "office",
}


def _pay_line(job: jobs.JobBrief) -> str:
    if job.salary_currency is None:
        return ""
    if job.salary_min is not None and job.salary_max is not None:
        pay = f"{job.salary_min}-{job.salary_max}"
    elif job.salary_max is not None:
        pay = f"up to {job.salary_max}"
    else:
        pay = f"from {job.salary_min}"
    return f"\nPay: {pay} {job.salary_currency} per year."


def job_filters(job: jobs.JobBrief) -> HardFilters:
    """The job's own requirements as hard filters (user decision): the city only binds a
    hybrid or onsite job, since a remote one can be done from anywhere in its country."""
    return HardFilters(
        min_years=job.min_years,
        skill=", ".join(job.must_have_skills),
        city=job.city if job.work_mode != "remote" else None,
        country=job.country_code,
    )


async def match_job(
    session: AsyncSession,
    job_id: uuid.UUID,
    actor: AuthContext,
    progress: Progress | None = None,
) -> SemanticSearchResult:
    """Candidates for a job: its stored embedding plus full text fetch 20, the LLM ranks them
    against the job (pay included), then the job's requirements split the list."""
    progress = progress or Progress()
    job = await jobs.get_job_brief(session, job_id)
    model = get_settings().embedding_model
    await progress.start("embedding", "Loading the job's embedding")
    vector = await embeddings.load_job_vector(session, job_id, model)
    if vector is None:
        raise JobNotReadyForMatchingError(
            "This job's AI embedding isn't ready yet. Try again in a few seconds."
        )
    await progress.done("embedding", "Used the job's saved embedding, no new AI call")
    keywords = " ".join([job.title, *job.must_have_skills, job.city or ""])
    result = await _find_rank_and_filter(
        session,
        vector=vector,
        embedding_model=model,
        keyword_text=keywords,
        brief=job.search_document + _pay_line(job),
        required=_JOB_WORK_MODES[job.work_mode],
        filters=job_filters(job),
        limit=MAX_RESULTS,
        progress=progress,
    )
    async with session.begin():
        record_event(
            session,
            action="job.match",
            entity_type="job",
            entity_id=job_id,
            actor_user_id=actor.user_id,
            ip=actor.ip,
            details=_counts(result),
        )
    logger.info("job_match_completed", job_id=str(job_id), **_counts(result))
    return result


def _counts(result: SemanticSearchResult) -> dict[str, object]:
    return {
        "result_count": len(result.items),
        "filtered_out_count": len(result.filtered_out),
        "ranked_by": result.ranked_by,
    }


async def _find_rank_and_filter(
    session: AsyncSession,
    *,
    vector: list[float],
    embedding_model: str,
    keyword_text: str,
    brief: str,
    required: ranking.WorkMode | None,
    filters: HardFilters,
    limit: int,
    progress: Progress,
) -> SemanticSearchResult:
    """Hybrid fetch, LLM ranking against `brief`, then the hard filters split the ranked list
    (so both parts keep the ranked order).

    With filters, the best 20 are fetched among the candidates who pass them (so a perfect
    match is never crowded out of the shortlist), plus the best 10 of everyone else, so
    strong candidates a filter removed are still shown.
    """

    async def hybrid_ids(within: Select[uuid.UUID] | None) -> list[uuid.UUID]:
        # Vectors find the right kind of profile; full text catches exact skills and the city,
        # which the embedded document leaves out.
        nearest = await embeddings.nearest_candidates_to_vector(
            session, vector, embedding_model, count=POOL_SIZE, within=within
        )
        keyword_ids = await candidates.full_text_candidate_ids(
            session, keyword_text, count=POOL_SIZE, within=within
        )
        return ranking.fuse([cid for cid, _ in nearest], keyword_ids, count=POOL_SIZE)

    await progress.start("retrieval", "Searching profiles by meaning and keywords")
    passing: list[uuid.UUID] = []
    if _active_filters(filters):
        passing = await hybrid_ids(
            candidates.candidate_ids_passing(
                min_years=filters.min_years,
                skills=split_tags(filters.skill),
                city=filters.city or None,
                country=filters.country,
                source=filters.source or None,
            )
        )
        passing_set = set(passing)
        others = [cid for cid in await hybrid_ids(None) if cid not in passing_set]
        pool_ids = passing + others[:FILTERED_OUT_SIZE]
    else:
        pool_ids = await hybrid_ids(None)
    found = await candidates.get_rankable_candidates(session, pool_ids)
    pool = [found[cid] for cid in pool_ids if cid in found]  # deleted between the reads
    await progress.done(
        "retrieval",
        f"Found {_profiles(len(pool))}"
        + (f", {len(passing)} meeting every filter" if _active_filters(filters) else ""),
    )

    ranked = await _rank_with_llm(session, brief, pool, required, progress)
    ranked_by: Literal["ai", "search"] = "ai"
    if ranked is None:
        ranked_by = "search"
        ranked = [SemanticMatch(candidate=c.summary, fit=None, criteria=[]) for c in pool]

    await progress.start("filtering", "Checking the hard filters")
    by_id = {c.summary.id: c for c in pool}
    items: list[SemanticMatch] = []
    filtered_out: list[SemanticMatch] = []
    for match in ranked:
        failed = failed_filters(by_id[match.candidate.id], filters)
        if failed:
            filtered_out.append(match.model_copy(update={"failed_filters": failed}))
        else:
            items.append(match)
    items, filtered_out = items[:limit], filtered_out[:FILTERED_OUT_SIZE]
    await progress.done(
        "filtering",
        f"{len(items)} perfect match{'' if len(items) == 1 else 'es'}, "
        f"{len(filtered_out)} filtered out",
    )
    ai = ranked_by == "ai"
    return SemanticSearchResult(
        items=items,
        filtered_out=filtered_out,
        ranked_by=ranked_by,
        embedding_model=embedding_model,
        ranking_model=ranking.RANK_MODEL if ai else None,
        prompt_version=ranking.PROMPT_VERSION if ai else None,
    )
