import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import structlog
from sqlalchemy import Select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.core import storage
from app.core.errors import ForbiddenError, NotFoundError
from app.core.pagination import decode_created_at_cursor, next_created_at_cursor
from app.features.audit import AuditAction, record_event
from app.features.auth import AuthContext, get_full_names
from app.features.candidates import repository
from app.features.candidates.exceptions import CandidateAlreadyExistsError, VersionConflictError
from app.features.candidates.models import (
    EMAIL_UNIQUE_CONSTRAINT,
    Candidate,
    CandidateEducation,
    CandidateExperience,
)
from app.features.candidates.schemas import (
    Bookmark,
    BookmarkList,
    CandidateCreate,
    CandidateCreated,
    CandidateDetail,
    CandidatePage,
    CandidateProfile,
    CandidateSearchParams,
    CandidateSummary,
    CandidateUpdate,
    EducationOut,
    ExperienceOut,
    StaffCandidateCreate,
)
from app.features.candidates.search_document import build_search_document

logger = structlog.get_logger(__name__)

TOP_SKILLS = 5
# Recorded by name only in candidate.search audit events.
SEARCH_FILTER_FIELDS = ("country", "min_years", "skill", "city", "source")
# Scalar profile fields copied 1:1 from a CandidateProfile onto the model.
_PROFILE_FIELDS = (
    "full_name",
    "email",
    "phone",
    "city",
    "country_code",
    "linkedin_url",
    "github_url",
    "portfolio_url",
    "headline",
    "years_experience",
    "summary",
    "skills",
    "desired_roles",
    "work_modes",
    "open_to_relocation",
    "notice_period_days",
    "expected_salary",
    "salary_currency",
)
_DUPLICATE_EMAIL_MESSAGE = (
    "A profile with this email already exists. Contact us if you need to update it."
)


def _experiences(profile: CandidateProfile) -> list[CandidateExperience]:
    return [
        CandidateExperience(
            company=e.company,
            title=e.title,
            start_month=e.start_month,
            end_month=e.end_month,
            is_current=e.is_current,
            description=e.description,
            position=i,
        )
        for i, e in enumerate(profile.experiences)
    ]


def _educations(profile: CandidateProfile) -> list[CandidateEducation]:
    return [
        CandidateEducation(
            institution=e.institution,
            degree=e.degree,
            field_of_study=e.field_of_study,
            start_year=e.start_year,
            end_year=e.end_year,
            position=i,
        )
        for i, e in enumerate(profile.educations)
    ]


_EXPERIENCE_FIELDS = ("company", "title", "start_month", "end_month", "is_current", "description")
_EDUCATION_FIELDS = ("institution", "degree", "field_of_study", "start_year", "end_year")


def _rows(rows: Sequence[object], fields: tuple[str, ...]) -> list[tuple[object, ...]]:
    return [tuple(getattr(row, field) for field in fields) for row in rows]


def _apply_profile(candidate: Candidate, profile: CandidateProfile) -> list[str]:
    """Copy every profile field onto the model; returns the names of fields that changed."""
    changed: list[str] = []
    for field in _PROFILE_FIELDS:
        value = getattr(profile, field)
        if field == "work_modes":
            value = list(value)
        if getattr(candidate, field, None) != value:
            changed.append(field)
            setattr(candidate, field, value)
    children = (
        ("experiences", _experiences(profile), _EXPERIENCE_FIELDS),
        ("educations", _educations(profile), _EDUCATION_FIELDS),
    )
    for name, new_rows, fields in children:
        # Replaced only when they differ, so an unrelated edit doesn't rewrite every child row.
        if _rows(getattr(candidate, name), fields) != _rows(new_rows, fields):
            changed.append(name)
            setattr(candidate, name, new_rows)
    candidate.search_document = build_search_document(profile)
    return changed


