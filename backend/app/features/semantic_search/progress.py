"""Stage-by-stage progress of a search, for the streaming endpoints. Without a listener (the
plain JSON endpoints) every call is a no-op."""

import time
from collections.abc import Awaitable, Callable

from app.features.semantic_search.schemas import Stage, StageEvent

Listener = Callable[[StageEvent], Awaitable[None]]


class Progress:
    def __init__(self, listener: Listener | None = None) -> None:
        self._listener = listener
        self._started: dict[Stage, float] = {}

    async def start(self, stage: Stage, detail: str) -> None:
        self._started[stage] = time.perf_counter()
        if self._listener is not None:
            await self._listener(StageEvent(stage=stage, state="started", detail=detail))

    async def done(self, stage: Stage, detail: str) -> None:
        began = self._started.get(stage, time.perf_counter())
        elapsed_ms = round((time.perf_counter() - began) * 1000)
        if self._listener is not None:
            await self._listener(
                StageEvent(stage=stage, state="done", detail=detail, elapsed_ms=elapsed_ms)
            )
