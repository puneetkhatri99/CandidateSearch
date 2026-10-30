"""Job roles: recruiter-created requirements that Phase 4 matches candidates against."""

from app.features.jobs.router import router
from app.features.jobs.service import JobBrief, get_job_brief

__all__ = ["JobBrief", "get_job_brief", "router"]