def _new_candidate(
    profile: CandidateCreate | StaffCandidateCreate,
    *,
    consent_version: str,
    source: str,
    source_ref: str | None,
    consent_recorded_by: uuid.UUID | None = None,
) -> Candidate:
    candidate = Candidate(
        source=source,
        source_ref=source_ref,
        consent_given_at=datetime.now(UTC),
        consent_version=consent_version,
        consent_recorded_by=consent_recorded_by,
        resume_ref=profile.resume_ref,
    )
    _apply_profile(candidate, profile)
    return candidate


def _is_duplicate_email(exc: IntegrityError) -> bool:
    return EMAIL_UNIQUE_CONSTRAINT in str(exc.orig)


def _audit(
    session: AsyncSession,
    actor: AuthContext,
    action: AuditAction,
    candidate_id: uuid.UUID,
    **details: object,
) -> None:
    record_event(
        session,
        action=action,
        entity_type="candidate",
        entity_id=candidate_id,
        actor_user_id=actor.user_id,
        ip=actor.ip,
        details=dict(details),
    )


def to_detail(candidate: Candidate) -> CandidateDetail:
    return CandidateDetail(
        id=candidate.id,
        version=candidate.version,
        full_name=candidate.full_name,
        email=candidate.email,
        phone=candidate.phone,
        city=candidate.city,
        country_code=candidate.country_code,
        linkedin_url=candidate.linkedin_url,
        github_url=candidate.github_url,
        portfolio_url=candidate.portfolio_url,
        headline=candidate.headline,
        years_experience=float(candidate.years_experience),
        skills=candidate.skills,
        summary=candidate.summary,
        experiences=[
            ExperienceOut(
                company=e.company,
                title=e.title,
                start_month=e.start_month.strftime("%Y-%m"),
                is_current=e.is_current,
                end_month=e.end_month.strftime("%Y-%m") if e.end_month else None,
                description=e.description,
            )
            for e in candidate.experiences
        ],
        educations=[
            EducationOut(
                institution=e.institution,
                degree=e.degree,
                field_of_study=e.field_of_study,
                start_year=e.start_year,
                end_year=e.end_year,
            )
            for e in candidate.educations
        ],
        desired_roles=candidate.desired_roles,
        work_modes=candidate.work_modes,
        open_to_relocation=candidate.open_to_relocation,
        notice_period_days=candidate.notice_period_days,
        expected_salary=candidate.expected_salary,
        salary_currency=candidate.salary_currency,
        source=candidate.source,
        consent_given_at=candidate.consent_given_at,
        consent_version=candidate.consent_version,
        has_resume=candidate.resume_ref is not None,
        created_at=candidate.created_at,
        updated_at=candidate.updated_at,
    )


def _to_summary(candidate: Candidate) -> CandidateSummary:
    return CandidateSummary(
        id=candidate.id,
        full_name=candidate.full_name,
        email=candidate.email,
        headline=candidate.headline,
        city=candidate.city,
        country_code=candidate.country_code,
        years_experience=float(candidate.years_experience),
        top_skills=candidate.skills[:TOP_SKILLS],
        expected_salary=candidate.expected_salary,
        salary_currency=candidate.salary_currency,
        source=candidate.source,
        created_at=candidate.created_at,
    )


# --- Public intake -----------------------------------------------------------------------


async def create_candidate(
    session: AsyncSession,
    data: CandidateCreate,
    *,
    consent_version: str,
    source: str = "manual",
    source_ref: str | None = None,
) -> CandidateCreated:
    if data.website:
        # Honeypot tripped: pretend success so bots can't tell they were filtered.
        logger.warning("candidate_honeypot_triggered", source=source)
        return CandidateCreated(id=uuid.uuid4(), created_at=datetime.now(UTC))

    candidate = _new_candidate(
        data, consent_version=consent_version, source=source, source_ref=source_ref
    )
    try:
        # The embedding follows on its own: the stale scan sees a document with no vector.
        async with session.begin():
            await repository.add_candidate(session, candidate)
    except IntegrityError as exc:
        # The UNIQUE constraint is the source of truth, so concurrent submits can't race.
        if _is_duplicate_email(exc):
            raise CandidateAlreadyExistsError(_DUPLICATE_EMAIL_MESSAGE) from exc
        raise

    logger.info("candidate_created", candidate_id=str(candidate.id), source=source)
    return CandidateCreated(id=candidate.id, created_at=candidate.created_at)


