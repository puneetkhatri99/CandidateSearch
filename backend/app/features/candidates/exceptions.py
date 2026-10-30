from app.core.errors import ConflictError


class CandidateAlreadyExistsError(ConflictError):
    code = "candidate_exists"


class VersionConflictError(ConflictError):
    code = "version_conflict"
