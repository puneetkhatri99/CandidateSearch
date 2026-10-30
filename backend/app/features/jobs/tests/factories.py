from typing import Any


def valid_job_payload(**overrides: Any) -> dict[str, Any]:
    """A job body that passes every rule; override fields to probe one at a time."""
    payload: dict[str, Any] = {
        "title": "Senior Backend Engineer",
        "department": "Platform",
        "work_mode": "hybrid",
        "employment_type": "full_time",
        "city": "Berlin",
        "country_code": "DE",
        "min_years": 3,
        "max_years": 6,
        "must_have_skills": ["Python", "PostgreSQL"],
        "nice_to_have_skills": ["Kubernetes"],
        "description": (
            "You will design and run backend services that match candidates to open roles, "
            "own their reliability and work closely with the product team."
        ),
        "status": "draft",
    }
    payload.update(overrides)
    return payload
