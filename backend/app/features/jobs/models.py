import uuid
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import TimestampedModel


class Job(TimestampedModel):
    __tablename__ = "jobs"

    title: Mapped[str] = mapped_column(String(120))
    department: Mapped[str | None] = mapped_column(String(120))
    city: Mapped[str | None] = mapped_column(String(100))
    country_code: Mapped[str | None] = mapped_column(String(2))
    work_mode: Mapped[str] = mapped_column(String(10))
    employment_type: Mapped[str] = mapped_column(String(20))
    min_years: Mapped[Decimal] = mapped_column(Numeric(3, 1))
    max_years: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    must_have_skills: Mapped[list[str]] = mapped_column(ARRAY(Text))
    nice_to_have_skills: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10))
    # Yearly pay range in whole units of salary_currency.
    salary_min: Mapped[int | None] = mapped_column(Integer)
    salary_max: Mapped[int | None] = mapped_column(Integer)
    salary_currency: Mapped[str | None] = mapped_column(String(3))
    # Redacted text that is embedded and searched; rebuilt on every save.
    search_document: Mapped[str] = mapped_column(Text)
    # Optimistic locking: SQLAlchemy adds "WHERE version = :loaded" to every UPDATE.
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    # RESTRICT: users are only ever deactivated, never deleted, so a job always has an owner.
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))

    # SQLAlchemy reads this declaratively; it is never mutated.
    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}  # noqa: RUF012

    __table_args__ = (
        Index("ix_jobs_status", "status"),
        Index("ix_jobs_created_by", "created_by"),
        Index("ix_jobs_created_at_id", "created_at", "id"),
        CheckConstraint("work_mode IN ('remote', 'hybrid', 'onsite')", name="work_mode_valid"),
        CheckConstraint(
            "employment_type IN ('full_time', 'part_time', 'contract', 'internship')",
            name="employment_type_valid",
        ),
        CheckConstraint("status IN ('draft', 'open', 'closed')", name="status_valid"),
        CheckConstraint("min_years >= 0 AND min_years <= 50", name="min_years_range"),
        CheckConstraint(
            "max_years IS NULL OR (max_years >= min_years AND max_years <= 50)",
            name="max_years_range",
        ),
        CheckConstraint(
            "cardinality(must_have_skills) BETWEEN 1 AND 20", name="must_have_skills_count"
        ),
        CheckConstraint("cardinality(nice_to_have_skills) <= 20", name="nice_to_have_skills_count"),
        CheckConstraint(
            "work_mode = 'remote' OR (city IS NOT NULL AND country_code IS NOT NULL)",
            name="location_required",
        ),
        CheckConstraint(
            "(salary_currency IS NULL) = (salary_min IS NULL AND salary_max IS NULL)"
            " AND (salary_min IS NULL OR salary_min BETWEEN 1 AND 1000000000)"
            " AND (salary_max IS NULL OR salary_max BETWEEN 1 AND 1000000000)"
            " AND (salary_min IS NULL OR salary_max IS NULL OR salary_max >= salary_min)",
            name="salary_valid",
        ),
    )
