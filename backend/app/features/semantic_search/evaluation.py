"""Score search by meaning against the labelled golden set in backend/evals (RULES section 9).

A person grades candidates for each search (0 not relevant .. 3 perfect fit). The run then
reports NDCG@10 and precision@5 per search, and a fairness check: of the people graded as
qualified, does each group (country, experience band) reach the top 10 at a similar rate?

The golden set is committed to git, so it may only name synthetic seed profiles.
"""

import math
import random
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.semantic_search import ranking, service, understanding
from app.features.semantic_search.schemas import HardFilters, SemanticSearchParams

logger = structlog.get_logger(__name__)

# Graded at least this, a candidate counts as relevant (precision) and qualified (fairness).
RELEVANT_GRADE = 2
NDCG_K = 10
PRECISION_K = 5
# The four-fifths rule used in US adverse-impact analysis: a group found at under 80% of the
# best group's rate is flagged.
IMPACT_RATIO_FLOOR = 0.8
# Below this many qualified people, a group's rate is too noisy to flag.
MIN_GROUP_SIZE = 5
# Only seed data may be named in the committed golden set (see scripts/seed_candidates.py).
SYNTHETIC_SOURCE = "synthetic"


class GoldenCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    # What the grader reads; written by eval-label, not used for scoring.
    profile: str
    country: str
    years: float
    grade: int | None = Field(default=None, ge=0, le=3)


class GoldenCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    query: str
    filters: HardFilters = HardFilters()
    candidates: list[GoldenCandidate]

    @property
    def graded(self) -> bool:
        return bool(self.candidates) and all(c.grade is not None for c in self.candidates)

    def grades(self) -> dict[str, int]:
        return {c.email: c.grade for c in self.candidates if c.grade is not None}


class GoldenSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cases: list[GoldenCase] = []


class CaseScore(BaseModel):
    id: str
    ranked_by: Literal["ai", "search"]
    ndcg_at_10: float | None
    precision_at_5: float
    # Shown in the top 10 but never graded: the golden set needs extending when this grows.
    unjudged_in_top_10: int
    top_10: list[str]


class GroupRate(BaseModel):
    dimension: Literal["country", "experience"]
    group: str
    qualified: int
    found: int
    rate: float
    impact_ratio: float | None
    flagged: bool


class EvalReport(BaseModel):
    run_at: datetime
    ranking_model: str
    ranking_prompt_version: str
    understanding_prompt_version: str
    cases: list[CaseScore]
    skipped_ungraded: list[str]
    mean_ndcg_at_10: float | None
    mean_precision_at_5: float | None
    fairness: list[GroupRate]
    # Not stored, so they can't be checked here; an independent bias audit needs them.
    not_checked: list[str] = ["gender", "age", "ethnicity"]


def _dcg(gains: Iterable[int]) -> float:
    return sum((2.0**grade - 1) / math.log2(position + 2) for position, grade in enumerate(gains))


def ndcg_at(ranked: Sequence[str], grades: dict[str, int], k: int = NDCG_K) -> float | None:
    """None when the case has nobody graded above 0 (nothing to find, so no score)."""
    ideal = _dcg(sorted(grades.values(), reverse=True)[:k])
    if ideal == 0:
        return None
    return _dcg(grades.get(email, 0) for email in ranked[:k]) / ideal


def precision_at(ranked: Sequence[str], grades: dict[str, int], k: int = PRECISION_K) -> float:
    """Ungraded results count as not relevant; fewer than k results still divide by k."""
    return sum(grades.get(email, 0) >= RELEVANT_GRADE for email in ranked[:k]) / k


def experience_band(years: float) -> str:
    if years < 3:
        return "0-3 years"
    if years < 8:
        return "3-8 years"
    if years < 15:
        return "8-15 years"
    return "15+ years"


def group_rates(
    outcomes: Sequence[tuple[GoldenCandidate, bool]],
    dimension: Literal["country", "experience"],
) -> list[GroupRate]:
    """Rate at which qualified people of each group were found; `outcomes` holds only people
    graded as qualified, with whether they were in that search's top 10."""
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for candidate, was_found in outcomes:
        group = candidate.country if dimension == "country" else experience_band(candidate.years)
        totals[group][0] += 1
        totals[group][1] += int(was_found)
    rates = {group: found / qualified for group, (qualified, found) in totals.items()}
    best = max(
        (rates[g] for g, (qualified, _) in totals.items() if qualified >= MIN_GROUP_SIZE),
        default=0.0,
    )
    rows = []
    for group, (qualified, found) in sorted(totals.items()):
        ratio = rates[group] / best if best > 0 and qualified >= MIN_GROUP_SIZE else None
        rows.append(
            GroupRate(
                dimension=dimension,
                group=group,
                qualified=qualified,
                found=found,
                rate=round(rates[group], 3),
                impact_ratio=None if ratio is None else round(ratio, 3),
                flagged=ratio is not None and ratio < IMPACT_RATIO_FLOOR,
            )
        )
    return rows


