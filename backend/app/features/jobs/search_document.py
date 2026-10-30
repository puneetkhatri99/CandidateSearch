"""Builds the plain-text job description that is embedded and that Phase 4 searches with.

Jobs hold no candidate data, but recruiters can type contact details and names, so every
free-text value goes through the shared redaction. Status is deliberately left out: closing or
reopening a job must not change the document, or it would trigger an embedding call.
"""

from collections.abc import Sequence
from decimal import Decimal

import pycountry

from app.features.jobs.schemas import JobFields
from app.shared.redaction import redact_identifiers


def _format_years(value: Decimal) -> str:
    return f"{value.normalize():f}"


def _country_name(country_code: str) -> str:
    country = pycountry.countries.get(alpha_2=country_code)
    return country.name if country else country_code


def build_job_search_document(job: JobFields, redact_names: Sequence[str]) -> str:
    def clean(value: str) -> str:
        return redact_identifiers(value, redact_names)

    def clean_all(values: Sequence[str]) -> list[str]:
        return [cleaned for cleaned in (clean(v) for v in values) if cleaned]

    lines: list[str] = []
    if title := clean(job.title):
        lines.append(f"{title}.")
    if job.department and (department := clean(job.department)):
        lines.append(f"Department: {department}.")
    employment = job.employment_type.replace("_", "-")
    lines.append(f"Employment type: {employment}. Work mode: {job.work_mode}.")

    place = [clean(job.city)] if job.city else []
    if job.country_code:
        place.append(_country_name(job.country_code))
    if place := [part for part in place if part]:
        lines.append(f"Location: {', '.join(place)}.")

    minimum = _format_years(job.min_years)
    if job.max_years is None:
        lines.append(f"Experience: {minimum}+ years.")
    else:
        lines.append(f"Experience: {minimum}-{_format_years(job.max_years)} years.")

    if must_have := clean_all(job.must_have_skills):
        lines.append(f"Must-have skills: {', '.join(must_have)}.")
    if nice_to_have := clean_all(job.nice_to_have_skills):
        lines.append(f"Nice-to-have skills: {', '.join(nice_to_have)}.")
    if description := clean(job.description):
        lines.append(f"Description: {description}")
    return "\n".join(lines)
