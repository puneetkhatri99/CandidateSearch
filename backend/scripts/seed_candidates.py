"""Load synthetic candidates for local development and search testing.

    python -m scripts.seed_candidates --count 1000

All data is fake (Faker + templates), uses example.com emails, and is tagged
source="synthetic". Re-running is safe: existing seed candidates are skipped.
Refuses to run in production.
"""

import argparse
import asyncio
import random
import sys
import time
from datetime import UTC, date, datetime
from typing import Any

import structlog
from faker import Faker

from app.core.config import get_settings
from app.core.db import get_engine, get_sessionmaker
from app.core.logging import configure_logging
from app.features.candidates import CandidateAlreadyExistsError, CandidateCreate, create_candidate

logger = structlog.get_logger("seed_candidates")

SOURCE = "synthetic"

# fmt: off
ROLES: dict[str, list[str]] = {
    "Backend Engineer": [
        "python", "fastapi", "django", "postgresql", "kafka", "docker", "aws", "go",
        "java", "spring boot", "kafka", "rest apis", "microservices", "grpc",
    ],
    "Frontend Engineer": [
        "react", "typescript", "javascript", "next.js", "css", "tailwind", "redux",
        "vite", "html", "web performance", "accessibility", "graphql",
    ],
    "Full Stack Engineer": [
        "react", "typescript", "node.js", "express", "python", "postgresql", "mongodb",
        "docker", "aws", "graphql", "rest apis",
    ],
    "Data Engineer": [
        "python", "sql", "spark", "airflow", "dbt", "kafka", "snowflake", "bigquery",
        "aws", "etl", "data modeling", "databricks",
    ],
    "Machine Learning Engineer": [
        "python", "pytorch", "tensorflow", "scikit-learn", "mlops", "llms", "nlp",
        "computer vision", "docker", "kubernetes", "hugging face", "vector databases",
    ],
    "Data Scientist": [
        "python", "pandas", "statistics", "sql", "machine learning", "a/b testing",
        "tableau", "r", "experimentation", "forecasting",
    ],
    "DevOps Engineer": [
        "kubernetes", "terraform", "aws", "gcp", "docker", "ci/cd", "linux",
        "prometheus", "ansible", "helm", "github actions", "observability",
    ],
    "Mobile Developer": [
        "kotlin", "swift", "android", "ios", "react native", "flutter", "firebase",
        "mobile ui", "app store deployment",
    ],
    "QA Engineer": [
        "selenium", "playwright", "cypress", "test automation", "python", "java",
        "api testing", "jmeter", "manual testing", "ci/cd",
    ],
    "Product Designer": [
        "figma", "ux research", "prototyping", "design systems", "user testing",
        "wireframing", "interaction design", "accessibility",
    ],
}

LOCATIONS = [
    ("Bengaluru", "IN"), ("Hyderabad", "IN"), ("Pune", "IN"), ("Mumbai", "IN"),
    ("New Delhi", "IN"), ("Chennai", "IN"), ("Berlin", "DE"), ("London", "GB"),
    ("Toronto", "CA"), ("Austin", "US"), ("New York", "US"), ("San Francisco", "US"),
    ("Singapore", "SG"), ("Amsterdam", "NL"), ("Dubai", "AE"), ("Sydney", "AU"),
]

DEGREES = [
    ("B.Tech", "Computer Science"), ("B.E.", "Information Technology"),
    ("M.Tech", "Computer Science"), ("B.Sc", "Mathematics"), ("M.Sc", "Data Science"),
    ("BCA", "Computer Applications"), ("MCA", "Computer Applications"),
    ("B.Des", "Interaction Design"), ("B.Tech", "Electronics"),
]

FOCUS = [
    "building reliable, well-tested systems",
    "shipping customer-facing features quickly",
    "scaling products from prototype to millions of users",
    "improving performance and reducing infrastructure cost",
    "mentoring engineers and improving team practices",
    "working closely with product and design",
]

DOMAINS = ["fintech", "e-commerce", "healthcare", "edtech", "logistics", "SaaS", "gaming", "media"]
# fmt: on


