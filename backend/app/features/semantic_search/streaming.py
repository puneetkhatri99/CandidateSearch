"""Server-sent events for a search: one `stage` event per step, then `result` or `error`.

The search runs in its own task with its own session. If the browser disconnects, the task
is left to finish rather than cancelled: cancelling a metered AI call mid-flight would leave
the spend unrecorded (see ai_usage.metered_call).
"""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable

import structlog
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.core.errors import AppError
from app.features.semantic_search.progress import Progress
from app.features.semantic_search.schemas import SemanticSearchResult, StageEvent

logger = structlog.get_logger(__name__)

type Search = Callable[[AsyncSession, Progress], Awaitable[SemanticSearchResult]]

# Strong references, so a search outliving its disconnected stream isn't garbage-collected.
_running: set[asyncio.Task[None]] = set()


def _event(name: str, data: str) -> str:
    return f"event: {name}\ndata: {data}\n\n"


async def _events(search: Search) -> AsyncIterator[str]:
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def on_stage(event: StageEvent) -> None:
        await queue.put(_event("stage", event.model_dump_json()))

    async def run() -> None:
        try:
            async with get_sessionmaker()() as session:
                result = await search(session, Progress(on_stage))
            await queue.put(_event("result", result.model_dump_json()))
        except AppError as exc:
            error = {"status": exc.status_code, "code": exc.code, "message": exc.message}
            await queue.put(_event("error", json.dumps(error)))
        except Exception as exc:
            # The response has started, so the 500 handler can't answer; report it in-stream.
            # Class name only: driver messages can echo values.
            logger.error("semantic_search_stream_failed", error_type=type(exc).__name__)
            error = {
                "status": 500,
                "code": "internal_error",
                "message": "An unexpected error occurred.",
            }
            await queue.put(_event("error", json.dumps(error)))
        finally:
            await queue.put(None)

    task = asyncio.create_task(run())
    _running.add(task)
    task.add_done_callback(_running.discard)
    while (item := await queue.get()) is not None:
        yield item


def stream_search(search: Search) -> StreamingResponse:
    return StreamingResponse(
        _events(search),
        media_type="text/event-stream",
        # No caching, and no buffering by a reverse proxy, or the steps arrive all at once.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
