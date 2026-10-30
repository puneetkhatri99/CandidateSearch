"""Staff-only AI spend views. Recruiters can read; only admins can change the limit."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.core.db import SessionDep
from app.features.ai_usage import service
from app.features.ai_usage.schemas import (
    BudgetSummary,
    BudgetUpdate,
    UsageEventPage,
    UsageEventParams,
)
from app.features.auth import AdminUser, CurrentUser

router = APIRouter(prefix="/ai-usage", tags=["ai usage"])


@router.get("/summary")
async def get_summary(session: SessionDep, _: CurrentUser) -> BudgetSummary:
    return await service.get_summary(session)


@router.get("/events")
async def list_events(
    params: Annotated[UsageEventParams, Query()], session: SessionDep, _: CurrentUser
) -> UsageEventPage:
    return await service.list_events(session, params)


@router.put("/budget")
async def update_budget(
    payload: BudgetUpdate, session: SessionDep, actor: AdminUser
) -> BudgetSummary:
    return await service.update_budget(session, payload, actor)
