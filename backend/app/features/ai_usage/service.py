"""AI spend metering: check the budget, make the call, then record what it cost.

Every function that takes a `session` expects one that is NOT already in a transaction; each
step opens its own, so the provider call never holds a database transaction.
"""

from collections.abc import Awaitable, Callable
from decimal import Decimal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai_pricing import UnknownModelPriceError, compute_cost_usd, get_model_price
from app.core.errors import ForbiddenError, describe_error
from app.core.pagination import decode_created_at_cursor, next_created_at_cursor
from app.features.ai_usage import repository
from app.features.ai_usage.exceptions import BudgetExceededError
from app.features.ai_usage.models import AiBudget, AiUsageEvent
from app.features.ai_usage.schemas import (
    BudgetSummary,
    BudgetUpdate,
    UsageEventOut,
    UsageEventPage,
    UsageEventParams,
)
from app.features.audit import record_event
from app.features.auth import AuthContext

logger = structlog.get_logger(__name__)

DEFAULT_LIMIT_USD = Decimal("5.00")
_CENT = Decimal("0.01")


def _billed(exc: BaseException, attribute: str) -> int:
    # A negative count would be a credit that frees budget; treat it as nothing billed.
    value = getattr(exc, attribute, None)
    return value if isinstance(value, int) and value > 0 else 0


async def _ensure_budget(session: AsyncSession) -> AiBudget:
    """The migration seeds the row; this covers a database that was truncated or restored."""
    budget = await repository.get_budget(session)
    if budget is None:
        budget = await repository.add_budget(session, DEFAULT_LIMIT_USD)
    return budget


# --- Metering ----------------------------------------------------------------------------


async def _refusal(session: AsyncSession, model: str) -> Exception | None:
    """Why a call to `model` may not run now, or None. Runs in the caller's transaction."""
    budget = await _ensure_budget(session)
    try:
        get_model_price(model)
    except UnknownModelPriceError as exc:
        return exc
    if await repository.get_spent(session) >= budget.limit_usd:
        return BudgetExceededError("The AI spending limit has been reached.")
    return None


async def metered_call[T](
    session: AsyncSession,
    *,
    provider: str,
    model: str,
    operation: str,
    trigger: str,
    item_count: int,
    call: Callable[[], Awaitable[T]],
    tokens_of: Callable[[T], tuple[int, int]],
) -> T:
    """Refuse when the budget is used up, otherwise run `call` and record its real cost.

    `tokens_of` returns the (input, output) tokens the provider billed for the result.

    A refusal is recorded as a `blocked` event and raised (BudgetExceededError, or
    UnknownModelPriceError for a model with no price); `call` is then never invoked.

    shortcut: checking and recording are not atomic, so callers running at the same moment can
    each pass the check and overshoot the limit by one call (at most about $0.01 for a
    64-input embedding batch). A call cancelled mid-flight is not recorded. Both are fine for
    one worker plus staff searches; reserve the cost up front if many workers share a budget.
    """

    def event(
        status: str, *, input_tokens: int = 0, output_tokens: int = 0, error: str | None = None
    ) -> AiUsageEvent:
        billed = input_tokens or output_tokens
        return AiUsageEvent(
            provider=provider,
            model=model,
            operation=operation,
            trigger=trigger,
            item_count=item_count,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=compute_cost_usd(model, input_tokens, output_tokens) if billed else Decimal(0),
            status=status,
            error=error,
        )

    async with session.begin():
        refusal = await _refusal(session, model)
        if refusal is not None:
            await repository.add_event(session, event("blocked", error=type(refusal).__name__))
    if refusal is not None:
        logger.warning("ai_call_blocked", model=model, operation=operation)
        raise refusal

    try:
        result = await call()
    except Exception as exc:
        # A 200 with an unusable body is still billed; the error says how many tokens.
        failed = event(
            "failed",
            input_tokens=_billed(exc, "billed_tokens"),
            output_tokens=_billed(exc, "billed_output_tokens"),
            error=describe_error(exc),
        )
        async with session.begin():
            await repository.add_event(session, failed)
        logger.warning("ai_call_failed", model=model, operation=operation, error=failed.error)
        raise

    input_tokens, output_tokens = tokens_of(result)
    succeeded = event("succeeded", input_tokens=input_tokens, output_tokens=output_tokens)
    async with session.begin():
        await repository.add_event(session, succeeded)
    logger.info(
        "ai_call_recorded",
        model=model,
        operation=operation,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=str(succeeded.cost_usd),
    )
    return result


async def budget_used_up(session: AsyncSession) -> bool:
    """Whether spend has reached the limit. Runs in the caller's transaction."""
    budget = await repository.get_budget(session)
    spent = await repository.get_spent(session)
    return spent >= (budget.limit_usd if budget else DEFAULT_LIMIT_USD)


async def has_budget(session: AsyncSession) -> bool:
    """True while the spend is below the limit. Callers use it to skip work that would only be
    refused; `metered_call` still does the authoritative check."""
    async with session.begin():
        return not await budget_used_up(session)


# --- Staff views -------------------------------------------------------------------------


async def get_summary(session: AsyncSession) -> BudgetSummary:
    async with session.begin():
        budget = await repository.get_budget(session)
        spent = await repository.get_spent(session)
        by_model = await repository.totals_by(session, AiUsageEvent.model)
        by_operation = await repository.totals_by(session, AiUsageEvent.operation)

    limit = budget.limit_usd if budget else DEFAULT_LIMIT_USD
    return BudgetSummary(
        limit_usd=limit,
        spent_usd=spent,
        remaining_usd=max(limit - spent, Decimal(0)),
        percent_used=float(spent / limit * 100) if limit > 0 else 100.0,
        limit_reached=spent >= limit,
        updated_at=budget.updated_at if budget else None,
        by_model=by_model,
        by_operation=by_operation,
    )


async def list_events(session: AsyncSession, params: UsageEventParams) -> UsageEventPage:
    after = decode_created_at_cursor(params.cursor)
    async with session.begin():
        rows = await repository.list_events(
            session,
            model=params.model,
            operation=params.operation,
            status=params.status,
            after=after,
            limit=params.limit,
        )
    page, next_cursor = next_created_at_cursor(rows, params.limit)
    return UsageEventPage(
        items=[UsageEventOut.model_validate(event) for event in page], next_cursor=next_cursor
    )


async def update_budget(
    session: AsyncSession, data: BudgetUpdate, actor: AuthContext
) -> BudgetSummary:
    if not actor.is_admin:
        raise ForbiddenError("Only admins can change the AI spending limit.")
    new_limit = data.limit_usd.quantize(_CENT)
    async with session.begin():
        budget = await _ensure_budget(session)
        old_limit = budget.limit_usd
        if new_limit != old_limit:
            budget.limit_usd = new_limit
            budget.updated_by = actor.user_id
        # Limits are not personal data; strings keep the exact decimal in the JSON details.
        record_event(
            session,
            action="ai_budget.update",
            entity_type="ai_budget",
            entity_id=budget.id,
            actor_user_id=actor.user_id,
            ip=actor.ip,
            details={"old_limit_usd": str(old_limit), "new_limit_usd": str(new_limit)},
        )
    logger.info("ai_budget_updated", actor_user_id=str(actor.user_id))
    return await get_summary(session)
