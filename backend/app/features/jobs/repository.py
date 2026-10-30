import uuid
from datetime import datetime

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.jobs.models import Job


async def add_job(session: AsyncSession, job: Job) -> None:
    """Insert the job; flush so DB errors surface here and server defaults are loaded."""
    session.add(job)
    await session.flush()


async def get_job(
    session: AsyncSession, job_id: uuid.UUID, *, for_update: bool = False
) -> Job | None:
    statement = select(Job).where(Job.id == job_id)
    if for_update:
        statement = statement.with_for_update()
    return await session.scalar(statement)


async def list_jobs(
    session: AsyncSession,
    *,
    status: str | None,
    after: tuple[datetime, uuid.UUID] | None,
    limit: int,
) -> list[Job]:
    """Newest first. Fetches one extra row so the caller can tell whether another page exists."""
    statement = select(Job)
    if status:
        statement = statement.where(Job.status == status)
    if after is not None:
        statement = statement.where(tuple_(Job.created_at, Job.id) < tuple_(*after))
    statement = statement.order_by(Job.created_at.desc(), Job.id.desc()).limit(limit + 1)
    return list((await session.scalars(statement)).all())
