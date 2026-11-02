import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ColumnElement, Select, Text, cast, delete, func, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.features.candidates.models import Candidate, CandidateBookmark
from app.features.candidates.schemas import CandidateSearchParams
from app.shared.aliases import city_spellings, skill_spellings
from app.shared.validation import split_tags


async def add_candidate(session: AsyncSession, candidate: Candidate) -> None:
    """Insert the candidate and its child rows; flush so DB errors surface here."""
    session.add(candidate)
    await session.flush()


def hard_filter_clauses(
    *,
    min_years: Decimal | None = None,
    skills: Sequence[str] = (),
    city: str | None = None,
    country: str | None = None,
    source: str | None = None,
    max_salary: int | None = None,
    salary_currency: str | None = None,
) -> list[ColumnElement[bool]]:
    """The hard filters as SQL. semantic_search.failed_filters checks the same rules in
    Python; change both together."""
    clauses: list[ColumnElement[bool]] = []
    if min_years is not None:
        clauses.append(Candidate.years_experience >= min_years)
    for skill in skills:
        # Any spelling of each required skill ("postgres" is met by "postgresql").
        clauses.append(Candidate.skills.overlap(sorted(skill_spellings(skill))))
    if city:
        # shortcut: unindexed lower(city) scan, fine for ~1,000 rows; add an index around 100k.
        clauses.append(func.lower(Candidate.city).in_(sorted(city_spellings(city))))
    if country:
        clauses.append(Candidate.country_code == country)
    if source:
        clauses.append(Candidate.source == source)
    if max_salary is not None and salary_currency:
        # Only a stated salary in the same currency can be over budget (user decision: no
        # salary counts as within; another currency can't be compared without exchange rates).
        clauses.append(
            or_(
                Candidate.expected_salary.is_(None),
                Candidate.salary_currency != salary_currency,
                Candidate.expected_salary <= max_salary,
            )
        )
    return clauses


def ids_passing(
    *,
    min_years: Decimal | None,
    skills: Sequence[str],
    city: str | None,
    country: str | None,
    source: str | None,
    max_salary: int | None = None,
    salary_currency: str | None = None,
) -> Select[uuid.UUID]:
    """Ids of candidates meeting every hard filter, as a subquery for other searches."""
    clauses = hard_filter_clauses(
        min_years=min_years,
        skills=skills,
        city=city,
        country=country,
        source=source,
        max_salary=max_salary,
        salary_currency=salary_currency,
    )
    return select(Candidate.id).where(*clauses)


async def search_candidates(
    session: AsyncSession,
    params: CandidateSearchParams,
    after: tuple[datetime, uuid.UUID] | None,
) -> list[Candidate]:
    """Newest first, meeting every hard filter. Fetches one extra row so the caller can tell
    whether another page exists."""
    statement = select(Candidate).where(
        *hard_filter_clauses(
            min_years=params.min_years,
            skills=split_tags(params.skill),
            city=params.city,
            country=params.country,
            source=params.source,
        )
    )
    if after is not None:
        statement = statement.where(tuple_(Candidate.created_at, Candidate.id) < tuple_(*after))
    statement = statement.order_by(Candidate.created_at.desc(), Candidate.id.desc())
    return list((await session.scalars(statement.limit(params.limit + 1))).all())


async def get_candidate(
    session: AsyncSession, candidate_id: uuid.UUID, *, for_update: bool = False
) -> Candidate | None:
    stmt = (
        select(Candidate)
        .options(selectinload(Candidate.experiences), selectinload(Candidate.educations))
        .where(Candidate.id == candidate_id)
    )
    if for_update:
        stmt = stmt.with_for_update(of=Candidate)
    return await session.scalar(stmt)


async def get_candidates_by_ids(
    session: AsyncSession, candidate_ids: list[uuid.UUID]
) -> list[Candidate]:
    if not candidate_ids:
        return []
    return list(await session.scalars(select(Candidate).where(Candidate.id.in_(candidate_ids))))


async def list_candidates_with_children(session: AsyncSession) -> list[Candidate]:
    """Locks the rows until the caller commits, so an edit saved meanwhile waits instead of
    being overwritten by a document built from the old profile."""
    statement = (
        select(Candidate)
        .options(selectinload(Candidate.experiences), selectinload(Candidate.educations))
        .with_for_update(of=Candidate)
    )
    return list(await session.scalars(statement))


async def set_search_document(
    session: AsyncSession, candidate_id: uuid.UUID, document: str
) -> None:
    """Not an edit of the profile, so `version` and `updated_at` stay as they are."""
    await session.execute(
        update(Candidate)
        .where(Candidate.id == candidate_id)
        .values(search_document=document, updated_at=Candidate.updated_at)
    )


