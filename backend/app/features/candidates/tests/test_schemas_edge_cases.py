"""Schema edge cases found during Phase 1 QA.

xfail(strict=True) tests document open bugs; remove the marker when the bug is fixed.
"""

from typing import Any

import pytest
from pydantic import ValidationError

from app.features.candidates.schemas import CandidateCreate
from app.features.candidates.tests.factories import valid_candidate_payload


def _locs(**overrides: Any) -> list[tuple[str | int, ...]]:
    with pytest.raises(ValidationError) as exc_info:
        CandidateCreate.model_validate(valid_candidate_payload(**overrides))
    return [tuple(e["loc"]) for e in exc_info.value.errors()]


def test_tabs_and_repeated_spaces_inside_skills_are_collapsed() -> None:
    candidate = CandidateCreate.model_validate(
        valid_candidate_payload(skills=["Machine\t\tLearning", "machine learning", " C++ "])
    )
    assert candidate.skills == ["machine learning", "c++"]


def test_skill_limit_counts_unique_skills_only() -> None:
    # 60 entries but only 50 unique after normalization: allowed.
    skills = [f"Skill{i}" for i in range(50)] + [f"skill{i}" for i in range(10)]
    candidate = CandidateCreate.model_validate(valid_candidate_payload(skills=skills))
    assert len(candidate.skills) == 50


def test_desired_roles_limit() -> None:
    assert ("desired_roles",) in _locs(desired_roles=[f"role {i}" for i in range(11)])


def test_full_name_whitespace_only_rejected() -> None:
    assert ("full_name",) in _locs(full_name="   ")


@pytest.mark.parametrize("length", [121])
def test_headline_too_long_rejected(length: int) -> None:
    assert ("headline",) in _locs(headline="h" * length)


def test_experience_description_limit() -> None:
    experience = {
        "company": "A",
        "title": "T",
        "start_month": "2020-01",
        "is_current": True,
        "description": "d" * 2001,
    }
    assert ("experiences", 0, "description") in _locs(experiences=[experience])


def test_too_many_educations_rejected() -> None:
    assert ("educations",) in _locs(educations=[{"institution": "X"}] * 11)


def test_education_year_before_1950_rejected() -> None:
    assert ("educations", 0, "start_year") in _locs(
        educations=[{"institution": "X", "start_year": 1949}]
    )


def test_nan_years_experience_rejected() -> None:
    assert ("years_experience",) in _locs(years_experience="NaN")


def test_github_url_without_username_rejected() -> None:
    assert ("github_url",) in _locs(github_url="https://github.com/")


def test_portfolio_javascript_scheme_rejected() -> None:
    assert ("portfolio_url",) in _locs(portfolio_url="javascript://example.com/%0aalert(1)")


def test_linkedin_userinfo_trick_rejected() -> None:
    assert ("linkedin_url",) in _locs(linkedin_url="https://linkedin.com@evil.example/in/x")


@pytest.mark.parametrize(
    ("field", "url"),
    [
        # urlsplit sees linkedin.com/github.com, but browsers treat "\" as "/" and go elsewhere.
        ("linkedin_url", "https://evil.example\\@linkedin.com/in/x"),
        ("github_url", "https://evil.example\\@github.com/x"),
        ("portfolio_url", "https://evil.example\\@asha.dev"),
        ("linkedin_url", "https://user@linkedin.com/in/x"),
        ("github_url", "https://github.com/ash a"),
    ],
)
def test_ambiguous_urls_rejected(field: str, url: str) -> None:
    assert (field,) in _locs(**{field: url})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("notice_period_days", True),
        ("years_experience", True),
        ("consent", "true"),
        ("open_to_relocation", "yes"),
    ],
)
def test_wrong_scalar_types_are_not_coerced(field: str, value: object) -> None:
    assert (field,) in _locs(**{field: value})


def test_bool_education_year_rejected() -> None:
    assert ("educations", 0, "start_year") in _locs(
        educations=[{"institution": "X", "start_year": True}]
    )


def test_experience_before_1950_rejected() -> None:
    experiences = [{"company": "A", "title": "T", "start_month": "0001-01", "end_month": "2020-01"}]
    assert ("experiences", 0, "start_month") in _locs(experiences=experiences)


@pytest.mark.parametrize(
    "overrides",
    [
        {"full_name": "Asha\u0000Verma"},
        {"skills": ["py\u0000thon"]},
        {
            "experiences": [
                {"company": "A\u0000", "title": "T", "start_month": "2020-01", "is_current": True}
            ]
        },
    ],
    ids=["full_name", "skills", "nested_experience"],
)
def test_nul_characters_rejected(overrides: dict[str, Any]) -> None:
    assert _locs(**overrides)


def test_empty_userinfo_rejected() -> None:
    assert ("linkedin_url",) in _locs(linkedin_url="https://@linkedin.com/in/x")


def test_nfkc_netloc_gets_readable_url_error() -> None:
    with pytest.raises(ValidationError) as exc_info:
        CandidateCreate.model_validate(
            valid_candidate_payload(linkedin_url="https://evil.example\uff0f.linkedin.com/in/x")
        )
    messages = [e["msg"] for e in exc_info.value.errors() if e["loc"] == ("linkedin_url",)]
    assert messages == ["Enter a valid URL."]
