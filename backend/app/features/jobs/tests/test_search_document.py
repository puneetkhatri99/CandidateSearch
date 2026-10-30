from app.features.jobs.schemas import JobFields
from app.features.jobs.search_document import build_job_search_document
from app.features.jobs.tests.factories import valid_job_payload

DESCRIPTION = "Build services. " * 8


def _document(names: list[str] | None = None, **overrides: object) -> str:
    overrides.setdefault("description", DESCRIPTION)
    job = JobFields.model_validate(valid_job_payload(**overrides))
    return build_job_search_document(job, names or [])


def test_document_has_the_exact_format() -> None:
    assert _document() == (
        "Senior Backend Engineer.\n"
        "Department: Platform.\n"
        "Employment type: full-time. Work mode: hybrid.\n"
        "Location: Berlin, Germany.\n"
        "Experience: 3-6 years.\n"
        "Must-have skills: python, postgresql.\n"
        "Nice-to-have skills: kubernetes.\n"
        f"Description: {DESCRIPTION.strip()}"
    )


def test_optional_lines_are_omitted() -> None:
    document = _document(
        department=None,
        work_mode="remote",
        city=None,
        country_code=None,
        max_years=None,
        min_years=4.5,
        nice_to_have_skills=[],
    )

    assert "Department" not in document
    assert "Location" not in document
    assert "Nice-to-have" not in document
    assert "Experience: 4.5+ years." in document
    assert "Work mode: remote." in document


def test_status_is_not_part_of_the_document() -> None:
    assert _document(status="draft") == _document(status="closed")


def test_free_text_is_redacted_in_every_field() -> None:
    document = _document(
        ["Maria Gonzalez", "Omar Haddad"],
        title="Engineer for maria@example.com",
        department="Platform, call +49 170 1234567",
        city="Berlin",
        must_have_skills=["python", "https://evil.example/x"],
        description=(
            "Contact Maria Gonzalez or Omar Haddad at omar@example.com, "
            "see https://jobs.example.com/apply for details. " + DESCRIPTION
        ),
    )

    for leaked in (
        "maria",
        "Maria",
        "Gonzalez",
        "Omar",
        "example.com",
        "+49",
        "1234567",
        "evil.example",
        "https",
    ):
        assert leaked not in document


def test_the_country_name_is_rendered() -> None:
    assert "Location: Pune, India." in _document(city="Pune", country_code="IN")
