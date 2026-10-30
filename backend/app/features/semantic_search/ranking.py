"""Hybrid retrieval fusion, and ranking of the shortlist by an LLM with readable reasons.

Order (user decision): skills and location first, then experience. The LLM only *judges*
each criterion; this code decides the order, so the same answers always give the same order.
"""

import json
import re
import time
import uuid
from collections import OrderedDict
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.features import candidates
from app.features.semantic_search.schemas import Criterion, Fit, SemanticMatch

PROMPT_VERSION = "rank_v3"
INSTRUCTIONS = (Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.md").read_text("utf-8")
RANK_MODEL = "gpt-5.4-mini"
# Room for up to 30 judgements (about 150 tokens each); caps a runaway answer at about $0.045
# (gpt-5.4-mini output is $4.50 per million tokens).
MAX_OUTPUT_TOKENS = 10_000
# Reciprocal rank fusion constant; 60 is the usual choice and keeps either list from dominating.
RRF_K = 60
SKILLS_MET_SCORE = 60
EXPERIENCE_MET_SCORE = 60
EXPERIENCE_PARTIAL_SCORE = 30
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
SalaryVerdict = Literal["not_required", "within", "above", "unknown"]


class CandidateJudgement(BaseModel):
    candidate: int
    skills_score: int
    skills_note: str
    location: LocationVerdict
    location_note: str
    experience_score: int
    experience_note: str
    salary: SalaryVerdict
    salary_note: str


class RankingAnswer(BaseModel):
    # Asked once per search, so one odd per-candidate verdict can't decide it for everyone.
    search_names_place: bool
    search_states_pay: bool
    judgements: list[CandidateJudgement]


def build_prompt(query: str, pool: Sequence[candidates.RankableCandidate]) -> str:
    """The search and the anonymised profiles: no names, emails, phones or links."""
    profiles = [
        {
            "candidate": number,
            "profile": candidate.profile_text,
            "city": candidate.city,
            "country": candidate.country_code,
            "years_experience": candidate.years_experience,
            "work_modes": list(candidate.work_modes),
            "open_to_relocation": candidate.open_to_relocation,
            "expected_yearly_salary": (
                f"{candidate.expected_salary} {candidate.salary_currency}"
                if candidate.expected_salary is not None
                else None
            ),
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


def judge_location(
    judgement: CandidateJudgement,
    candidate: candidates.RankableCandidate,
    required: WorkMode | None,
    place_named: bool = False,
) -> tuple[float, str]:
    """Points (1 met, 0.5 partial, 0 missed) and a note. The work-mode rule is plain logic, so
    it is applied here rather than trusted to the LLM."""
    if required == "remote":
        return 1.0, "Remote role, location doesn't matter"
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


_SALARY_POINTS: dict[SalaryVerdict, float] = {
    "not_required": 1.0,
    "within": 1.0,
    "unknown": 0.5,
    "above": 0.0,
}


def judge_salary(
    judgement: CandidateJudgement, candidate: candidates.RankableCandidate, pay_named: bool
) -> tuple[SalaryVerdict, float]:
    if not pay_named:
        return "not_required", _SALARY_POINTS["not_required"]
    verdict = judgement.salary
    if verdict == "not_required":
        verdict = "unknown"  # the search states pay, so it is required
    if verdict in ("within", "above") and candidate.expected_salary is None:
        verdict = "unknown"  # the LLM may not invent an expectation the profile doesn't state
    return verdict, _SALARY_POINTS[verdict]


def to_match(
    judgement: CandidateJudgement,
    candidate: candidates.RankableCandidate,
    required: WorkMode | None,
    place_named: bool = False,
    pay_named: bool = False,
) -> tuple[tuple[float, int, float, int], SemanticMatch]:
    """The sort key (higher is better) and the match shown to the recruiter: skills and
    location first, then the skills score, then pay, then experience."""
    skills = _clamp(judgement.skills_score)
    experience = _clamp(judgement.experience_score)
    skills_points = 1.0 if skills >= SKILLS_MET_SCORE else 0.0
    location_points, location_note = judge_location(judgement, candidate, required, place_named)
    salary_verdict, salary_points = judge_salary(judgement, candidate, pay_named)
    total = skills_points + location_points
    fit: Fit = "strong" if total >= 2 else "partial" if total >= 1 else "weak"
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
    if salary_verdict != "not_required":  # only when the search or job states pay
        note = "No expected salary stated" if salary_verdict == "unknown" else judgement.salary_note
        criteria.append(Criterion(name="salary", status=_status(salary_points), note=note))
    match = SemanticMatch(candidate=candidate.summary, fit=fit, criteria=criteria)
    return (total, skills, salary_points, experience), match


def rank_by_judgements(
    answer: RankingAnswer,
    pool: Sequence[candidates.RankableCandidate],
    required: WorkMode | None,
) -> list[SemanticMatch]:
    """Skills + location first, then skills score, then pay, then experience. A candidate the
    LLM left out (or numbered wrongly) is kept, last, rather than silently dropped."""
    by_number = {j.candidate: j for j in answer.judgements}
    place_named, pay_named = answer.search_names_place, answer.search_states_pay
    ranked: list[tuple[tuple[float, int, float, int], int, SemanticMatch]] = []
    for number, candidate in enumerate(pool, start=1):
        judgement = by_number.get(number)
        if judgement is None:
            unjudged = SemanticMatch(
                candidate=candidate.summary,
                fit="weak",
                criteria=[Criterion(name="skills", status="missed", note="Not assessed")],
            )
            ranked.append(((-1.0, 0, 0.0, 0), number, unjudged))
            continue
        key, match = to_match(judgement, candidate, required, place_named, pay_named)
        ranked.append((key, number, match))
    # Ties keep the hybrid-search order (lower number first).
    ranked.sort(key=lambda item: (tuple(-k for k in item[0]), item[1]))
    return [match for _, _, match in ranked]


# --- Cache: repeating a search over unchanged profiles is free ---------------------------------

type _CacheKey = tuple[str, str, tuple[tuple[uuid.UUID, str], ...]]
_cache: OrderedDict[_CacheKey, tuple[float, RankingAnswer]] = OrderedDict()


def cache_key(model: str, query: str, pool: Sequence[candidates.RankableCandidate]) -> _CacheKey:
    profiles = tuple((c.summary.id, c.updated_at.isoformat()) for c in pool)
    return (f"{model}:{PROMPT_VERSION}", query.casefold(), profiles)


def cached_answer(key: _CacheKey) -> RankingAnswer | None:
    entry = _cache.get(key)
    if entry is None or time.monotonic() - entry[0] > RANKING_CACHE_SECONDS:
        _cache.pop(key, None)
        return None
    _cache.move_to_end(key)
    return entry[1]


def remember_answer(key: _CacheKey, answer: RankingAnswer) -> None:
    _cache[key] = (time.monotonic(), answer)
    if len(_cache) > RANKING_CACHE_SIZE:
        _cache.popitem(last=False)


def clear_ranking_cache() -> None:
    _cache.clear()