async def full_text_candidate_ids(
    session: AsyncSession,
    query: str,
    limit: int,
    within: Select[uuid.UUID] | None = None,
) -> list[uuid.UUID]:
    """Best full-text matches first, among candidates meeting `within`. Words are OR-ed, so a
    profile matching 4 of 6 still ranks; ts_rank_cd puts profiles matching more of them,
    closer together, higher."""
    any_word = func.to_tsquery(
        "english",
        func.replace(cast(func.plainto_tsquery("english", query), Text), "&", "|"),
    )
    # Flag 1 divides by 1 + log(length), so long profiles don't win by length alone.
    rank = func.ts_rank_cd(Candidate.search_tsv, any_word, 1)
    statement = (
        select(Candidate.id)
        .where(Candidate.search_tsv.bool_op("@@")(any_word))
        .order_by(rank.desc(), Candidate.id)
        .limit(limit)
    )
    if within is not None:
        statement = statement.where(Candidate.id.in_(within))
    return list(await session.scalars(statement))


async def get_candidate_row(session: AsyncSession, candidate_id: uuid.UUID) -> Candidate | None:
    """The candidate without its child rows."""
    return await session.get(Candidate, candidate_id)


async def lock_resume_pdf_key(
    session: AsyncSession, candidate_id: uuid.UUID
) -> tuple[bool, str | None]:
    """Whether the candidate exists, and their stored PDF key, with the row locked."""
    row = (
        await session.execute(
            select(Candidate.resume_pdf_key).where(Candidate.id == candidate_id).with_for_update()
        )
    ).one_or_none()
    return (row is not None, row[0] if row is not None else None)


async def set_resume_ref(
    session: AsyncSession, candidate_id: uuid.UUID, resume_ref: uuid.UUID
) -> bool:
    # A plain UPDATE: attaching a file isn't a profile edit, so `version` stays and an editor
    # with the profile open can still save. A new resume makes any stored PDF stale.
    result = await session.execute(
        update(Candidate)
        .where(Candidate.id == candidate_id)
        .values(resume_ref=resume_ref, resume_pdf_key=None)
        .returning(Candidate.id)
        .execution_options(synchronize_session=False)
    )
    return result.scalar_one_or_none() is not None


async def set_resume_pdf_key(
    session: AsyncSession,
    candidate_id: uuid.UUID,
    key: str,
    *,
    resume_ref: uuid.UUID,
    version: int,
    replacing: str | None,
) -> bool:
    """Record a stored PDF only if nothing changed since it was fetched: same resume, same
    profile version, and the key it replaces is still the current one (so of two views racing,
    only the first is kept). Plain UPDATE, so `version` doesn't move."""
    result = await session.execute(
        update(Candidate)
        .where(
            Candidate.id == candidate_id,
            Candidate.resume_ref == resume_ref,
            Candidate.version == version,
            Candidate.resume_pdf_key.is_not_distinct_from(replacing),
        )
        .values(resume_pdf_key=key)
        .returning(Candidate.id)
        .execution_options(synchronize_session=False)
    )
    return result.scalar_one_or_none() is not None


async def add_bookmark(session: AsyncSession, candidate_id: uuid.UUID, added_by: uuid.UUID) -> bool:
    """True when a new bookmark was made; starring an already-starred candidate keeps the first
    adder."""
    result = await session.execute(
        insert(CandidateBookmark)
        .values(id=uuid.uuid4(), candidate_id=candidate_id, added_by=added_by)
        .on_conflict_do_nothing(index_elements=[CandidateBookmark.candidate_id])
        .returning(CandidateBookmark.id)
    )
    return result.scalar_one_or_none() is not None


async def remove_bookmark(session: AsyncSession, candidate_id: uuid.UUID) -> bool:
    result = await session.execute(
        delete(CandidateBookmark)
        .where(CandidateBookmark.candidate_id == candidate_id)
        .returning(CandidateBookmark.id)
    )
    return result.scalar_one_or_none() is not None


async def list_bookmarks(session: AsyncSession) -> list[tuple[CandidateBookmark, Candidate]]:
    rows = await session.execute(
        select(CandidateBookmark, Candidate)
        .join(Candidate, Candidate.id == CandidateBookmark.candidate_id)
        .order_by(CandidateBookmark.created_at.desc(), CandidateBookmark.id.desc())
    )
    return [(bookmark, candidate) for bookmark, candidate in rows]


async def delete_candidate(
    session: AsyncSession, candidate_id: uuid.UUID
) -> tuple[bool, str | None]:
    """Whether a row was deleted, and its stored PDF key (the caller deletes that file)."""
    # Child rows go via ON DELETE CASCADE; no need to load them.
    row = (
        await session.execute(
            delete(Candidate)
            .where(Candidate.id == candidate_id)
            .returning(Candidate.id, Candidate.resume_pdf_key)
        )
    ).one_or_none()
    return (row is not None, row[1] if row is not None else None)
