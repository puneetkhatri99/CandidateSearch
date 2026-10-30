"""The one background runner: periodic tasks (embedding stale documents, pruning old rows)
on the API's event loop, or in `python -m app.cli maintenance`.

This module knows nothing about features: the task list is composed in `app/maintenance.py`
from each feature's public API. Every task is idempotent, so running it in several processes
at once is safe, just redundant.
"""

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_sessionmaker

logger = structlog.get_logger(__name__)

# A failing task (usually the database being down) is retried after this, whatever its interval:
# sooner than the hourly prune, and slow enough that a 2-second task logs once a minute.
FAILED_TASK_RETRY_SECONDS = 60.0
# Long enough for an in-flight embedding call (30 s SDK timeout) to finish and be recorded.
SHUTDOWN_GRACE_SECONDS = 45.0


@dataclass(frozen=True)
class MaintenanceTask:
    name: str
    interval_seconds: float
    # Takes a session that is not in a transaction; returns how many rows it affected.
    run: Callable[[AsyncSession], Awaitable[int]]


async def _run_task(task: MaintenanceTask) -> int:
    started = time.monotonic()
    async with get_sessionmaker()() as session:
        affected = await task.run(session)
    if affected:  # Quiet when idle: the embedding task runs every few seconds.
        logger.info(
            "maintenance_task_completed",
            task=task.name,
            affected=affected,
            duration_ms=round((time.monotonic() - started) * 1000),
        )
    return affected


async def run_maintenance(
    tasks: Sequence[MaintenanceTask], *, stop: asyncio.Event | None = None, once: bool = False
) -> None:
    """Run each task when due (all are due at start) until `stop` is set.

    A failing task is logged and retried after 60 s; it never stops the others.
    With `once`, every task runs once and the first error is raised afterwards.
    """
    stop = stop or asyncio.Event()
    next_run = {task.name: 0.0 for task in tasks}
    first_error: Exception | None = None
    while not stop.is_set():
        for task in tasks:
            if stop.is_set() or time.monotonic() < next_run[task.name]:
                continue
            try:
                await _run_task(task)
            except Exception as exc:
                # The type only: driver messages can echo row values.
                logger.error(
                    "maintenance_task_failed", task=task.name, error_type=type(exc).__name__
                )
                first_error = first_error or exc
                next_run[task.name] = time.monotonic() + FAILED_TASK_RETRY_SECONDS
            else:
                next_run[task.name] = time.monotonic() + task.interval_seconds
        if once:
            if first_error is not None:
                raise first_error
            return
        if not next_run:
            return
        wait = max(min(next_run.values()) - time.monotonic(), 0.0)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=wait)


@dataclass
class _Handle:
    task: asyncio.Task[None]
    stop: asyncio.Event


_handle: _Handle | None = None


def _log_if_crashed(task: asyncio.Task[None]) -> None:
    if not task.cancelled() and (error := task.exception()) is not None:
        logger.error("maintenance_crashed", error_type=type(error).__name__)


def start_background_maintenance(tasks: Sequence[MaintenanceTask]) -> bool:
    """Run the tasks on the API's event loop. Returns whether they are running."""
    global _handle
    if _handle is not None:
        return True
    if not get_settings().maintenance_in_api:
        logger.info("maintenance_disabled", reason="setting")
        return False
    stop = asyncio.Event()
    task = asyncio.create_task(run_maintenance(tasks, stop=stop), name="maintenance")
    task.add_done_callback(_log_if_crashed)
    _handle = _Handle(task, stop)
    return True


async def stop_background_maintenance(grace_seconds: float = SHUTDOWN_GRACE_SECONDS) -> None:
    """Ask the runner to stop, wait briefly for the current task, then cancel it."""
    global _handle
    handle, _handle = _handle, None
    if handle is None:
        return
    handle.stop.set()
    done, _ = await asyncio.wait({handle.task}, timeout=grace_seconds)
    if not done:
        handle.task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await handle.task
