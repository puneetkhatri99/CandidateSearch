"""Read the place and years a search states, so those people are fetched first.

What comes back only changes who reaches the ranking. It never removes anyone from the results;
that stays the job of the filters a recruiter sets.
"""

import asyncio
import time
from collections import OrderedDict
from pathlib import Path

import structlog
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm import LLMError, get_llm_client
from app.features import ai_usage
from app.features.semantic_search.ranking import RANK_MODEL
from app.features.semantic_search.schemas import HardFilters

logger = structlog.get_logger(__name__)

PROMPT_VERSION = "understand_v1"
INSTRUCTIONS = (Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.md").read_text("utf-8")
OPERATION = "search_understand"
# Includes the model's reasoning tokens, so more than these few fields alone would need.
MAX_OUTPUT_TOKENS = 1_000
TIMEOUT_SECONDS = 10.0
CACHE_SIZE = 256
CACHE_SECONDS = 600.0


class QueryFacts(BaseModel):
    city: str | None
    country_code: str | None
    min_years: float | None


# A different answer to a repeated search would change the pool and so pay for a new ranking.
_cache: OrderedDict[str, tuple[float, HardFilters]] = OrderedDict()


def clear_understanding_cache() -> None:
    _cache.clear()


async def understand_query(session: AsyncSession, query: str) -> HardFilters | None:
    """The facts the search states, or None when nothing could be read; the search then runs
    without them. The answer is checked like a recruiter's own filters, since it comes from
    outside this code."""
    key = f"{RANK_MODEL}:{PROMPT_VERSION}:{query.casefold()}"
    entry = _cache.get(key)
    if entry is not None and time.monotonic() - entry[0] <= CACHE_SECONDS:
        _cache.move_to_end(key)
        return entry[1]
    try:
        client = get_llm_client()
        result = await ai_usage.metered_call(
            session,
            provider=client.provider_name,
            model=RANK_MODEL,
            operation=OPERATION,
            trigger="api",
            item_count=1,
            # The timeout wraps only the call, so a slow answer is recorded as a failed event.
            call=lambda: asyncio.wait_for(
                client.parse(
                    model=RANK_MODEL,
                    instructions=INSTRUCTIONS,
                    content=f"Search: {query}",
                    schema=QueryFacts,
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                ),
                timeout=TIMEOUT_SECONDS,
            ),
            tokens_of=lambda r: (r.input_tokens, r.output_tokens),
        )
        facts = result.parsed
        understood = HardFilters(
            city=facts.city, country=facts.country_code, min_years=facts.min_years
        )
    except (
        LLMError,
        TimeoutError,
        ValidationError,
        ai_usage.BudgetExceededError,
        ai_usage.UnknownModelPriceError,
    ) as exc:
        logger.warning("semantic_search_understanding_failed", error_type=type(exc).__name__)
        return None
    _cache[key] = (time.monotonic(), understood)
    if len(_cache) > CACHE_SIZE:
        _cache.popitem(last=False)
    return understood
