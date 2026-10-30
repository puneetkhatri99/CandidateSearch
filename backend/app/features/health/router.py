from fastapi import APIRouter, Response, status

from app.core.db import SessionDep
from app.features.health import service
from app.features.health.schemas import HealthStatus

router = APIRouter(tags=["health"])


@router.get("/health")
async def liveness() -> HealthStatus:
    """The process is up. Does not touch dependencies."""
    return HealthStatus(status="ok")


@router.get("/ready")
async def readiness(response: Response, session: SessionDep) -> HealthStatus:
    """The service can handle traffic: all dependencies are reachable."""
    result = await service.check_readiness(session)
    if result.status != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result
