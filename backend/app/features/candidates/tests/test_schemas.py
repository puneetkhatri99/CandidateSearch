from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from app.features.candidates.schemas import CandidateCreate
from app.features.candidates.tests.factories import valid_candidate_payload


def _errors(**overrides: Any) -> list[tuple[tuple[str | int, ...], str]]:
    with pytest.raises(ValidationError) as exc_info:
        CandidateCreate.model_validate(valid_candidate_payload(**overrides))
    return [(tuple(e["loc"]), e["msg"]) for e in exc_info.value.errors()]


def _locs(**overrides: Any) -> list[tuple[str | int, ...]]:
    return [loc for loc, _ in _errors(**overrides)]


def test_valid_payload_is_normalized() -> None:
    candidate = CandidateCreate.model_validate(
        valid_candidate_payload(email="Asha.Verma@Example.COM", country_code="in")
    )

    assert candidate.email == "asha.verma@example.com"
    assert candidate.country_code == "IN"
    assert candidate.phone == "+919876543210"
    assert candidate.skills == ["python", "fastapi", "postgresql"]
    assert candidate.desired_roles == ["backend engineer", "platform engineer"]
    assert candidate.portfolio_url is None
    assert candidate.years_experience == Decimal("6.5")
    assert candidate.experiences[0].end_month is None


def test_expected_salary_is_optional_and_needs_its_currency() -> None:
    candidate = CandidateCreate.model_validate(
        valid_candidate_payload(expected_salary=1_800_000, salary_currency="inr")
    )
    assert (candidate.expected_salary, candidate.salary_currency) == (1_800_000, "INR")
    assert CandidateCreate.model_validate(valid_candidate_payload()).expected_salary is None
    assert ("salary_currency",) in _locs(expected_salary=1_800_000)
    assert ("salary_currency",) in _locs(salary_currency="INR")
    assert ("expected_salary",) in _locs(expected_salary=0, salary_currency="INR")
    assert ("expected_salary",) in _locs(expected_salary=10**10, salary_currency="INR")


def test_skills_must_not_be_empty_after_cleanup() -> None:
    assert ("skills",) in _locs(skills=["  ", ""])


def test_skill_too_long_rejected() -> None:
    assert ("skills",) in _locs(skills=["x" * 51])


def test_more_than_50_unique_skills_rejected() -> None:
    assert ("skills",) in _locs(skills=[f"skill{i}" for i in range(51)])


@pytest.mark.parametrize("phone", ["12345", "+0123456789", "phone"])
def test_invalid_phone_rejected(phone: str) -> None:
    assert ("phone",) in _locs(phone=phone)


def test_unknown_country_rejected() -> None:
    assert ("country_code",) in _locs(country_code="XX")


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("linkedin.com/in/asha", "https://linkedin.com/in/asha"),
        ("https://in.linkedin.com/in/asha", "https://in.linkedin.com/in/asha"),
    ],
)
def test_linkedin_url_accepted(url: str, expected: str) -> None:
    candidate = CandidateCreate.model_validate(valid_candidate_payload(linkedin_url=url))
    assert candidate.linkedin_url == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/in/asha",
        "https://linkedin.com/company/acme",
        "https://linkedin.com/in/",
        "https://notlinkedin.com/in/asha",
    ],
)
def test_bad_linkedin_url_rejected(url: str) -> None:
    assert ("linkedin_url",) in _locs(linkedin_url=url)


def test_github_url_requires_github_host() -> None:
    assert ("github_url",) in _locs(github_url="https://gitlab.com/asha")


def test_portfolio_requires_https() -> None:
    assert ("portfolio_url",) in _locs(portfolio_url="http://asha.dev")


@pytest.mark.parametrize("years", [-1, 51, 5.25])
def test_years_experience_bounds_and_precision(years: float) -> None:
    assert ("years_experience",) in _locs(years_experience=years)


def test_summary_minimum_length() -> None:
    assert ("summary",) in _locs(summary="Too short.")


def test_current_role_must_not_have_end_month() -> None:
    experiences = [
        {
            "company": "A",
            "title": "T",
            "start_month": "2020-01",
            "is_current": True,
            "end_month": "2021-01",
        },
    ]
    assert ("experiences", 0, "end_month") in _locs(experiences=experiences)


def test_past_role_requires_end_month() -> None:
    experiences = [{"company": "A", "title": "T", "start_month": "2020-01", "is_current": False}]
    assert ("experiences", 0, "end_month") in _locs(experiences=experiences)


def test_end_month_before_start_rejected() -> None:
    experiences = [
        {"company": "A", "title": "T", "start_month": "2020-05", "end_month": "2020-01"},
    ]
    assert ("experiences", 0, "end_month") in _locs(experiences=experiences)


def test_future_start_month_rejected() -> None:
    experiences = [{"company": "A", "title": "T", "start_month": "2999-01", "is_current": True}]
    assert ("experiences", 0, "start_month") in _locs(experiences=experiences)


def test_bad_month_format_rejected() -> None:
    experiences = [{"company": "A", "title": "T", "start_month": "2020-13", "is_current": True}]
    assert ("experiences", 0, "start_month") in _locs(experiences=experiences)


def test_only_one_current_role() -> None:
    role = {"company": "A", "title": "T", "start_month": "2020-01", "is_current": True}
    assert ("experiences",) in _locs(experiences=[role, {**role, "company": "B"}])


def test_too_many_experiences_rejected() -> None:
    role = {"company": "A", "title": "T", "start_month": "2020-01", "end_month": "2020-02"}
    assert ("experiences",) in _locs(experiences=[role] * 16)


def test_education_end_before_start_rejected() -> None:
    educations = [{"institution": "X", "start_year": 2018, "end_year": 2015}]
    assert ("educations", 0, "end_year") in _locs(educations=educations)


def test_work_modes_required_and_restricted() -> None:
    assert ("work_modes",) in _locs(work_modes=[])
    assert ("work_modes", 0) in _locs(work_modes=["office"])


def test_work_modes_deduplicated() -> None:
    candidate = CandidateCreate.model_validate(
        valid_candidate_payload(work_modes=["remote", "remote"])
    )
    assert candidate.work_modes == ["remote"]


def test_consent_required_with_readable_message() -> None:
    errors = _errors(consent=False)
    assert (("consent",), "You must agree to the privacy notice to continue.") in errors


def test_unknown_fields_rejected() -> None:
    assert ("is_admin",) in _locs(is_admin=True)


def test_notice_period_bounds() -> None:
    assert ("notice_period_days",) in _locs(notice_period_days=181)
