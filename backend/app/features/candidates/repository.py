import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ColumnElement, Select, Text, cast, delete, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.features.candidates.models import Candidate
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
    return clauses


def ids_passing(
    *,
    min_years: Decimal | None,
    skills: Sequence[str],
    city: str | None,
    country: str | None,
    source: str | None,
) -> Select[uuid.UUID]:
    """Ids of candidates meeting every hard filter, as a subquery for other searches."""
    clauses = hard_filter_clauses(
        min_years=min_years, skills=skills, city=city, country=country, source=source
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


async def delete_candidate(session: AsyncSession, candidate_id: uuid.UUID) -> bool:
    # Child rows go via ON DELETE CASCADE; no need to load them.
    result = await session.execute(
        delete(Candidate).where(Candidate.id == candidate_id).returning(Candidate.id)
    )
    return result.scalar_one_or_none() is not None