# --- Staff management --------------------------------------------------------------------


async def search_candidates(
    session: AsyncSession, params: CandidateSearchParams, actor: AuthContext
) -> CandidatePage:
    after = decode_created_at_cursor(params.cursor)
    async with session.begin():
        rows = await repository.search_candidates(session, params, after)
        page, next_cursor = next_created_at_cursor(rows, params.limit)
        # Results show names and emails, so a search is audited like a view: in the same
        # transaction (no audit, no results). Only which filters were used is recorded, never
        # their values or the ids returned.
        record_event(
            session,
            action="candidate.search",
            entity_type="candidate",
            entity_id=None,
            actor_user_id=actor.user_id,
            ip=actor.ip,
            details={
                "filters": sorted(
                    name for name in SEARCH_FILTER_FIELDS if getattr(params, name) is not None
                ),
                "cursor_page": params.cursor is not None,
                "limit": params.limit,
                "result_count": len(page),
            },
        )
    return CandidatePage(items=[_to_summary(c) for c in page], next_cursor=next_cursor)


async def get_candidate(
    session: AsyncSession, candidate_id: uuid.UUID, actor: AuthContext
) -> CandidateDetail:
    async with session.begin():
        candidate = await repository.get_candidate(session, candidate_id)
        if candidate is None:
            raise NotFoundError("Candidate not found.")
        # Viewing PII is itself an auditable act.
        _audit(session, actor, "candidate.view", candidate.id)
        return to_detail(candidate)


async def create_candidate_by_staff(
    session: AsyncSession, data: StaffCandidateCreate, actor: AuthContext, *, consent_version: str
) -> CandidateDetail:
    candidate = _new_candidate(
        data,
        consent_version=consent_version,
        source="admin",
        source_ref=None,
        consent_recorded_by=actor.user_id,
    )
    try:
        async with session.begin():
            await repository.add_candidate(session, candidate)
            _audit(session, actor, "candidate.create", candidate.id)
    except IntegrityError as exc:
        if _is_duplicate_email(exc):
            raise CandidateAlreadyExistsError("A profile with this email already exists.") from exc
        raise
    logger.info("candidate_created", candidate_id=str(candidate.id), source="admin")
    return to_detail(candidate)


async def update_candidate(
    session: AsyncSession, candidate_id: uuid.UUID, data: CandidateUpdate, actor: AuthContext
) -> CandidateDetail:
    try:
        async with session.begin():
            candidate = await repository.get_candidate(session, candidate_id, for_update=True)
            if candidate is None:
                raise NotFoundError("Candidate not found.")
            if candidate.version != data.version:
                raise VersionConflictError(
                    "This profile was changed by someone else. Reload to see the latest version."
                )
            # A changed search document is re-embedded by the stale scan; nothing to queue here.
            changed = _apply_profile(candidate, data)
            # Any profile change makes the stored resume PDF stale (user decision): the next
            # "See resume" fetches a fresh one.
            stale_pdf = candidate.resume_pdf_key if changed else None
            if stale_pdf is not None:
                candidate.resume_pdf_key = None
            await session.flush()
            # Field names only: the audit log must not hold personal data.
            _audit(session, actor, "candidate.update", candidate.id, changed_fields=changed)
    except IntegrityError as exc:
        if _is_duplicate_email(exc):
            raise CandidateAlreadyExistsError("A profile with this email already exists.") from exc
        raise
    except StaleDataError as exc:
        raise VersionConflictError(
            "This profile was changed by someone else. Reload to see the latest version."
        ) from exc
    await storage.discard(stale_pdf)
    logger.info("candidate_updated", candidate_id=str(candidate_id))
    return to_detail(candidate)


