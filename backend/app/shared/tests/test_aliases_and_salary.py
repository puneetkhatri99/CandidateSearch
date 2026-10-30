from typing import Any

import pytest
from pydantic import ValidationError

from app.features.candidates.schemas import CandidateCreate
from app.features.candidates.tests.factories import valid_candidate_payload
from app.features.jobs.schemas import JobCreate, JobPatch
from app.features.jobs.tests.factories import valid_job_payload
from app.shared.aliases import city_spellings, skill_spellings


def test_spellings_of_the_same_skill_or_city_are_one_group() -> None:
    assert skill_spellings("Postgres") == skill_spellings("postgresql")
    assert "k8s" in skill_spellings("kubernetes")
    assert skill_spellings("rust") == frozenset({"rust"})  # unknown: only itself
    assert city_spellings(" Bangalore ") == city_spellings("bengaluru")
    assert city_spellings("Noida") == frozenset({"noida"})  # nearby is not the same city


def _error_fields(model: Any, payload: dict[str, Any]) -> list[str]:
    with pytest.raises(ValidationError) as caught:
        model.model_validate(payload)
    return [str(error["loc"][0]) for error in caught.value.errors()]


def test_one_bad_amount_gives_one_error_not_a_currency_error_too() -> None:
    bad = valid_candidate_payload(expected_salary=0, salary_currency="INR")
    assert _error_fields(CandidateCreate, bad) == ["expected_salary"]
    assert _error_fields(JobCreate, valid_job_payload(salary_max=0, salary_currency="INR")) == [
        "salary_max"
    ]


def test_only_the_currencies_the_forms_offer_are_accepted() -> None:
    assert "salary_currency" in _error_fields(
        CandidateCreate, valid_candidate_payload(expected_salary=5, salary_currency="JPY")
    )


def test_editing_a_job_is_as_strict_about_pay_as_creating_one() -> None:
    with pytest.raises(ValidationError):
        JobPatch.model_validate({"version": 1, "salary_min": "100"})


def test_tags_with_commas_are_rejected() -> None:
    assert "must_have_skills" in _error_fields(
        JobCreate, valid_job_payload(must_have_skills=["react, redux"])
    )
    assert "skills" in _error_fields(CandidateCreate, valid_candidate_payload(skills=["a,b"]))
