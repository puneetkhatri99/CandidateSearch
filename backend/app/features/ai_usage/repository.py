import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import and_, desc, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.features.ai_usage.models import AiBudget, AiUsageEvent
from app.features.ai_usage.schemas import UsageTotals


async def get_budget(session: AsyncSession) -> AiBudget | None:
    return (
        await session.execute(select(AiBudget).order_by(AiBudget.created_at).limit(1))
    ).scalar_one_or_none()


async def add_budget(session: AsyncSession, limit_usd: Decimal) -> AiBudget:
    budget = AiBudget(limit_usd=limit_usd)
    session.add(budget)
    await session.flush()
    return budget


async def get_spent(session: AsyncSession) -> Decimal:
    # Blocked events cost 0, and a failed one costs 0 unless the provider billed a response we
    # could not use, so summing every row is the spend.
    spent = await session.scalar(select(func.sum(AiUsageEvent.cost_usd)))
    return spent if isinstance(spent, Decimal) else Decimal(0)


async def add_event(session: AsyncSession, event: AiUsageEvent) -> None:
    session.add(event)
    await session.flush()


async def totals_by(session: AsyncSession, column: InstrumentedAttribute[str]) -> list[UsageTotals]:
    """Billed requests only (succeeded, or failed with a cost), so rows add up to the spend."""
    rows = await session.execute(
        select(
            column,
            func.count(),
            func.coalesce(func.sum(AiUsageEvent.input_tokens), 0),
            func.coalesce(func.sum(AiUsageEvent.output_tokens), 0),
            func.coalesce(func.sum(AiUsageEvent.cost_usd), Decimal(0)),
        )
        .where(
            or_(
                AiUsageEvent.status == "succeeded",
                and_(AiUsageEvent.status == "failed", AiUsageEvent.cost_usd > 0),
            )
        )
        .group_by(column)
        .order_by(desc(func.sum(AiUsageEvent.cost_usd)), column)
    )
    return [
        UsageTotals(key=key, requests=count, input_tokens=inp, output_tokens=out, cost_usd=cost)
        for key, count, inp, out, cost in rows.all()
    ]


async def list_events(
    session: AsyncSession,
    *,
    model: str | None,
    operation: str | None,
    status: str | None,
    after: tuple[datetime, uuid.UUID] | None,
    limit: int,
) -> list[AiUsageEvent]:
    """Newest first. Fetches one extra row so the caller can tell whether another page exists."""
    query = select(AiUsageEvent)
    if model:
        query = query.where(AiUsageEvent.model == model)
    if operation:
        query = query.where(AiUsageEvent.operation == operation)
    if status:
        query = query.where(AiUsageEvent.status == status)
    if after:
        created_at, event_id = after
        query = query.where(
            tuple_(AiUsageEvent.created_at, AiUsageEvent.id) < tuple_(created_at, event_id)
        )
    query = query.order_by(AiUsageEvent.created_at.desc(), AiUsageEvent.id.desc()).limit(limit + 1)
    return list((await session.execute(query)).scalars())