async def delete_candidate(
    session: AsyncSession, candidate_id: uuid.UUID, actor: AuthContext
) -> None:
    if not actor.is_admin:
        raise ForbiddenError("Only admins can delete candidates.")
    async with session.begin():
        deleted, pdf_key = await repository.delete_candidate(session, candidate_id)
        if not deleted:
            raise NotFoundError("Candidate not found.")
        _audit(session, actor, "candidate.delete", candidate_id)
    await storage.discard(pdf_key)
    logger.info("candidate_deleted", candidate_id=str(candidate_id))


# --- Resumes (the files live in ResumeAI; features/resumes calls it) -------------------------


async def get_resume_ref(session: AsyncSession, candidate_id: uuid.UUID) -> uuid.UUID | None:
    """The candidate's ResumeAI reference (None when no resume is attached). 404 for an unknown
    candidate. Viewing the resume goes through open_resume, which is audited."""
    async with session.begin():
        candidate = await repository.get_candidate_row(session, candidate_id)
        if candidate is None:
            raise NotFoundError("Candidate not found.")
        return candidate.resume_ref


@dataclass(frozen=True)
class OpenedResume:
    """What "See resume" needs: ResumeAI's ref, the stored PDF (if any), and the profile version
    it must still match when a freshly fetched PDF is recorded."""

    resume_ref: uuid.UUID
    pdf_key: str | None
    version: int


async def open_resume(
    session: AsyncSession, candidate_id: uuid.UUID, actor: AuthContext
) -> OpenedResume | None:
    """None when no resume is attached; 404 for an unknown candidate. Audited as a view."""
    async with session.begin():
        candidate = await repository.get_candidate_row(session, candidate_id)
        if candidate is None:
            raise NotFoundError("Candidate not found.")
        if candidate.resume_ref is None:
            return None
        _audit(session, actor, "candidate.resume_view", candidate_id)
        return OpenedResume(candidate.resume_ref, candidate.resume_pdf_key, candidate.version)


async def record_resume_pdf(
    session: AsyncSession, candidate_id: uuid.UUID, key: str, opened: OpenedResume
) -> bool:
    """Point the candidate at a newly stored PDF. False when the resume or profile changed
    meanwhile (or another view stored one first); the caller then deletes its file."""
    async with session.begin():
        return await repository.set_resume_pdf_key(
            session,
            candidate_id,
            key,
            resume_ref=opened.resume_ref,
            version=opened.version,
            replacing=opened.pdf_key,
        )


async def attach_resume(
    session: AsyncSession, candidate_id: uuid.UUID, resume_ref: uuid.UUID, actor: AuthContext
) -> None:
    """Link a resume ResumeAI has stored to the candidate. Profile fields stay as they are; a
    stored PDF of the old resume is removed."""
    async with session.begin():
        found, stale_pdf = await repository.lock_resume_pdf_key(session, candidate_id)
        if not found or not await repository.set_resume_ref(session, candidate_id, resume_ref):
            raise NotFoundError("Candidate not found.")
        _audit(session, actor, "candidate.resume_attach", candidate_id)
    await storage.discard(stale_pdf)


# --- Bookmarks (one list shared by the team) ------------------------------------------------


async def bookmark_candidate(
    session: AsyncSession, candidate_id: uuid.UUID, actor: AuthContext
) -> None:
    try:
        async with session.begin():
            if await repository.add_bookmark(session, candidate_id, actor.user_id):
                _audit(session, actor, "candidate.bookmark", candidate_id)
    except IntegrityError as exc:
        # The conflict on candidate_id is ignored, so only the foreign key can fail: the
        # candidate doesn't exist (or was deleted meanwhile).
        raise NotFoundError("Candidate not found.") from exc


async def unbookmark_candidate(
    session: AsyncSession, candidate_id: uuid.UUID, actor: AuthContext
) -> None:
    async with session.begin():
        if await repository.remove_bookmark(session, candidate_id):
            _audit(session, actor, "candidate.unbookmark", candidate_id)


