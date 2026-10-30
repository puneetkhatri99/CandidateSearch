"""Job roles. Every route requires a signed-in staff member."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.db import SessionDep
from app.features.auth import CurrentUser
from app.features.jobs import service
from app.features.jobs.schemas import JobCreate, JobDetail, JobListParams, JobPage, JobPatch

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_job(payload: JobCreate, session: SessionDep, actor: CurrentUser) -> JobDetail:
    return await service.create_job(session, payload, actor)


@router.get("")
async def list_jobs(
    params: Annotated[JobListParams, Query()], session: SessionDep, _: CurrentUser
) -> JobPage:
    return await service.list_jobs(session, params)


@router.get("/{job_id}")
async def get_job(job_id: uuid.UUID, session: SessionDep, actor: CurrentUser) -> JobDetail:
    return await service.get_job(session, job_id, actor)


@router.patch("/{job_id}")
async def update_job(
    job_id: uuid.UUID, payload: JobPatch, session: SessionDep, actor: CurrentUser
) -> JobDetail:
    return await service.update_job(session, job_id, payload, actor)
