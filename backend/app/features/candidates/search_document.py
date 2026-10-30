"""Builds the plain-text profile that Phase 2 embeds and Phase 4 keyword-searches.

The document must never contain direct identifiers (name, email, phone, URLs): it is sent
to embedding providers and drives ranking, which must not depend on who the person is.
Every user-typed field goes through `redact_identifiers`, not just the free-text ones.

Name redaction is deliberately aggressive: a name that is also an ordinary word ("Will",
"Rose") is removed wherever it appears. Losing a word costs far less than leaking identity.
"""

from decimal import Decimal

from app.features.candidates.schemas import CandidateProfile, EducationIn, ExperienceIn
from app.shared import redaction


def redact_identifiers(text: str, full_name: str) -> str:
    return redaction.redact_identifiers(text, [full_name])


def _format_years(value: Decimal) -> str:
    return f"{value.normalize():f}"


def _redact_all(values: list[str], full_name: str) -> list[str]:
    redacted = (redact_identifiers(v, full_name) for v in values)
    return [v for v in redacted if v]


def _format_experience(exp: ExperienceIn, full_name: str) -> str:
    end = "present" if exp.is_current or exp.end_month is None else exp.end_month.strftime("%Y-%m")
    title = redact_identifiers(exp.title, full_name)
    company = redact_identifiers(exp.company, full_name)
    line = f"{title} at {company} ({exp.start_month.strftime('%Y-%m')} to {end})"
    if exp.description:
        line += f": {redact_identifiers(exp.description, full_name)}"
    return line + "."


def _format_education(edu: EducationIn, full_name: str) -> str:
    degree_parts = _redact_all([p for p in (edu.degree, edu.field_of_study) if p], full_name)
    institution = redact_identifiers(edu.institution, full_name)
    line = f"{' '.join(degree_parts)}, {institution}" if degree_parts else institution
    if edu.start_year or edu.end_year:
        line += f" ({edu.start_year or '?'} to {edu.end_year or '?'})"
    return line + "."


def build_search_document(candidate: CandidateProfile) -> str:
    name = candidate.full_name
    lines = [
        f"{redact_identifiers(candidate.headline, name)}.",
        f"{_format_years(candidate.years_experience)} years experience.",
    ]
    # Skills can all redact away when they collide with the name; skip the empty line then.
    skills = _redact_all(candidate.skills, name)
    if skills:
        lines.append(f"Skills: {', '.join(skills)}.")
    lines.append(f"Summary: {redact_identifiers(candidate.summary, name)}")
    if candidate.experiences:
        lines.append(
            "Experience: " + " ".join(_format_experience(e, name) for e in candidate.experiences)
        )
    if candidate.educations:
        lines.append(
            "Education: " + " ".join(_format_education(e, name) for e in candidate.educations)
        )
    desired_roles = _redact_all(candidate.desired_roles, name)
    if desired_roles:
        lines.append(f"Desired roles: {', '.join(desired_roles)}.")
    lines.append(f"Work mode: {', '.join(candidate.work_modes)}.")
    return "\n".join(lines)
