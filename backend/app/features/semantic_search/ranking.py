"""Hybrid retrieval fusion, and ranking of the shortlist by an LLM with readable reasons.

Order (user decision 2026-11-02): skills first, and location with them unless the role is
remote; then experience; then, for remote roles, the wanted country; finally years. Budget is a
hard filter checked by code, so it never reaches the LLM. The LLM only *judges* skills,
location and experience; this code decides the order, so the same answers give the same order.
"""

import json
import re
import time
import uuid
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.features import candidates
from app.features.semantic_search.schemas import Criterion, Fit, SemanticMatch
from app.shared.validation import country_name

PROMPT_VERSION = "rank_v7"
INSTRUCTIONS = (Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.md").read_text("utf-8")
RANK_MODEL = "gpt-5.4-mini"
# Room for up to 110 judgements (about 150 tokens each); caps a runaway answer at about $0.09
# (gpt-5.4-mini output is $4.50 per million tokens).
MAX_OUTPUT_TOKENS = 20_000
# Reciprocal rank fusion constant; 60 is the usual choice and keeps either list from dominating.
RRF_K = 60
SKILLS_MET_SCORE = 60
EXPERIENCE_MET_SCORE = 60
EXPERIENCE_PARTIAL_SCORE = 30
# LLM scores wobble by a few points between runs, so only a gap of about this size counts.
# Without bands, a 91 over an 88 decided the order and experience almost never got a say.
SCORE_BAND = 20
RANKING_CACHE_SIZE = 128
RANKING_CACHE_SECONDS = 600.0

WorkMode = Literal["remote", "hybrid", "office"]
# The more office time someone accepts, the more kinds of job they fit (user decision): office
# fits office, hybrid and remote jobs; hybrid fits hybrid and remote; remote fits remote only.
# Profiles and jobs store "onsite"; searches say "office". Both mean the same.
_OFFICE_TIME: dict[str, int] = {"remote": 0, "hybrid": 1, "office": 2, "onsite": 2}
_WORK_MODE_WORDS: list[tuple[WorkMode, re.Pattern[str]]] = [
    ("hybrid", re.compile(r"\bhybrid\b")),
    ("office", re.compile(r"\b(?:on-?site|in[- ]office|office|wfo)\b")),
    ("remote", re.compile(r"\b(?:remote|wfh|work from home)\b")),
]


def required_work_mode(query: str) -> WorkMode | None:
    """The work mode a search asks for; hybrid wins when several are named."""
    lowered = query.lower()
    return next((mode for mode, pattern in _WORK_MODE_WORDS if pattern.search(lowered)), None)


def fits_work_mode(candidate_modes: Sequence[str], required: WorkMode) -> bool:
    return any(_OFFICE_TIME.get(mode, -1) >= _OFFICE_TIME[required] for mode in candidate_modes)


def fuse(*ranked_lists: Sequence[uuid.UUID], count: int) -> list[uuid.UUID]:
    """Reciprocal rank fusion: a profile near the top of either list, or in both, ranks high."""
    scores: dict[uuid.UUID, float] = {}
    for ranked in ranked_lists:
        for position, candidate_id in enumerate(ranked):
            scores[candidate_id] = scores.get(candidate_id, 0.0) + 1 / (RRF_K + position + 1)
    return sorted(scores, key=lambda cid: (-scores[cid], str(cid)))[:count]


# --- What the LLM answers (structured output) ------------------------------------------------

LocationVerdict = Literal[
    "not_required", "same_city", "commutable", "willing_to_relocate", "elsewhere"
]


class CandidateJudgement(BaseModel):
    candidate: int
    skills_score: int
    skills_note: str
    location: LocationVerdict
    location_note: str
    experience_score: int
    experience_note: str


class RankingAnswer(BaseModel):
    # Asked once per search, so one odd per-candidate verdict can't decide it for everyone.
    search_names_place: bool
    # Flips the final years tie-break. Asked of the model because a word list can't tell a
    # junior role from a senior one that "mentors junior engineers".
    search_wants_junior: bool
    judgements: list[CandidateJudgement]


def build_prompt(query: str, pool: Sequence[candidates.RankableCandidate]) -> str:
    """The search and the anonymised profiles: no names, emails, phones, links or pay (budget
    is checked by code)."""
    profiles = [
        {
            "candidate": number,
            "profile": candidate.profile_text,
            "city": candidate.city,
            "country": candidate.country_code,
            "years_experience": candidate.years_experience,
            "work_modes": list(candidate.work_modes),
            "open_to_relocation": candidate.open_to_relocation,
        }
        for number, candidate in enumerate(pool, start=1)
    ]
    return f"Search: {query}\n\nCandidates:\n{json.dumps(profiles, ensure_ascii=False, indent=1)}"


# --- From judgements to an order -------------------------------------------------------------

_LOCATION_POINTS: dict[LocationVerdict, float] = {
    "not_required": 1.0,
    "same_city": 1.0,
    "commutable": 1.0,
    "willing_to_relocate": 0.5,
    "elsewhere": 0.0,
}


def _clamp(score: int) -> int:
    return max(0, min(100, score))


def _band(score: int) -> int:
    return min(score, 99) // SCORE_BAND


type SortKey = tuple[float, int, int, float, float]


def judge_location(
    judgement: CandidateJudgement,
    candidate: candidates.RankableCandidate,
    required: WorkMode | None,
    place_named: bool = False,
    home_country: str | None = None,
) -> tuple[float, str]:
    """Points (1 met, 0.5 partial, 0 missed) and a note. The work-mode rule is plain logic, so
    it is applied here rather than trusted to the LLM. For a remote role the points only break
    ties (same country first), so they come from the stored country, not the LLM."""
    if required == "remote":
        if home_country is None:
            return 1.0, "Remote role, location doesn't matter"
        if candidate.country_code == home_country:
            return 1.0, f"Remote role, based in {country_name(home_country)}"
        return 0.5, f"Remote role, based outside {country_name(home_country)}"
    if required is not None and not fits_work_mode(candidate.work_modes, required):
        return 0.0, f"Wants {', '.join(candidate.work_modes) or 'no stated'} work only"
    verdict = judgement.location
    if not place_named:
        return 1.0, "No place named"
    if verdict == "not_required":
        # The search names a place, so "doesn't matter" is wrong here; it once let a
        # remote-working Berlin profile outrank a local one.
        return 0.0, f"Lives in {candidate.city}, not the place searched"
    if verdict == "willing_to_relocate" and candidate.open_to_relocation is not True:
        verdict = "elsewhere"  # the LLM may not invent a willingness the profile doesn't state
    return _LOCATION_POINTS[verdict], judgement.location_note


def _status(points: float) -> Literal["met", "partial", "missed"]:
    return "met" if points >= 1 else "partial" if points > 0 else "missed"


@dataclass(frozen=True)
class Budget:
    """The most a job or search will pay per year, in whole units of `currency`."""

    max_salary: int
    currency: str


def salary_criterion(candidate: candidates.RankableCandidate, budget: Budget) -> Criterion:
    """What the recruiter reads about pay. Over budget is a hard filter (failed_filters), so
    this only explains it; no stated salary counts as within budget (user decision)."""
    expected, currency = candidate.expected_salary, candidate.salary_currency
    if expected is None or currency is None:
        return Criterion(name="salary", status="partial", note="No expected salary stated")
    if currency != budget.currency:
        return Criterion(
            name="salary", status="partial", note=f"Expects in {currency}, can't compare"
        )
    note = f"Expects {expected:,} {currency}, budget {budget.max_salary:,} {currency}"
    return Criterion(
        name="salary", status="met" if expected <= budget.max_salary else "missed", note=note
    )


def to_match(
    judgement: CandidateJudgement,
    candidate: candidates.RankableCandidate,
    required: WorkMode | None,
    place_named: bool = False,
    wants_junior: bool = False,
    budget: Budget | None = None,
    home_country: str | None = None,
) -> tuple[SortKey, SemanticMatch]:
    """The sort key (higher is better) and the match shown to the recruiter: skills, plus
    location unless the role is remote; then the skills band, the experience band, for a
    remote role the wanted country, and finally actual years (fewer for a junior search)."""
    skills = _clamp(judgement.skills_score)
    experience = _clamp(judgement.experience_score)
    skills_points = 1.0 if skills >= SKILLS_MET_SCORE else 0.0
    location_points, location_note = judge_location(
        judgement, candidate, required, place_named, home_country
    )
    remote = required == "remote"
    total = skills_points + (0.0 if remote else location_points)
    musts = 1 if remote else 2
    fit: Fit = "strong" if total >= musts else "partial" if total >= 1 else "weak"
    experience_status: Literal["met", "partial", "missed"] = (
        "met"
        if experience >= EXPERIENCE_MET_SCORE
        else "partial"
        if experience >= EXPERIENCE_PARTIAL_SCORE
        else "missed"
    )
    criteria = [
        Criterion(name="skills", status=_status(skills_points), note=judgement.skills_note),
        Criterion(name="location", status=_status(location_points), note=location_note),
        Criterion(name="experience", status=experience_status, note=judgement.experience_note),
    ]
    if budget is not None:  # only when the job or search states a budget
        criteria.append(salary_criterion(candidate, budget))
    match = SemanticMatch(candidate=candidate.summary, fit=fit, criteria=criteria)
    years = -candidate.years_experience if wants_junior else candidate.years_experience
    country = location_points if remote else 0.0
    key = (total, _band(skills), _band(experience), country, years)
    return key, match


def rank_by_judgements(
    answer: RankingAnswer,
    pool: Sequence[candidates.RankableCandidate],
    required: WorkMode | None,
    *,
    budget: Budget | None = None,
    home_country: str | None = None,
) -> list[SemanticMatch]:
    """Ordered by `to_match`'s key. A candidate the LLM left out (or numbered wrongly) is kept,
    last, rather than silently dropped. `home_country` is the country a remote role wants."""
    by_number = {j.candidate: j for j in answer.judgements}
    place_named = answer.search_names_place
    ranked: list[tuple[SortKey, int, SemanticMatch]] = []
    for number, candidate in enumerate(pool, start=1):
        judgement = by_number.get(number)
        if judgement is None:
            unjudged = SemanticMatch(
                candidate=candidate.summary,
                fit="weak",
                criteria=[Criterion(name="skills", status="missed", note="Not assessed")],
            )
            ranked.append(((-1.0, 0, 0, 0.0, 0.0), number, unjudged))
            continue
        key, match = to_match(
            judgement,
            candidate,
            required,
            place_named,
            answer.search_wants_junior,
            budget,
            home_country,
        )
        ranked.append((key, number, match))
    # Ties keep the hybrid-search order (lower number first).
    ranked.sort(key=lambda item: (tuple(-k for k in item[0]), item[1]))
    return [match for _, _, match in ranked]


# --- Cache: repeating a search over unchanged profiles is free ---------------------------------

type CacheKey = tuple[str, str, tuple[tuple[uuid.UUID, str], ...]]
_cache: OrderedDict[CacheKey, tuple[float, RankingAnswer]] = OrderedDict()


def cache_key(model: str, query: str, pool: Sequence[candidates.RankableCandidate]) -> CacheKey:
    profiles = tuple((c.summary.id, c.updated_at.isoformat()) for c in pool)
    return (f"{model}:{PROMPT_VERSION}", query.casefold(), profiles)


def cached_answer(key: CacheKey) -> RankingAnswer | None:
    entry = _cache.get(key)
    if entry is None or time.monotonic() - entry[0] > RANKING_CACHE_SECONDS:
        _cache.pop(key, None)
        return None
    _cache.move_to_end(key)
    return entry[1]


def remember_answer(key: CacheKey, answer: RankingAnswer) -> None:
    _cache[key] = (time.monotonic(), answer)
    if len(_cache) > RANKING_CACHE_SIZE:
        _cache.popitem(last=False)


def clear_ranking_cache() -> None:
    _cache.clear()
