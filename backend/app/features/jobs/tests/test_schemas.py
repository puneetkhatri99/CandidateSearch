from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from app.features.jobs.schemas import JobCreate, JobPatch
from app.features.jobs.tests.factories import valid_job_payload

DESCRIPTION_100 = "x" * 100


def _errors(**overrides: Any) -> dict[str, str]:
    """Field name -> error type for a payload that must be rejected."""
    with pytest.raises(ValidationError) as caught:
        JobCreate.model_validate(valid_job_payload(**overrides))
    return {str(error["loc"][0]): error["type"] for error in caught.value.errors()}


def test_a_valid_payload_passes_and_is_normalised() -> None:
    job = JobCreate.model_validate(
        valid_job_payload(
            title="  Engineer  ",
            department="  ",
            country_code="de",
            must_have_skills=["  Python ", "python", "Post  GRES"],
        )
    )

    assert job.title == "Engineer"
    assert job.department is None
    assert job.country_code == "DE"
    assert job.must_have_skills == ["python", "post gres"]
    assert job.min_years == Decimal(3)


@pytest.mark.parametrize(("length", "ok"), [(120, True), (121, False)])
def test_title_length_boundary(length: int, ok: bool) -> None:
    payload = valid_job_payload(title="t" * length)
    if ok:
        JobCreate.model_validate(payload)
    else:
        assert "title" in _errors(title="t" * length)


def test_blank_title_is_rejected() -> None:
    assert "title" in _errors(title="   ")


@pytest.mark.parametrize(
    ("description", "ok"),
    [
        ("x" * 99, False),
        (DESCRIPTION_100, True),
        ("x" * 10_000, True),
        ("x" * 10_001, False),
        ("  " + "x" * 99 + "  ", False),  # trimmed before counting
    ],
)
def test_description_length_boundary_after_trim(description: str, ok: bool) -> None:
    if ok:
        JobCreate.model_validate(valid_job_payload(description=description))
    else:
        assert "description" in _errors(description=description)


@pytest.mark.parametrize(
    ("minimum", "ok"),
    [(-0.1, False), (0, True), (50, True), (50.1, False), (3.25, False), (4.5, True)],
)
def test_min_years_range_and_precision(minimum: float, ok: bool) -> None:
    overrides = {"min_years": minimum, "max_years": None}
    if ok:
        JobCreate.model_validate(valid_job_payload(**overrides))
    else:
        assert "min_years" in _errors(**overrides)


def test_boolean_years_are_rejected() -> None:
    assert _errors(min_years=True, max_years=None)["min_years"] == "number_type"


def test_max_years_cannot_be_below_min_years() -> None:
    assert _errors(min_years=5, max_years=4)["max_years"] == "max_below_min"
    JobCreate.model_validate(valid_job_payload(min_years=5, max_years=5))


def test_max_years_is_optional() -> None:
    assert JobCreate.model_validate(valid_job_payload(max_years=None)).max_years is None


@pytest.mark.parametrize(
    ("skills", "ok"),
    [
        ([], False),
        (["a", "A", " a "], True),  # one skill after de-duplication
        ([f"skill {i}" for i in range(20)], True),
        ([f"skill {i}" for i in range(21)], False),
        (["s" * 50], True),
        (["s" * 51], False),
    ],
)
def test_must_have_skill_counts_are_checked_after_normalising(skills: list[str], ok: bool) -> None:
    if ok:
        JobCreate.model_validate(valid_job_payload(must_have_skills=skills, nice_to_have_skills=[]))
    else:
        assert "must_have_skills" in _errors(must_have_skills=skills, nice_to_have_skills=[])


def test_nice_to_have_is_optional_and_capped() -> None:
    JobCreate.model_validate(valid_job_payload(nice_to_have_skills=[]))
    too_many = [f"extra {i}" for i in range(21)]
    assert "nice_to_have_skills" in _errors(nice_to_have_skills=too_many)