def _mean(values: Iterable[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return round(sum(present) / len(present), 4) if present else None


async def run_eval(session: AsyncSession, golden: GoldenSet) -> EvalReport:
    """Run every fully graded search for real (about $0.05 each, metered like any search)."""
    scores: list[CaseScore] = []
    qualified: list[tuple[GoldenCandidate, bool]] = []
    for case in golden.cases:
        if not case.graded:
            continue
        params = SemanticSearchParams(q=case.query, **case.filters.model_dump(exclude_none=True))
        result, _ = await service.find_matches(session, params)
        ranked = [match.candidate.email for match in result.items]
        grades = case.grades()
        top = ranked[:NDCG_K]
        scores.append(
            CaseScore(
                id=case.id,
                ranked_by=result.ranked_by,
                ndcg_at_10=None if (n := ndcg_at(ranked, grades)) is None else round(n, 4),
                precision_at_5=round(precision_at(ranked, grades), 4),
                unjudged_in_top_10=sum(email not in grades for email in top),
                top_10=top,
            )
        )
        qualified += [
            (c, c.email in top) for c in case.candidates if (c.grade or 0) >= RELEVANT_GRADE
        ]
        logger.info("eval_case_completed", case=case.id, ranked_by=result.ranked_by)
    return EvalReport(
        run_at=datetime.now(UTC),
        ranking_model=ranking.RANK_MODEL,
        ranking_prompt_version=ranking.PROMPT_VERSION,
        understanding_prompt_version=understanding.PROMPT_VERSION,
        cases=scores,
        skipped_ungraded=[case.id for case in golden.cases if not case.graded],
        mean_ndcg_at_10=_mean(s.ndcg_at_10 for s in scores),
        mean_precision_at_5=_mean(s.precision_at_5 for s in scores),
        fairness=group_rates(qualified, "country") + group_rates(qualified, "experience"),
    )


async def new_case(
    session: AsyncSession, case_id: str, query: str, count: int, rng: random.Random
) -> GoldenCase:
    """A case to grade: the best hybrid matches (no AI ranking), synthetic profiles only, in a
    shuffled order so the grader isn't steered by the search's own order."""
    pool = await service.label_pool(session, query, count)
    picked = [
        GoldenCandidate(
            email=c.summary.email,
            profile=(
                f"{c.summary.headline} · {c.city}, {c.country_code} · "
                f"{c.years_experience:g} years · {', '.join(c.skills)}"
            ),
            country=c.country_code,
            years=c.years_experience,
        )
        for c in pool
        if c.summary.source == SYNTHETIC_SOURCE
    ]
    rng.shuffle(picked)
    return GoldenCase(id=case_id, query=query, candidates=picked)


def report_markdown(report: EvalReport) -> str:
    """The run as a short page a person can read in a PR."""
    lines = [
        f"# Search eval {report.run_at:%Y-%m-%d %H:%M} UTC",
        "",
        f"Ranking `{report.ranking_model}` prompt `{report.ranking_prompt_version}`, "
        f"understanding prompt `{report.understanding_prompt_version}`.",
        "",
        f"**Mean NDCG@10:** {report.mean_ndcg_at_10} · "
        f"**Mean precision@5:** {report.mean_precision_at_5}",
        "",
        "| Case | Ranked by | NDCG@10 | Precision@5 | Ungraded in top 10 |",
        "|---|---|---|---|---|",
        *(
            f"| {c.id} | {c.ranked_by} | {c.ndcg_at_10} | {c.precision_at_5} "
            f"| {c.unjudged_in_top_10} |"
            for c in report.cases
        ),
        "",
        "## Fairness: qualified people found in the top 10",
        "",
        f"Flagged when a group with at least {MIN_GROUP_SIZE} qualified people is found at "
        f"under {IMPACT_RATIO_FLOOR:.0%} of the best group's rate.",
        "",
        "| Dimension | Group | Qualified | Found | Rate | Impact ratio | Flag |",
        "|---|---|---|---|---|---|---|",
        *(
            f"| {g.dimension} | {g.group} | {g.qualified} | {g.found} | {g.rate} "
            f"| {g.impact_ratio if g.impact_ratio is not None else 'too few'} "
            f"| {'FLAG' if g.flagged else ''} |"
            for g in report.fairness
        ),
        "",
        f"Not checked (not collected): {', '.join(report.not_checked)}.",
    ]
    if report.skipped_ungraded:
        lines += ["", f"Skipped, not fully graded: {', '.join(report.skipped_ungraded)}."]
    if any(c.ranked_by != "ai" for c in report.cases):
        lines += ["", "**Warning:** some cases fell back to search order (no AI ranking)."]
    return "\n".join(lines) + "\n"
