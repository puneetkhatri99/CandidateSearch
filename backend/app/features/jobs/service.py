import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import structlog
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.core.config import get_settings
from app.core.errors import ForbiddenError
from app.core.pagination import decode_created_at_cursor, next_created_at_cursor
from app.features.audit import AuditAction, record_event
from app.features.auth import AuthContext, get_full_names
from app.features.embeddings import get_job_embedding_status
from app.features.jobs import repository
from app.features.jobs.exceptions import (
    JobNotFoundError,
    JobValidationError,
    JobVersionConflictError,
)
from app.features.jobs.models import Job
from app.features.jobs.schemas import (
    JobCreate,
    JobDetail,
    JobFields,
    JobListParams,
    JobOwner,
    JobPage,
    JobPatch,
    JobSummary,
)
from app.features.jobs.search_document import build_job_search_document

logger = structlog.get_logger(__name__)

# The columns a user edits; copied 1:1 between the validated fields and the model.
EDITABLE_FIELDS = (
    "title",
    "department",
    "work_mode",
    "employment_type",
    "city",
    "country_code",
    "min_years",
    "max_years",
    "must_have_skills",
    "nice_to_have_skills",
    "description",
    "status",
    "salary_min",
    "salary_max",
    "salary_currency",
)


def _audit(
    session: AsyncSession,
    actor: AuthContext,
    action: AuditAction,
    job_id: uuid.UUID,
    **details: object,
) -> None:
    record_event(
        session,
        action=action,
        entity_type="job",
        entity_id=job_id,
        actor_user_id=actor.user_id,
        ip=actor.ip,
        details=dict(details),
    )


def _can_edit(job: Job, actor: AuthContext) -> bool:
    return actor.is_admin or job.created_by == actor.user_id


