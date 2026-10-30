from typing import Any


def valid_candidate_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "full_name": "Asha Verma",
        "email": "asha.verma@example.com",
        "phone": "+91 98765 43210",
        "city": "Bengaluru",
        "country_code": "IN",
        "linkedin_url": "https://www.linkedin.com/in/asha-verma",
        "github_url": "https://github.com/ashaverma",
        "portfolio_url": "",
        "headline": "Senior Backend Engineer",
        "years_experience": 6.5,
        "skills": ["Python", "FastAPI", " python ", "PostgreSQL"],
        "summary": (
            "Backend engineer building APIs and data pipelines for fintech products at scale."
        ),
        "experiences": [
            {
                "company": "Acme Payments",
                "title": "Senior Backend Engineer",
                "start_month": "2021-03",
                "is_current": True,
                "end_month": "",
                "description": "Led the payments API rewrite.",
            },
            {
                "company": "Globex",
                "title": "Backend Engineer",
                "start_month": "2018-06",
                "is_current": False,
                "end_month": "2021-02",
            },
        ],
        "educations": [
            {
                "institution": "IIT Delhi",
                "degree": "B.Tech",
                "field_of_study": "Computer Science",
                "start_year": 2014,
                "end_year": 2018,
            }
        ],
        "desired_roles": ["Backend Engineer", "Platform Engineer"],
        "work_modes": ["remote", "hybrid"],
        "open_to_relocation": True,
        "notice_period_days": 30,
        "consent": True,
    }
    payload.update(overrides)
    return payload
