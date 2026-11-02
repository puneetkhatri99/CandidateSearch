from uuid import UUID

from pydantic import BaseModel, ConfigDict

# --- ResumeAI's answer (POST /api/public/resumes), read leniently: extra fields are ignored ---


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ResumeAIExperience(_Lenient):
    company: str | None = None
    title: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    description: str | None = None


class ResumeAIEducation(_Lenient):
    institution: str | None = None
    degree: str | None = None
    field_of_study: str | None = None
    start_date: str | None = None
    end_date: str | None = None


class ResumeAIData(_Lenient):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    links: list[str] = []
    skills: list[str] = []
    experience: list[ResumeAIExperience] = []
    education: list[ResumeAIEducation] = []


class ResumeAIExtractResponse(_Lenient):
    data: ResumeAIData


# --- What we return: suggestions for the profile form, every field may be missing -----------


class ExperienceSuggestion(BaseModel):
    company: str
    title: str
    start_month: str | None  # "YYYY-MM", as the form edits it
    is_current: bool
    end_month: str | None
    description: str | None


class EducationSuggestion(BaseModel):
    institution: str
    degree: str | None
    field_of_study: str | None
    start_year: int | None
    end_year: int | None


class ProfileSuggestion(BaseModel):
    """Read from a resume by AI, so the person checks it in the form before saving."""

    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    city: str | None = None
    country_code: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None
    headline: str | None = None
    years_experience: float | None = None
    skills: list[str] = []
    experiences: list[ExperienceSuggestion] = []
    educations: list[EducationSuggestion] = []


class ResumeRead(BaseModel):
    """`resume_ref` goes back with the new profile, so its resume is linked once it is saved."""

    resume_ref: UUID
    profile: ProfileSuggestion
