import pytest

from app.features.resumes.mapping import (
    is_still_there,
    parse_month,
    parse_year,
    sort_links,
    split_location,
    to_profile,
    years_of_experience,
)
from app.features.resumes.schemas import (
    ExperienceSuggestion,
    ResumeAIData,
    ResumeAIEducation,
    ResumeAIExperience,
)


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("Jan 2021", "2021-01"),
        ("January 2021", "2021-01"),
        ("Sept. 2019", "2019-09"),
        ("03/2020", "2020-03"),
        ("2020-11", "2020-11"),
        ("2018", "2018-01"),
        ("Present", None),
        ("Spring 2020", None),
        ("13/2020", None),
        ("1900", None),
        ("Jan 2999", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_month(written: str | None, expected: str | None) -> None:
    assert parse_month(written) == expected


def test_parse_year_and_present() -> None:
    assert parse_year("Aug 2017") == 2017
    assert parse_year("Expected") is None
    assert is_still_there(" Present ") and is_still_there("till date")
    assert not is_still_there("Dec 2020")


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("Pune, India", ("Pune", "IN")),
        ("Bengaluru, Karnataka, India", ("Bengaluru", "IN")),
        ("Austin, TX, USA", ("Austin", "US")),
        ("London, UK", ("London", "GB")),
        ("Germany", (None, "DE")),
        ("Pune", ("Pune", None)),
        ("  ", (None, None)),
        (None, (None, None)),
    ],
)
def test_split_location(location: str | None, expected: tuple[str | None, str | None]) -> None:
    assert split_location(location) == expected


def test_sort_links_picks_the_first_of_each_kind() -> None:
    links = [
        "linkedin.com/company/acme",
        "https://www.linkedin.com/in/priya",
        "https://github.com/priya",
        "https://github.com/other",
        "http://insecure.example",
        "https://priya.dev",
    ]

    assert sort_links(links) == (
        "https://www.linkedin.com/in/priya",
        "https://github.com/priya",
        "https://priya.dev",
    )


def _role(start: str | None, end: str | None, current: bool = False) -> ExperienceSuggestion:
    return ExperienceSuggestion(
        company="Acme", title="Engineer", start_month=start, is_current=current,
        end_month=end, description=None,
    )  # fmt: skip


def test_years_of_experience_spans_first_start_to_last_end() -> None:
    assert years_of_experience([_role("2015-01", "2018-01"), _role("2018-02", "2021-07")]) == 6.5
    assert years_of_experience([_role(None, None)]) is None


def test_to_profile_maps_the_guide_example() -> None:
    data = ResumeAIData(
        name="Priya Raman",
        email="priya.raman@example.com",
        phone="+91 98765 43210",
        location="Pune, India",
        links=["https://github.com/priya-raman-example"],
        skills=["Python", "FastAPI", " python ", "C, C++"],
        experience=[
            ResumeAIExperience(
                company="Nimbus Logistics", title="Senior Backend Engineer",
                start_date="Jan 2021", end_date="Present",
                description="Built a shipment-tracking API\nCut p95 latency by 40%",
            ),
            ResumeAIExperience(
                company="Old Co", title="Engineer", start_date="Jul 2017", end_date="Current",
            ),
            ResumeAIExperience(company=None, title="No company", start_date="2015"),
        ],
        education=[
            ResumeAIEducation(
                institution="College of Engineering Pune", degree="B.Tech",
                field_of_study="Computer Science", start_date="2017", end_date="2013",
            )
        ],
    )  # fmt: skip

    profile = to_profile(data)

    assert (profile.full_name, profile.city, profile.country_code) == ("Priya Raman", "Pune", "IN")
    assert profile.github_url == "https://github.com/priya-raman-example"
    assert profile.headline == "Senior Backend Engineer"
    # Duplicates merge; a skill containing a comma can't be a tag.
    assert profile.skills == ["python", "fastapi"]
    first, second = profile.experiences
    assert (first.start_month, first.is_current, first.end_month) == ("2021-01", True, None)
    # Only one role can be current: the second "Current" is left for the person to fix.
    assert (second.is_current, second.end_month) == (False, None)
    assert first.description == "Built a shipment-tracking API\nCut p95 latency by 40%"
    # An end year before the start year is dropped rather than failing the form.
    assert profile.educations[0].start_year == 2017
    assert profile.educations[0].end_year is None
    assert profile.years_experience is not None and profile.years_experience >= 9


def test_to_profile_of_an_empty_resume_suggests_nothing() -> None:
    profile = to_profile(ResumeAIData())

    assert profile.model_dump(exclude_defaults=True) == {}