def test_a_skill_cannot_be_both_must_have_and_nice_to_have() -> None:
    errors = _errors(must_have_skills=["Python"], nice_to_have_skills=["python"])
    assert errors["nice_to_have_skills"] == "skill_in_both"


def test_remote_jobs_need_no_location() -> None:
    job = JobCreate.model_validate(
        valid_job_payload(work_mode="remote", city="", country_code=None)
    )
    assert (job.city, job.country_code) == (None, None)


@pytest.mark.parametrize("work_mode", ["hybrid", "onsite"])
def test_site_based_jobs_need_a_city_and_country(work_mode: str) -> None:
    errors = _errors(work_mode=work_mode, city=None, country_code=None)
    assert errors == {"city": "city_required", "country_code": "country_required"}


def test_a_city_without_a_country_is_rejected_even_for_remote() -> None:
    errors = _errors(work_mode="remote", city="Paris", country_code=None)
    assert errors == {"country_code": "country_required"}


def test_country_codes_are_validated() -> None:
    assert _errors(country_code="XX") == {"country_code": "country_code"}
    assert JobCreate.model_validate(valid_job_payload(country_code="in")).country_code == "IN"


@pytest.mark.parametrize("field", ["title", "department", "city", "description"])
def test_nul_characters_are_rejected_in_text_fields(field: str) -> None:
    value = "ab\x00cd" + ("x" * 120 if field == "description" else "")
    assert _errors(**{field: value})[field] == "invalid_characters"


def test_nul_characters_are_rejected_inside_skill_lists() -> None:
    assert _errors(must_have_skills=["py\x00thon"])["must_have_skills"] == "invalid_characters"


def test_unknown_fields_are_rejected() -> None:
    assert _errors(salary=100) == {"salary": "extra_forbidden"}


@pytest.mark.parametrize(
    ("field", "value"),
    [("work_mode", "moon"), ("employment_type", "gig"), ("status", "archived")],
)
def test_enum_fields_reject_unknown_values(field: str, value: str) -> None:
    assert field in _errors(**{field: value})


def test_a_pay_range_is_yearly_with_a_currency() -> None:
    job = JobCreate.model_validate(
        valid_job_payload(salary_min=1_500_000, salary_max=2_400_000, salary_currency=" inr ")
    )
    assert (job.salary_min, job.salary_max, job.salary_currency) == (1_500_000, 2_400_000, "INR")
    # Either end may be open.
    assert JobCreate.model_validate(valid_job_payload(salary_max=90_000, salary_currency="EUR"))


@pytest.mark.parametrize(
    ("overrides", "field", "error"),
    [
        ({"salary_min": 100}, "salary_currency", "currency_required"),
        ({"salary_currency": "INR"}, "salary_currency", "salary_required"),
        (
            {"salary_min": 10, "salary_max": 5, "salary_currency": "INR"},
            "salary_max",
            "max_below_min",
        ),
        ({"salary_min": 0, "salary_currency": "INR"}, "salary_min", "greater_than_equal"),
        ({"salary_min": True, "salary_currency": "INR"}, "salary_min", "number_type"),
        ({"salary_min": "100", "salary_currency": "INR"}, "salary_min", "int_type"),
        ({"salary_min": 100, "salary_currency": "XYZ"}, "salary_currency", "currency_code"),
    ],
)
def test_pay_range_rules(overrides: dict[str, Any], field: str, error: str) -> None:
    assert _errors(**overrides)[field] == error


def test_patch_keeps_explicit_nulls_as_set_fields() -> None:
    patch = JobPatch.model_validate({"version": 2, "department": None})

    assert patch.model_dump(exclude_unset=True) == {"version": 2, "department": None}


def test_patch_requires_a_version_and_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        JobPatch.model_validate({"title": "x"})
    with pytest.raises(ValidationError):
        JobPatch.model_validate({"version": 1, "owner": "x"})
