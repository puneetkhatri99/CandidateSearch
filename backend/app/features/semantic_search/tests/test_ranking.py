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
) -> RankableCandidate:
    payload = valid_candidate_payload()
    summary = CandidateSummary(
        id=uuid.uuid4(),
        full_name=name,
        email=f"{name.lower()}@example.com",
        headline=payload["headline"],
        city="Ghaziabad",
        country_code="IN",
        years_experience=6,
        top_skills=["FastAPI"],
        expected_salary=salary,
        salary_currency=None if salary is None else "INR",
        source="manual",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    return RankableCandidate(
        summary=summary,
        profile_text="Backend engineer. Skills: FastAPI.",
        city="Ghaziabad",
        country_code="IN",
        years_experience=6,
        skills=("fastapi",),
        work_modes=work_modes,
        open_to_relocation=relocate,
        expected_salary=salary,
        salary_currency=None if salary is None else "INR",
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _answer(
    *, judgements: list[CandidateJudgement], place: bool = True, pay: bool = False
) -> RankingAnswer:
    return RankingAnswer(search_names_place=place, search_states_pay=pay, judgements=judgements)


def _judgement(
    number: int, skills: int, location: str, experience: int, salary: str = "not_required"
) -> CandidateJudgement:
    return CandidateJudgement.model_validate(
        {
            "candidate": number,
            "skills_score": skills,
            "skills_note": f"skills {number}",
            "location": location,
            "location_note": f"location {number}",
            "experience_score": experience,
            "experience_note": f"experience {number}",
            "salary": salary,
            "salary_note": f"salary {number}",
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


def test_pay_comes_after_the_skills_score_and_before_experience() -> None:
    pricey, affordable, stronger = (
        _candidate("Pricey", salary=3_000_000),
        _candidate("Fits", salary=1_800_000),
        _candidate("Stronger", salary=3_000_000),
    )
    answer = _answer(
        pay=True,
        judgements=[
            _judgement(1, 80, "same_city", 95, salary="above"),
            _judgement(2, 80, "same_city", 60, salary="within"),
            _judgement(3, 95, "same_city", 40, salary="above"),
        ],
    )

    ranked = ranking.rank_by_judgements(answer, [pricey, affordable, stronger], None)

    # Better skills win over budget; with equal skills, within budget beats more experience.
    assert [m.candidate.full_name for m in ranked] == ["Stronger", "Fits", "Pricey"]
    assert (ranked[2].criteria[3].name, ranked[2].criteria[3].status) == ("salary", "missed")


def test_one_odd_verdict_does_not_decide_place_or_pay_for_everyone() -> None:
    # The search names no place and no pay, but the LLM answered "elsewhere" and "above" for
    # one candidate. Only the search-level answers count, so nobody is marked down.
    answer = _answer(
        place=False,
        pay=False,
        judgements=[
            _judgement(1, 90, "elsewhere", 90, salary="above"),
            _judgement(2, 90, "not_required", 90),
        ],
    )

    ranked = ranking.rank_by_judgements(answer, [_candidate("A", salary=10), _candidate("B")], None)

    assert {m.fit for m in ranked} == {"strong"}
    assert all(len(m.criteria) == 3 for m in ranked)


def test_salary_without_a_stated_expectation_is_unknown_not_a_guess() -> None:
    answer = _answer(
        pay=True,
        judgements=[
            _judgement(1, 90, "same_city", 90, salary="within"),
            _judgement(2, 90, "same_city", 90, salary="not_required"),
        ],
    )

    ranked = ranking.rank_by_judgements(answer, [_candidate("A"), _candidate("B")], None)

    # A states no expectation; for B the search states pay, so "not required" can't stand.
    assert [(m.criteria[3].status, m.criteria[3].note) for m in ranked] == [
        ("partial", "No expected salary stated"),
        ("partial", "No expected salary stated"),
    ]


def test_no_salary_criterion_when_pay_is_not_asked() -> None:
    answer = _answer(judgements=[_judgement(1, 90, "same_city", 90)])

    [match] = ranking.rank_by_judgements(answer, [_candidate("A", salary=10)], None)

    assert [c.name for c in match.criteria] == ["skills", "location", "experience"]


def test_the_prompt_carries_the_expected_salary_but_no_identity() -> None:
    prompt = ranking.build_prompt("job", [_candidate("Secret Name", salary=1_800_000)])

    assert '"expected_yearly_salary": "1800000 INR"' in prompt
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
