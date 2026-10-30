import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import TimestampedModel

# Referenced by the service to translate a unique violation into a 409.
EMAIL_UNIQUE_CONSTRAINT = "uq_candidates_email"
SEARCH_TSV_EXPRESSION = "to_tsvector('english'::regconfig, search_document || ' ' || city)"


class Candidate(TimestampedModel):
    __tablename__ = "candidates"

    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    phone: Mapped[str | None] = mapped_column(String(20))
    city: Mapped[str] = mapped_column(String(100))
    country_code: Mapped[str] = mapped_column(String(2))

    linkedin_url: Mapped[str | None] = mapped_column(String(300))
    github_url: Mapped[str | None] = mapped_column(String(300))
    portfolio_url: Mapped[str | None] = mapped_column(String(300))

    headline: Mapped[str] = mapped_column(String(120))
    years_experience: Mapped[Decimal] = mapped_column(Numeric(3, 1))
    summary: Mapped[str] = mapped_column(Text)
    skills: Mapped[list[str]] = mapped_column(ARRAY(Text))
    desired_roles: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    work_modes: Mapped[list[str]] = mapped_column(ARRAY(Text))
    open_to_relocation: Mapped[bool | None] = mapped_column(Boolean)
    notice_period_days: Mapped[int | None] = mapped_column(SmallInteger)
    # Yearly, whole units of salary_currency; both set or both null.
    expected_salary: Mapped[int | None] = mapped_column(Integer)
    salary_currency: Mapped[str | None] = mapped_column(String(3))

    source: Mapped[str] = mapped_column(String(30), server_default=text("'manual'"))
    source_ref: Mapped[str | None] = mapped_column(String(200))
    search_document: Mapped[str] = mapped_column(Text)
    # Full-text index of the profile plus city (search_document leaves location out), maintained
    # by Postgres; deferred so no load reads it.
    search_tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(SEARCH_TSV_EXPRESSION, persisted=True),
        deferred=True,
    )

    consent_given_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consent_version: Mapped[str] = mapped_column(String(20))
    # Set when staff (not the candidate) captured the consent.
    consent_recorded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    # Optimistic locking: SQLAlchemy adds "WHERE version = :loaded" to every UPDATE.
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))

    # lazy="raise" forbids implicit lazy loads, which fail under asyncio anyway.
    experiences: Mapped[list["CandidateExperience"]] = relationship(
        back_populates="candidate",
        cascade="all, delete-orphan",
        order_by="CandidateExperience.position",
        lazy="raise",
    )
    educations: Mapped[list["CandidateEducation"]] = relationship(
        back_populates="candidate",
        cascade="all, delete-orphan",
        order_by="CandidateEducation.position",
        lazy="raise",
    )

    # SQLAlchemy reads this declaratively; it is never mutated.
    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}  # noqa: RUF012

    __table_args__ = (
        Index("ix_candidates_skills", "skills", postgresql_using="gin"),
        Index("ix_candidates_location", "country_code", "city"),
        Index("ix_candidates_search_tsv", "search_tsv", postgresql_using="gin"),
        Index("ix_candidates_created_at", "created_at"),
        Index(
            "uq_candidates_source_ref",
            "source",
            "source_ref",
            unique=True,
            postgresql_where=text("source_ref IS NOT NULL"),
        ),
        CheckConstraint("years_experience BETWEEN 0 AND 50", name="years_experience_range"),
        CheckConstraint(
            "notice_period_days IS NULL OR notice_period_days BETWEEN 0 AND 180",
            name="notice_period_range",
        ),
        CheckConstraint(
            "(expected_salary IS NULL) = (salary_currency IS NULL)"
            " AND (expected_salary IS NULL OR expected_salary BETWEEN 1 AND 1000000000)",
            name="expected_salary_valid",
        ),
        CheckConstraint("cardinality(skills) >= 1", name="skills_not_empty"),
        CheckConstraint(
            "cardinality(work_modes) >= 1 AND work_modes <@ ARRAY['remote','hybrid','onsite']",
            name="work_modes_valid",
        ),
    )


class CandidateExperience(TimestampedModel):
    __tablename__ = "candidate_experiences"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )
    company: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(120))
    start_month: Mapped[date] = mapped_column(Date)
    end_month: Mapped[date | None] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean)
    description: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(SmallInteger)

    candidate: Mapped[Candidate] = relationship(back_populates="experiences", lazy="raise")

    __table_args__ = (
        CheckConstraint("end_month IS NULL OR end_month >= start_month", name="dates_ordered"),
    )


class CandidateEducation(TimestampedModel):
    __tablename__ = "candidate_educations"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )
    institution: Mapped[str] = mapped_column(String(200))
    degree: Mapped[str | None] = mapped_column(String(120))
    field_of_study: Mapped[str | None] = mapped_column(String(120))
    start_year: Mapped[int | None] = mapped_column(SmallInteger)
    end_year: Mapped[int | None] = mapped_column(SmallInteger)
    position: Mapped[int] = mapped_column(SmallInteger)

    candidate: Mapped[Candidate] = relationship(back_populates="educations", lazy="raise")

    __table_args__ = (
        CheckConstraint(
            "end_year IS NULL OR start_year IS NULL OR end_year >= start_year",
            name="years_ordered",
        ),
    )