def _seniority(years: float) -> str:
    if years < 2:
        return "Junior "
    if years < 5:
        return ""
    if years < 10:
        return "Senior "
    return "Lead "


def _months_ago(today: date, months: int) -> date:
    index = today.year * 12 + today.month - 1 - months
    return date(index // 12, index % 12 + 1, 1)


def _experiences(fake: Faker, rng: random.Random, role: str, years: float) -> list[dict[str, Any]]:
    total_months = max(int(years * 12), 3)
    count = min(rng.randint(1, 4), max(1, total_months // 12))
    today = datetime.now(UTC).date()
    entries: list[dict[str, Any]] = []
    end_offset = 0
    for i in range(count):
        length = max(3, total_months // count)
        start = _months_ago(today, end_offset + length)
        is_current = i == 0
        entries.append(
            {
                "company": fake.company()[:120],
                "title": f"{_seniority(years) if i == 0 else ''}{role}",
                "start_month": start.strftime("%Y-%m"),
                "is_current": is_current,
                "end_month": None
                if is_current
                else _months_ago(today, end_offset).strftime("%Y-%m"),
                "description": (f"Worked on {rng.choice(DOMAINS)} products, {rng.choice(FOCUS)}."),
            }
        )
        end_offset += length + rng.randint(0, 2)
    return entries


def build_payload(i: int, fake: Faker, rng: random.Random) -> dict[str, Any]:
    role, pool = rng.choice(list(ROLES.items()))
    years = round(rng.uniform(0, 15) * 2) / 2
    skills = rng.sample(pool, k=rng.randint(4, min(10, len(pool))))
    city, country = rng.choice(LOCATIONS)
    degree, field = rng.choice(DEGREES)
    grad_year = max(1990, datetime.now(UTC).year - int(years) - rng.randint(0, 2))
    domain = rng.choice(DOMAINS)

    return {
        "full_name": fake.name(),
        "email": f"seed.{i:05d}@example.com",
        "city": city,
        "country_code": country,
        "headline": f"{_seniority(years)}{role}",
        "years_experience": years,
        "skills": skills,
        "summary": (
            f"{role} with {years:g} years of experience in {domain}. "
            f"Strong in {', '.join(skills[:3])}. Focused on {rng.choice(FOCUS)} "
            f"and {rng.choice(FOCUS)}."
        ),
        "experiences": _experiences(fake, rng, role, years),
        "educations": [
            {
                "institution": f"{fake.city()} University",
                "degree": degree,
                "field_of_study": field,
                "start_year": grad_year - 4,
                "end_year": grad_year,
            }
        ],
        "desired_roles": [role],
        "work_modes": rng.sample(["remote", "hybrid", "onsite"], k=rng.randint(1, 3)),
        "open_to_relocation": rng.random() < 0.4,
        "notice_period_days": rng.choice([0, 15, 30, 60, 90]),
        "consent": True,
    }


async def seed(count: int, random_seed: int) -> None:
    fake = Faker()
    Faker.seed(random_seed)
    rng = random.Random(random_seed)  # noqa: S311 - synthetic data, not security-sensitive
    created = skipped = 0
    started = time.perf_counter()

    async with get_sessionmaker()() as session:
        for i in range(count):
            data = CandidateCreate.model_validate(build_payload(i, fake, rng))
            try:
                await create_candidate(
                    session,
                    data,
                    consent_version="synthetic",
                    source=SOURCE,
                    source_ref=f"seed-{i:05d}",
                )
                created += 1
            except CandidateAlreadyExistsError:
                skipped += 1
    await get_engine().dispose()

    logger.info(
        "seed_completed",
        created=created,
        skipped_existing=skipped,
        seconds=round(time.perf_counter() - started, 1),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42, help="random seed for reproducible data")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings)
    if settings.environment == "production":
        logger.error("seed_refused", reason="never seed synthetic data into production")
        sys.exit(1)

    asyncio.run(seed(args.count, args.seed))


if __name__ == "__main__":
    main()