def _summary_fields(job: Job, owner_name: str) -> dict[str, Any]:
    # Any: a kwargs bag shared by JobSummary and JobDetail.
    return {
        "id": job.id,
        "title": job.title,
        "department": job.department,
        "status": job.status,
        "work_mode": job.work_mode,
        "employment_type": job.employment_type,
        "city": job.city,
        "country_code": job.country_code,
        "min_years": float(job.min_years),
        "max_years": None if job.max_years is None else float(job.max_years),
        "must_have_skills": job.must_have_skills,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "salary_currency": job.salary_currency,
        "created_by": JobOwner(id=job.created_by, full_name=owner_name),
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


async def _to_detail(session: AsyncSession, job: Job, actor: AuthContext) -> JobDetail:
    """Build the detail view inside the caller's transaction (it reads names and embed status)."""
    names = await get_full_names(session, [job.created_by])
    status = await get_job_embedding_status(session, job.id, get_settings().embedding_model)
    return JobDetail(
        **_summary_fields(job, names.get(job.created_by, "")),
        nice_to_have_skills=job.nice_to_have_skills,
        description=job.description,
        version=job.version,
        can_edit=_can_edit(job, actor),
        embedding_status=status,
    )


def _apply(job: Job, fields: JobFields) -> list[str]:
    """Copy validated fields onto the model; returns the names of fields that changed."""
    changed: list[str] = []
    for name in EDITABLE_FIELDS:
        value = getattr(fields, name)
        if isinstance(value, list):
            value = list(value)
        if getattr(job, name, None) != value:
            changed.append(name)
            setattr(job, name, value)
    return changed


def _stored_fields(job: Job) -> dict[str, Any]:
    # Any: field values of mixed types, fed back through JobFields for validation.
    return {name: getattr(job, name) for name in EDITABLE_FIELDS}


async def create_job(session: AsyncSession, data: JobCreate, actor: AuthContext) -> JobDetail:
    job = Job(created_by=actor.user_id, search_document="")
    _apply(job, data)
    job.search_document = build_job_search_document(data, [actor.full_name])
    try:
        async with session.begin():
            # The embedding follows on its own: the stale scan sees a document with no vector.
            await repository.add_job(session, job)
            _audit(session, actor, "job.create", job.id)
            detail = await _to_detail(session, job, actor)
    except IntegrityError as exc:
        raise _constraint_error(exc) from exc
    logger.info("job_created", job_id=str(job.id), actor_id=str(actor.user_id))
    return detail


async def list_jobs(session: AsyncSession, params: JobListParams) -> JobPage:
    after = decode_created_at_cursor(params.cursor)
    async with session.begin():
        rows = await repository.list_jobs(
            session, status=params.status, after=after, limit=params.limit
        )
        page, next_cursor = next_created_at_cursor(rows, params.limit)
        # One query for every owner on the page, not one per row.
        names = await get_full_names(session, [job.created_by for job in page])
    return JobPage(
        items=[JobSummary(**_summary_fields(job, names.get(job.created_by, ""))) for job in page],
        next_cursor=next_cursor,
    )


async def get_job(session: AsyncSession, job_id: uuid.UUID, actor: AuthContext) -> JobDetail:
    async with session.begin():
        job = await repository.get_job(session, job_id)
        if job is None:
            raise JobNotFoundError
        return await _to_detail(session, job, actor)


@dataclass(frozen=True)
class JobBrief:
    """What candidate matching needs from a job. `search_document` is redacted, so it may be
    sent to the ranking model."""

    id: uuid.UUID
    title: str
    search_document: str
    work_mode: str
    city: str | None
    country_code: str | None
    min_years: Decimal
    must_have_skills: tuple[str, ...]
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None


async def get_job_brief(session: AsyncSession, job_id: uuid.UUID) -> JobBrief:
    async with session.begin():
        job = await repository.get_job(session, job_id)
        if job is None:
            raise JobNotFoundError
        return JobBrief(
            id=job.id,
            title=job.title,
            search_document=job.search_document,
            work_mode=job.work_mode,
            city=job.city,
            country_code=job.country_code,
            min_years=job.min_years,
            must_have_skills=tuple(job.must_have_skills),
            salary_min=job.salary_min,
            salary_max=job.salary_max,
            salary_currency=job.salary_currency,
        )


def _constraint_error(exc: IntegrityError) -> JobValidationError:
    # The schema should have caught this; a database CHECK firing means the rules drifted apart.
    # Only the exception class is logged: the driver message can echo submitted values.
    logger.error("job_constraint_violated", error_type=type(exc.orig).__name__)
    return JobValidationError(
        [
            {
                "loc": ["body"],
                "msg": "Some of these values are not allowed.",
                "type": "constraint_violation",
            }
        ]
    )


def _validation_error(exc: ValidationError) -> JobValidationError:
    return JobValidationError(
        [
            {"loc": ["body", *error["loc"]], "msg": str(error["msg"]), "type": str(error["type"])}
            for error in exc.errors()
        ]
    )


async def update_job(
    session: AsyncSession, job_id: uuid.UUID, patch: JobPatch, actor: AuthContext
) -> JobDetail:
    try:
        async with session.begin():
            job = await repository.get_job(session, job_id, for_update=True)
            if job is None:
                raise JobNotFoundError
            if not _can_edit(job, actor):
                raise ForbiddenError("Only the job's creator or an admin can edit it.")
            if job.version != patch.version:
                raise JobVersionConflictError

            merged = _stored_fields(job) | patch.model_dump(exclude_unset=True, exclude={"version"})
            try:
                fields = JobFields.model_validate(merged)
            except ValidationError as exc:
                raise _validation_error(exc) from exc

            # Queries autoflush, so everything is read before the first attribute changes;
            # otherwise one edit would be written (and versioned) twice.
            owner = await get_full_names(session, [job.created_by])
            names = [actor.full_name, owner.get(job.created_by, "")]
            document = build_job_search_document(fields, names)
            changed = _apply(job, fields)
            # A new document is re-embedded by the stale scan; a status-only edit changes nothing.
            job.search_document = document
            await session.flush()
            if changed:
                # Field names only: the audit log records what changed, not the values.
                _audit(
                    session, actor, "job.update", job.id, changed_fields=changed, status=job.status
                )
            detail = await _to_detail(session, job, actor)
    except StaleDataError as exc:
        raise JobVersionConflictError from exc
    except IntegrityError as exc:
        raise _constraint_error(exc) from exc
    logger.info("job_updated", job_id=str(job_id), actor_id=str(actor.user_id))
    return detail