async def list_bookmarks(session: AsyncSession, actor: AuthContext) -> BookmarkList:
    # shortcut: unpaged, fine for a few hundred bookmarks; page it with the created_at cursor
    # helpers when lists grow.
    async with session.begin():
        rows = await repository.list_bookmarks(session)
        names = await get_full_names(session, list({bookmark.added_by for bookmark, _ in rows}))
        # Lists names and emails, so it is audited like a search.
        record_event(
            session,
            action="candidate.search",
            entity_type="candidate",
            entity_id=None,
            actor_user_id=actor.user_id,
            ip=actor.ip,
            details={"filters": ["bookmarked"], "result_count": len(rows)},
        )
    return BookmarkList(
        items=[
            Bookmark(
                candidate=_to_summary(candidate),
                added_by_name=names.get(bookmark.added_by, "Unknown user"),
                added_at=bookmark.created_at,
            )
            for bookmark, candidate in rows
        ]
    )


# --- For features that rank candidates (semantic search) -----------------------------------


@dataclass(frozen=True)
class RankableCandidate:
    """What a ranker may judge: the summary, plus the redacted profile and the structured facts
    code rules need (location, work modes). Never the name or contact details."""

    summary: CandidateSummary
    profile_text: str
    city: str
    country_code: str
    years_experience: float
    skills: tuple[str, ...]
    work_modes: tuple[str, ...]
    open_to_relocation: bool | None
    expected_salary: int | None
    salary_currency: str | None
    # Changes on every edit, so a cached ranking of this profile can tell it is stale.
    updated_at: datetime


async def get_rankable_candidates(
    session: AsyncSession, candidate_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, RankableCandidate]:
    """Keyed by id; ids of deleted candidates are simply absent."""
    async with session.begin():
        found = await repository.get_candidates_by_ids(session, list(candidate_ids))
        return {
            candidate.id: RankableCandidate(
                summary=_to_summary(candidate),
                profile_text=candidate.search_document,
                city=candidate.city,
                country_code=candidate.country_code,
                years_experience=float(candidate.years_experience),
                skills=tuple(candidate.skills),
                work_modes=tuple(candidate.work_modes),
                open_to_relocation=candidate.open_to_relocation,
                expected_salary=candidate.expected_salary,
                salary_currency=candidate.salary_currency,
                updated_at=candidate.updated_at,
            )
            for candidate in found
        }


async def full_text_candidate_ids(
    session: AsyncSession,
    query: str,
    *,
    count: int,
    within: Select[uuid.UUID] | None = None,
) -> list[uuid.UUID]:
    """Best keyword matches first (profile text and city), optionally only among `within`."""
    async with session.begin():
        return await repository.full_text_candidate_ids(session, query, count, within)


async def rebuild_search_documents(session: AsyncSession) -> int:
    """Rewrite every profile's document after its format changes; returns how many changed.
    Their hash then differs from the stored embedding's, so embedding picks them up as stale."""
    async with session.begin():
        changed = 0
        for candidate in await repository.list_candidates_with_children(session):
            # Already validated when saved; only the attributes the document reads are needed.
            fields = (*_PROFILE_FIELDS, "experiences", "educations")
            profile = CandidateProfile.model_construct(
                **{field: getattr(candidate, field) for field in fields}
            )
            document = build_search_document(profile)
            if document != candidate.search_document:
                await repository.set_search_document(session, candidate.id, document)
                changed += 1
        return changed


def candidate_ids_passing(
    *,
    min_years: Decimal | None,
    skills: Sequence[str],
    city: str | None,
    country: str | None,
    source: str | None,
    max_salary: int | None = None,
    salary_currency: str | None = None,
) -> Select[uuid.UUID]:
    """A subquery of the candidates meeting every hard filter; other features pass it to their
    own queries (embeddings' nearest search, the full-text search) to search only among them."""
    return repository.ids_passing(
        min_years=min_years,
        skills=skills,
        city=city,
        country=country,
        source=source,
        max_salary=max_salary,
        salary_currency=salary_currency,
    )
