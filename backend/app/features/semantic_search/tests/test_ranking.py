import uuid
from datetime import UTC, datetime

import pytest

from app.features.candidates import CandidateSummary, RankableCandidate
from app.features.candidates.tests.factories import valid_candidate_payload
from app.features.semantic_search import ranking
from app.features.semantic_search.ranking import CandidateJudgement, RankingAnswer


def _candidate(
    name: str,
    *,
    work_modes: tuple[str, ...] = ("onsite",),
    relocate: bool | None = None,
    salary: int | None = None,
    currency: str = "INR",
    years: float = 6,
    country: str = "IN",
) -> RankableCandidate:
    payload = valid_candidate_payload()
    summary = CandidateSummary(
        id=uuid.uuid4(),
        full_name=name,
        email=f"{name.lower()}@example.com",
        headline=payload["headline"],
        city="Ghaziabad",
        country_code=country,
        years_experience=6,
        top_skills=["FastAPI"],
        expected_salary=salary,
        salary_currency=None if salary is None else currency,
        source="manual",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    return RankableCandidate(
        summary=summary,
        profile_text="Backend engineer. Skills: FastAPI.",
        city="Ghaziabad",
        country_code=country,
        years_experience=years,
        skills=("fastapi",),
        work_modes=work_modes,
        open_to_relocation=relocate,
        expected_salary=salary,
        salary_currency=None if salary is None else currency,
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _answer(
    *,
    judgements: list[CandidateJudgement],
    place: bool = True,
    junior: bool = False,
) -> RankingAnswer:
    return RankingAnswer(
        search_names_place=place,
        search_wants_junior=junior,
        judgements=judgements,
    )


def _judgement(number: int, skills: int, location: str, experience: int) -> CandidateJudgement:
    return CandidateJudgement.model_validate(
        {
            "candidate": number,
            "skills_score": skills,
            "skills_note": f"skills {number}",
            "location": location,
            "location_note": f"location {number}",
            "experience_score": experience,
            "experience_note": f"experience {number}",
        }
    )


@pytest.mark.parametrize(
    ("query", "mode"),
    [
        ("fastapi dev, onsite in Ghaziabad", "office"),
        ("python engineer in office", "office"),
        ("hybrid role in Pune, office twice a week", "hybrid"),
        ("remote react developer", "remote"),
        ("fastapi developer in ghaziabad with 5 years", None),
    ],
)
def test_required_work_mode(query: str, mode: str | None) -> None:
    assert ranking.required_work_mode(query) == mode


def test_more_office_time_fits_more_kinds_of_job() -> None:
    assert ranking.fits_work_mode(["office"], "remote")
    assert ranking.fits_work_mode(["office"], "hybrid")
    assert ranking.fits_work_mode(["hybrid"], "remote")
    assert not ranking.fits_work_mode(["hybrid"], "office")
    # Profiles store "onsite"; it once counted as no work mode at all.
    assert ranking.fits_work_mode(["onsite"], "office")
    assert ranking.fits_work_mode(["onsite"], "hybrid")
    assert not ranking.fits_work_mode(["remote"], "hybrid")
    assert ranking.fits_work_mode(["remote", "hybrid"], "hybrid")


def test_location_not_required_is_ignored_when_the_search_names_a_place() -> None:
    # "python developer in noida": the LLM said "remote, doesn't matter" for a Berlin profile
    # with better skills and "commutable" for a local one; the local one must win.
    elsewhere, local = _candidate("Brandon"), _candidate("Puneet")
    answer = _answer(
        judgements=[_judgement(1, 90, "not_required", 90), _judgement(2, 70, "commutable", 60)]
    )

    ranked = ranking.rank_by_judgements(answer, [elsewhere, local], None)

    assert [m.candidate.full_name for m in ranked] == ["Puneet", "Brandon"]
    assert ranked[1].criteria[1].status == "missed"


BUDGET = ranking.Budget(2_400_000, "INR")


def test_the_salary_criterion_is_checked_by_code_against_the_budget() -> None:
    # User decision 2026-11-02: over budget is filtered out (failed_filters), no stated salary
    # counts as within, and another currency can't be compared.
    pool = [
        _candidate("Within", salary=1_800_000),
        _candidate("Over", salary=3_000_000),
        _candidate("Unstated"),
        _candidate("Dollars", salary=90_000, currency="USD"),
    ]
    answer = _answer(judgements=[_judgement(n, 90, "same_city", 90) for n in range(1, 5)])

    ranked = ranking.rank_by_judgements(answer, pool, None, budget=BUDGET)

    salary = {m.candidate.full_name: m.criteria[3] for m in ranked}
    assert {name: (c.name, c.status, c.note) for name, c in salary.items()} == {
        "Within": ("salary", "met", "Expects 1,800,000 INR, budget 2,400,000 INR"),
        "Over": ("salary", "missed", "Expects 3,000,000 INR, budget 2,400,000 INR"),
        "Unstated": ("salary", "partial", "No expected salary stated"),
        "Dollars": ("salary", "partial", "Expects in USD, can't compare"),
    }
    # Pay is never part of the order; the filter handles it, so the hybrid order stands.
    assert [m.candidate.full_name for m in ranked] == ["Within", "Over", "Unstated", "Dollars"]


def test_remote_location_only_breaks_ties_with_the_wanted_country_first() -> None:
    abroad = _candidate("Abroad", work_modes=("remote",), country="DE")
    home = _candidate("Home", work_modes=("remote",))
    stronger_abroad = _candidate("StrongerAbroad", work_modes=("remote",), country="DE")
    answer = _answer(
        judgements=[
            _judgement(1, 85, "elsewhere", 70),
            _judgement(2, 85, "elsewhere", 70),
            _judgement(3, 85, "elsewhere", 90),  # a higher experience band
        ]
    )

    ranked = ranking.rank_by_judgements(
        answer, [abroad, home, stronger_abroad], "remote", home_country="IN"
    )

    # Better experience still wins; the country only decides between otherwise equal people,
    # and being abroad never costs a remote candidate their "strong" fit.
    assert [m.candidate.full_name for m in ranked] == ["StrongerAbroad", "Home", "Abroad"]
    assert {m.fit for m in ranked} == {"strong"}
    location = {m.candidate.full_name: m.criteria[1] for m in ranked}
    assert (location["Home"].status, location["Home"].note) == (
        "met",
        "Remote role, based in India",
    )
    assert (location["Abroad"].status, location["Abroad"].note) == (
        "partial",
        "Remote role, based outside India",
    )


def test_more_experienced_people_win_among_similar_skills() -> None:
    # "devops tech lead in delhi": 5 years with a slightly higher score once beat 15 years.
    junior = _candidate("Junior", years=5)
    senior = _candidate("Senior", years=15)
    answer = _answer(
        judgements=[
            _judgement(1, 92, "same_city", 85),
            _judgement(2, 85, "same_city", 85),
        ]
    )

    ranked = ranking.rank_by_judgements(answer, [junior, senior], None)

    assert [m.candidate.full_name for m in ranked] == ["Senior", "Junior"]


def test_fewer_years_win_among_similar_skills_when_the_search_wants_juniors() -> None:
    # "junior python developer": 3 years scored 82 and 1 year 90, the same band, and the years
    # tie-break used to put the 3-year person first.
    three_years = _candidate("ThreeYears", years=3)
    one_year = _candidate("OneYear", years=1)
    answer = _answer(
        judgements=[
            _judgement(1, 90, "same_city", 82),
            _judgement(2, 90, "same_city", 90),
        ],
        junior=True,
    )

    ranked = ranking.rank_by_judgements(answer, [three_years, one_year], None)

    assert [m.candidate.full_name for m in ranked] == ["OneYear", "ThreeYears"]


def test_a_real_gap_in_skills_or_experience_still_beats_years() -> None:
    weaker_skills = _candidate("WeakerSkills", years=15)
    misfit_experience = _candidate("Misfit", years=12)
    best = _candidate("Best", years=6)
    answer = _answer(
        judgements=[
            _judgement(1, 62, "same_city", 85),
            _judgement(2, 85, "same_city", 30),
            _judgement(3, 85, "same_city", 85),
        ]
    )

    ranked = ranking.rank_by_judgements(answer, [weaker_skills, misfit_experience, best], None)

    assert [m.candidate.full_name for m in ranked] == ["Best", "Misfit", "WeakerSkills"]


def test_one_odd_verdict_does_not_decide_place_for_everyone() -> None:
    # The search names no place, but the LLM answered "elsewhere" for one candidate. Only the
    # search-level answer counts, so nobody is marked down.
    answer = _answer(
        place=False,
        judgements=[_judgement(1, 90, "elsewhere", 90), _judgement(2, 90, "not_required", 90)],
    )

    ranked = ranking.rank_by_judgements(answer, [_candidate("A"), _candidate("B")], None)

    assert {m.fit for m in ranked} == {"strong"}


def test_no_salary_criterion_without_a_budget() -> None:
    answer = _answer(judgements=[_judgement(1, 90, "same_city", 90)])

    [match] = ranking.rank_by_judgements(answer, [_candidate("A", salary=10)], None)

    assert [c.name for c in match.criteria] == ["skills", "location", "experience"]


def test_the_prompt_carries_no_pay_and_no_identity() -> None:
    # Budget is checked by code, so a salary never needs to reach OpenAI.
    prompt = ranking.build_prompt("job", [_candidate("Secret Name", salary=1_800_000)])

    assert "1800000" not in prompt
    assert "salary" not in prompt
    assert "Secret Name" not in prompt


def test_location_not_required_stands_when_no_place_is_named() -> None:
    answer = _answer(place=False, judgements=[_judgement(1, 90, "not_required", 90)])

    [match] = ranking.rank_by_judgements(answer, [_candidate("A")], None)

    assert match.fit == "strong"


def test_fuse_puts_profiles_found_by_both_lists_first() -> None:
    a, b, c, d = (uuid.uuid4() for _ in range(4))
    # c: 1/63 + 1/61; a: 1/61; b and d: 1/62 each (tie broken by id).
    fused = ranking.fuse([a, b, c], [c, d], count=4)
    assert fused[:2] == [c, a]
    assert set(fused[2:]) == {b, d}
    assert len(ranking.fuse([a, b, c], [d], count=2)) == 2


def test_skills_and_location_outrank_experience() -> None:
    pool = [_candidate("Far"), _candidate("Fits"), _candidate("Junior")]
    answer = _answer(
        judgements=[
            _judgement(1, 95, "elsewhere", 95),  # great skills and experience, wrong city
            _judgement(2, 80, "commutable", 50),  # skills + location, less experience
            _judgement(3, 40, "same_city", 20),
        ]
    )

    ranked = ranking.rank_by_judgements(answer, pool, required=None)

    assert [m.candidate.full_name for m in ranked] == ["Fits", "Far", "Junior"]
    assert [m.fit for m in ranked] == ["strong", "partial", "partial"]
    location = next(c for c in ranked[0].criteria if c.name == "location")
    assert (location.status, location.note) == ("met", "location 2")


def test_a_remote_only_candidate_misses_an_office_role_whatever_the_llm_said() -> None:
    pool = [_candidate("RemoteOnly", work_modes=("remote",)), _candidate("Office")]
    answer = _answer(
        judgements=[_judgement(1, 90, "same_city", 90), _judgement(2, 90, "same_city", 90)]
    )

    ranked = ranking.rank_by_judgements(answer, pool, required="office")

    assert [m.candidate.full_name for m in ranked] == ["Office", "RemoteOnly"]
    location = next(c for c in ranked[1].criteria if c.name == "location")
    assert location.status == "missed"
    assert "remote" in location.note


def test_remote_search_ignores_location() -> None:
    pool = [_candidate("Anywhere", work_modes=("remote",))]
    answer = _answer(judgements=[_judgement(1, 90, "elsewhere", 90)])

    [match] = ranking.rank_by_judgements(answer, pool, required="remote")

    assert match.fit == "strong"


def test_relocation_counts_only_when_the_profile_says_so() -> None:
    pool = [_candidate("Willing", relocate=True), _candidate("Unknown", relocate=None)]
    answer = _answer(
        judgements=[
            _judgement(1, 90, "willing_to_relocate", 50),
            _judgement(2, 90, "willing_to_relocate", 50),
        ]
    )

    ranked = ranking.rank_by_judgements(answer, pool, required=None)

    statuses = {
        m.candidate.full_name: next(c for c in m.criteria if c.name == "location").status
        for m in ranked
    }
    assert statuses == {"Willing": "partial", "Unknown": "missed"}


def test_a_candidate_the_llm_skipped_is_kept_last() -> None:
    pool = [_candidate("Skipped"), _candidate("Judged")]
    answer = _answer(judgements=[_judgement(2, 10, "elsewhere", 10)])

    ranked = ranking.rank_by_judgements(answer, pool, required=None)

    assert [m.candidate.full_name for m in ranked] == ["Judged", "Skipped"]
    assert ranked[1].criteria[0].note == "Not assessed"


def test_scores_out_of_range_are_clamped() -> None:
    pool = [_candidate("Odd")]
    answer = _answer(judgements=[_judgement(1, 400, "same_city", -5)])

    [match] = ranking.rank_by_judgements(answer, pool, required=None)

    assert match.fit == "strong"
    assert next(c for c in match.criteria if c.name == "experience").status == "missed"


def test_prompt_never_contains_names_or_emails() -> None:
    pool = [_candidate("Zelda")]
    prompt = ranking.build_prompt("fastapi developer", pool)
    assert "Zelda" not in prompt
    assert "zelda@example.com" not in prompt
    assert "Ghaziabad" in prompt


def test_cached_answer_expires_and_follows_profile_edits() -> None:
    ranking.clear_ranking_cache()
    pool = [_candidate("Cached")]
    answer = _answer(judgements=[_judgement(1, 90, "same_city", 90)])
    key = ranking.cache_key("gpt-5-mini", "FastAPI Dev", pool)
    ranking.remember_answer(key, answer)

    assert ranking.cached_answer(ranking.cache_key("gpt-5-mini", "fastapi dev", pool)) == answer
    edited = [
        RankableCandidate(**{**pool[0].__dict__, "updated_at": datetime(2026, 2, 1, tzinfo=UTC)})
    ]
    assert ranking.cached_answer(ranking.cache_key("gpt-5-mini", "fastapi dev", edited)) is None
    ranking.clear_ranking_cache()
