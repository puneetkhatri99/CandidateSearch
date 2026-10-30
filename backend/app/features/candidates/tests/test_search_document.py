from app.features.candidates.schemas import CandidateCreate
from app.features.candidates.search_document import build_search_document, redact_identifiers
from app.features.candidates.tests.factories import valid_candidate_payload


def _document(**overrides: object) -> str:
    return build_search_document(
        CandidateCreate.model_validate(valid_candidate_payload(**overrides))
    )


def test_document_contains_matching_signals() -> None:
    doc = _document()

    assert "Senior Backend Engineer." in doc
    assert "6.5 years experience." in doc
    assert "Skills: python, fastapi, postgresql." in doc
    assert "Senior Backend Engineer at Acme Payments (2021-03 to present)" in doc
    assert "Backend Engineer at Globex (2018-06 to 2021-02)" in doc
    assert "B.Tech Computer Science, IIT Delhi (2014 to 2018)." in doc
    assert "Desired roles: backend engineer, platform engineer." in doc
    assert "Work mode: remote, hybrid." in doc


def test_document_excludes_direct_identifiers() -> None:
    summary = (
        "I'm Asha Verma, reach me at asha.verma@example.com or +91 98765 43210. "
        "See https://asha.dev and linkedin.com/in/asha-verma for my 2019-2023 projects."
    )
    doc = _document(summary=summary).lower()

    for identifier in ("asha", "verma", "@", "98765", "https://", "linkedin.com", "asha.dev"):
        assert identifier not in doc
    assert "2019-2023" in doc


def test_whole_years_have_no_trailing_decimal() -> None:
    assert "5 years experience." in _document(years_experience=5)


def test_short_name_parts_are_not_stripped_from_words() -> None:
    # "Al" is shorter than the minimum, so "Algorithms" must survive.
    assert redact_identifiers("Algorithms expert", "Al Smith") == "Algorithms expert"
