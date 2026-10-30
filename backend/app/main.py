"""App factory: wires infrastructure and registers feature routers. No business logic here."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.body_limit import BodySizeLimitMiddleware
from app.core.config import get_settings
from app.core.db import get_engine
from app.core.embeddings import close_embedding_provider
from app.core.errors import UnhandledErrorMiddleware, register_exception_handlers
from app.core.logging import configure_logging
from app.core.maintenance import start_background_maintenance, stop_background_maintenance
from app.core.middleware import RequestContextMiddleware
from app.features import ai_usage, auth, candidates, health, jobs, semantic_search
from app.maintenance import maintenance_tasks


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    start_background_maintenance(maintenance_tasks())
    yield
    # Before the engine goes: the runner finishes its in-flight task using the database.
    await stop_background_maintenance()
    await close_embedding_provider()
    await get_engine().dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
        # Interactive docs are a local/staging convenience only.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    # Middleware added first is innermost. UnhandledErrorMiddleware is first so a 500 is built
    # inside CORS and request-context (headers, log line); the body limit is next so 413
    # responses also carry CORS headers.
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_body_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)

    # Probes live at the root so load balancers don't depend on API versioning.
    app.include_router(health.router)

    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(auth.router)
    api_v1.include_router(auth.admin_router)
    api_v1.include_router(ai_usage.router)
    api_v1.include_router(jobs.router)
    api_v1.include_router(candidates.router)
    api_v1.include_router(candidates.admin_router)
    api_v1.include_router(semantic_search.router)
    app.include_router(api_v1)

    return app


app = create_app()
