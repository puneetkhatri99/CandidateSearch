import math
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.features.semantic_search.evaluation import (
    CaseScore,
    EvalReport,
    GoldenCandidate,
    GoldenCase,
    experience_band,
    group_rates,
    ndcg_at,
    precision_at,
    report_markdown,
)


def person(
    email: str, country: str = "IN", years: float = 5, grade: int | None = 3
) -> GoldenCandidate:
    return GoldenCandidate(email=email, profile="", country=country, years=years, grade=grade)


def test_ndcg_is_1_for_the_ideal_order_and_lower_when_swapped() -> None:
    grades = {"a": 3, "b": 2, "c": 0}
    assert ndcg_at(["a", "b", "c"], grades) == pytest.approx(1.0)
    swapped = ndcg_at(["b", "a", "c"], grades)
    ideal = 7 + 3 / math.log2(3)
    assert swapped == pytest.approx((3 + 7 / math.log2(3)) / ideal)
    assert swapped is not None and swapped < 1


def test_ndcg_counts_ungraded_results_as_0_and_is_none_with_nothing_to_find() -> None:
    assert ndcg_at(["x", "a"], {"a": 3}) == pytest.approx(1 / math.log2(3))
    assert ndcg_at(["a"], {"a": 0, "b": 0}) is None


def test_ndcg_only_looks_at_the_top_k() -> None:
    assert ndcg_at(["x", "a"], {"a": 3}, k=1) == 0


def test_precision_counts_grades_of_2_and_up_and_divides_by_k() -> None:
    grades = {"a": 3, "b": 2, "c": 1}
    assert precision_at(["a", "b", "c", "x", "y"], grades) == pytest.approx(2 / 5)
    # Fewer results than k still divide by k: missing results are misses.
    assert precision_at(["a"], grades) == pytest.approx(1 / 5)


def test_experience_bands() -> None:
    assert [experience_band(y) for y in (0, 2.9, 3, 7.9, 8, 14.9, 15, 30)] == [
        "0-3 years", "0-3 years", "3-8 years", "3-8 years",
        "8-15 years", "8-15 years", "15+ years", "15+ years",
    ]  # fmt: skip


def test_group_rates_flag_a_group_found_at_under_four_fifths_of_the_best() -> None:
    outcomes = [(person(f"in{i}", "IN"), True) for i in range(5)] + [
        (person(f"us{i}", "US"), i < 3) for i in range(5)
    ]
    rows = {r.group: r for r in group_rates(outcomes, "country")}
    assert (rows["IN"].rate, rows["IN"].impact_ratio, rows["IN"].flagged) == (1.0, 1.0, False)
    assert (rows["US"].found, rows["US"].impact_ratio, rows["US"].flagged) == (3, 0.6, True)


def test_group_rates_do_not_judge_groups_that_are_too_small() -> None:
    outcomes = [(person(f"in{i}", "IN"), True) for i in range(5)] + [(person("de", "DE"), False)]
    rows = {r.group: r for r in group_rates(outcomes, "country")}
    assert rows["DE"].impact_ratio is None
    assert not rows["DE"].flagged


def test_group_rates_by_experience() -> None:
    rows = group_rates([(person("a", years=1), True), (person("b", years=20), False)], "experience")
    assert [(r.group, r.found) for r in rows] == [("0-3 years", 1), ("15+ years", 0)]


def test_a_case_counts_as_graded_only_when_every_candidate_has_a_grade() -> None:
    assert GoldenCase(id="c", query="q", candidates=[person("a"), person("b")]).graded
    assert not GoldenCase(
        id="c", query="q", candidates=[person("a"), person("b", grade=None)]
    ).graded
    assert not GoldenCase(id="c", query="q", candidates=[]).graded


def test_grades_must_be_0_to_3() -> None:
    with pytest.raises(ValidationError):
        person("a", grade=4)


def test_the_report_names_flags_skips_and_fallbacks() -> None:
    report = EvalReport(
        run_at=datetime(2026, 11, 2, 12, 0, tzinfo=UTC),
        ranking_model="gpt-5.4-mini",
        ranking_prompt_version="rank_v7",
        understanding_prompt_version="understand_v3",
        cases=[
            CaseScore(
                id="python-pune",
                ranked_by="search",
                ndcg_at_10=0.8,
                precision_at_5=0.6,
                unjudged_in_top_10=1,
                top_10=[],
            )
        ],
        skipped_ungraded=["react-remote"],
        mean_ndcg_at_10=0.8,
        mean_precision_at_5=0.6,
        fairness=group_rates(
            [(person(f"in{i}", "IN"), True) for i in range(5)]
            + [(person(f"us{i}", "US"), i < 2) for i in range(5)],
            "country",
        ),
    )
    text = report_markdown(report)
    assert "| python-pune | search | 0.8 | 0.6 | 1 |" in text
    assert "| country | US | 5 | 2 | 0.4 | 0.4 | FLAG |" in text
    assert "Skipped, not fully graded: react-remote." in text
    assert "fell back to search order" in text
    assert "Not checked (not collected): gender, age, ethnicity." in text
