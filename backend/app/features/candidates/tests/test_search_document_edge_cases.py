"""search_document PII edge cases found during Phase 1 QA.

xfail(strict=True) tests document open gaps; remove the marker when fixed.
"""

import re

import pytest

from app.features.candidates.schemas import CandidateCreate
from app.features.candidates.search_document import build_search_document, redact_identifiers
from app.features.candidates.tests.factories import valid_candidate_payload


def _document(**overrides: object) -> str:
    return build_search_document(
        CandidateCreate.model_validate(valid_candidate_payload(**overrides))
    )


def test_unicode_name_is_redacted_case_insensitively() -> None:
    doc = _document(
        full_name="José Núñez",
        summary="JOSÉ NÚÑEZ here. I build payment systems and data pipelines at scale.",
    ).lower()
    assert "josé" not in doc
    assert "núñez" not in doc


@pytest.mark.parametrize(
    "text",
    [
        "Call 98765-43210 anytime",
        "Call (987) 654-3210 anytime",
        "Call +1 415 555 0100 anytime",
    ],
)
def test_phone_formats_are_redacted(text: str) -> None:
    assert redact_identifiers(text, "X Y") == "Call anytime"


def test_identifiers_in_headline_and_experience_description_are_redacted() -> None:
    experience = {
        "company": "Acme",
        "title": "Engineer",
        "start_month": "2020-01",
        "is_current": True,
        "description": "Ask asha.verma@example.com or see https://example.org/x.",
    }
    doc = _document(headline="Engineer https://asha.dev", experiences=[experience])
    assert "@" not in doc
    assert "https://" not in doc


def test_technology_names_with_dots_survive() -> None:
    assert redact_identifiers("next.js and node.js expert", "X Y") == "next.js and node.js expert"


def test_identifiers_in_every_typed_field_are_redacted() -> None:
    experience = {
        "company": "Asha Verma Consulting",
        "title": "Owner, call +91 98765 43210",
        "start_month": "2020-01",
        "is_current": True,
    }
    education = {"institution": "Verma Institute", "degree": "asha@x.io", "field_of_study": "CS"}
    doc = _document(
        experiences=[experience],
        educations=[education],
        skills=["python", "asha@x.io"],
        desired_roles=["engineer at asha.dev/jobs"],
    ).lower()
    for identifier in ("asha", "verma", "98765", "@", "asha.dev"):
        assert identifier not in doc
    assert "skills: python." in doc


def test_hyphenated_name_parts_are_redacted() -> None:
    assert redact_identifiers("Mary Jane and Mary-Jane wrote this", "Mary-Jane Watson") == (
        "and wrote this"
    )


def test_decomposed_unicode_name_is_redacted() -> None:
    decomposed = "José"  # "José" typed with a combining accent
    assert redact_identifiers(f"I am {decomposed}.", "José Núñez") == "I am ."


def test_two_letter_name_parts_are_redacted_as_whole_words_only() -> None:
    assert redact_identifiers("Li built Linux tools", "Li Wu") == "built Linux tools"


def test_year_ranges_are_not_mistaken_for_phones() -> None:
    assert redact_identifiers("Projects 2015-2019-2023", "X Y") == "Projects 2015-2019-2023"


def test_hyphenated_and_split_name_forms_are_redacted() -> None:
    doc = _document(
        full_name="Mary-Jane O'Neil",
        summary="Mary-Jane here; Mary Jane and O'Neil built payment systems and data pipelines.",
    )
    # Whole words only: "Summary:" itself contains "mary".
    for part in ("mary", "jane", "neil"):
        assert re.search(rf"\b{part}\b", doc, flags=re.IGNORECASE) is None


def test_no_empty_skills_line_when_all_skills_redact_away() -> None:
    doc = _document(full_name="Python Go", skills=["python", "go"])
    assert "Skills: ." not in doc
