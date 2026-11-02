"""Turn ResumeAI's data into suggestions for our profile form.

ResumeAI keeps dates and places as written ("Jan 2021", "Present", "Pune, India"), so they are
parsed here. Anything that can't be read is left empty for the person to fill in; nothing is
guessed. Lengths are cut to the form's limits so a suggestion never fails validation on size.
"""

import re
from datetime import UTC, date, datetime
from urllib.parse import urlsplit

import pycountry

from app.features.resumes.schemas import (
    EducationSuggestion,
    ExperienceSuggestion,
    ProfileSuggestion,
    ResumeAIData,
    ResumeAIEducation,
    ResumeAIExperience,
)
from app.shared.validation import normalize_tag

MIN_YEAR = 1950
MAX_SKILLS = 50
MAX_EXPERIENCES = 15
MAX_EDUCATIONS = 10

_MONTHS = {
    name: number
    for number, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for name in names
}
_STILL_THERE = {"present", "current", "now", "today", "ongoing", "till date", "to date"}
# Common short forms pycountry doesn't know.
_COUNTRY_ALIASES = {"usa": "US", "u.s.a.": "US", "u.s.": "US", "uk": "GB", "uae": "AE"}

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_MONTH_NAME_YEAR_RE = re.compile(r"^([a-z]+)\.?,?\s+(\d{4})$")
_NUMERIC_MONTH_RE = re.compile(r"^(\d{1,2})[/.-](\d{4})$|^(\d{4})[/.-](\d{1,2})$")


def _today() -> date:
    return datetime.now(UTC).date()


def _cut(value: str | None, max_length: int) -> str | None:
    text = " ".join(value.split()) if value else ""
    return text[:max_length].rstrip() or None


def _valid_year(year: int) -> bool:
    return MIN_YEAR <= year <= _today().year


def parse_month(value: str | None) -> str | None:
    """'Jan 2021', 'January 2021', '01/2021', '2021-01' -> '2021-01'; a bare '2021' -> '2021-01'.
    None for anything else, or a month in the future."""
    text = " ".join((value or "").lower().split())
    year = month = None
    if match := _MONTH_NAME_YEAR_RE.match(text):
        month, year = _MONTHS.get(match[1]), int(match[2])
    elif match := _NUMERIC_MONTH_RE.match(text):
        month = int(match[1] or match[4])
        year = int(match[2] or match[3])
    elif re.fullmatch(r"\d{4}", text):
        month, year = 1, int(text)
    if month is None or year is None or not 1 <= month <= 12 or not _valid_year(year):
        return None
    result = f"{year:04d}-{month:02d}"
    return None if result > _today().strftime("%Y-%m") else result


def parse_year(value: str | None) -> int | None:
    match = _YEAR_RE.search(value or "")
    return int(match[0]) if match and _valid_year(int(match[0])) else None


def is_still_there(value: str | None) -> bool:
    return " ".join((value or "").lower().split()) in _STILL_THERE


def _country_code(text: str) -> str | None:
    if alias := _COUNTRY_ALIASES.get(text.lower()):
        return alias
    try:
        return str(pycountry.countries.lookup(text).alpha_2)
    except LookupError:
        return None


def split_location(location: str | None) -> tuple[str | None, str | None]:
    """'Pune, Maharashtra, India' -> ('Pune', 'IN'); 'Pune' -> ('Pune', None);
    'India' -> (None, 'IN')."""
    parts = [part.strip() for part in (location or "").split(",") if part.strip()]
    if not parts:
        return None, None
    country = _country_code(parts[-1])
    if country is None:
        return _cut(parts[0], 100), None
    return (_cut(parts[0], 100) if len(parts) > 1 else None), country


def _with_scheme(link: str) -> str:
    return link if "://" in link else f"https://{link}"


def sort_links(links: list[str]) -> tuple[str | None, str | None, str | None]:
    """(linkedin, github, portfolio): the first link of each kind; the form checks the rules."""
    linkedin = github = portfolio = None
    for raw in links:
        link = _with_scheme(raw.strip())
        host = (urlsplit(link).hostname or "").lower()
        if host == "linkedin.com" or host.endswith(".linkedin.com"):
            linkedin = linkedin or (link if "/in/" in link else None)
        elif host in ("github.com", "www.github.com"):
            github = github or link
        elif link.startswith("https://") and "." in host:
            portfolio = portfolio or link
    return linkedin, github, portfolio


def _experience(entry: ResumeAIExperience, current_taken: bool) -> ExperienceSuggestion | None:
    company, title = _cut(entry.company, 120), _cut(entry.title, 120)
    if company is None or title is None:
        return None
    still_there = is_still_there(entry.end_date) and not current_taken
    return ExperienceSuggestion(
        company=company,
        title=title,
        start_month=parse_month(entry.start_date),
        is_current=still_there,
        end_month=None if still_there else parse_month(entry.end_date),
        description=(entry.description or "").strip()[:2000].rstrip() or None,
    )


def _education(entry: ResumeAIEducation) -> EducationSuggestion | None:
    institution = _cut(entry.institution, 200)
    if institution is None:
        return None
    start, end = parse_year(entry.start_date), parse_year(entry.end_date)
    return EducationSuggestion(
        institution=institution,
        degree=_cut(entry.degree, 120),
        field_of_study=_cut(entry.field_of_study, 120),
        start_year=start,
        end_year=end if start is None or end is None or end >= start else None,
    )


def years_of_experience(experiences: list[ExperienceSuggestion]) -> float | None:
    """From the first start to the last end (today for a current role), to the nearest half
    year. A rough starting value: gaps between jobs are counted."""
    starts = [e.start_month for e in experiences if e.start_month]
    if not starts:
        return None
    today = _today().strftime("%Y-%m")
    ends = [today if e.is_current else (e.end_month or e.start_month or today) for e in experiences]
    first, last = min(starts), max(ends)
    months = (int(last[:4]) - int(first[:4])) * 12 + int(last[5:]) - int(first[5:])
    return min(50.0, max(0.0, round(months / 6) / 2))


def to_profile(data: ResumeAIData) -> ProfileSuggestion:
    experiences: list[ExperienceSuggestion] = []
    for entry in data.experience:
        suggestion = _experience(entry, current_taken=any(e.is_current for e in experiences))
        if suggestion:
            experiences.append(suggestion)
    experiences = experiences[:MAX_EXPERIENCES]
    educations = [e for e in map(_education, data.education) if e][:MAX_EDUCATIONS]

    skills: list[str] = []
    for skill in data.skills:
        tag = normalize_tag(skill)[:50].rstrip()
        # Commas separate tags in filters, so a skill can't contain one.
        if tag and "," not in tag and tag not in skills:
            skills.append(tag)

    city, country_code = split_location(data.location)
    linkedin, github, portfolio = sort_links(data.links)
    return ProfileSuggestion(
        full_name=_cut(data.name, 120),
        email=_cut(data.email, 254),
        phone=_cut(data.phone, 30),
        city=city,
        country_code=country_code,
        linkedin_url=linkedin,
        github_url=github,
        portfolio_url=portfolio,
        # ResumeAI lists the latest role first.
        headline=experiences[0].title if experiences else None,
        years_experience=years_of_experience(experiences),
        skills=skills[:MAX_SKILLS],
        experiences=experiences,
        educations=educations,
    )
