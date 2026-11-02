"""Resumes: read an uploaded resume into profile suggestions, and show the formatted resume.
Both go through ResumeAI; we keep only the reference it stores the data under."""

import re

from app.features.resumes.client import (
    ResumeAIClient,
    close_resumeai_client,
    use_resumeai_client,
)
from app.features.resumes.router import router

# The two routes that take a file, for the larger body limit in main.py.
UPLOAD_PATHS = re.compile(r"/api/v1/(resumes|admin/candidates/[^/]+/resume)")

__all__ = [
    "UPLOAD_PATHS",
    "ResumeAIClient",
    "close_resumeai_client",
    "router",
    "use_resumeai_client",
]
