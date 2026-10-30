import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import maintenance
from app.core.maintenance import MaintenanceTask, run_maintenance


class _FailedError(Exception):
    pass


def _task(
    name: str, calls: list[str], *, fails: bool = False, interval: float = 3600
) -> MaintenanceTask:
    async def run(_: AsyncSession) -> int:
        calls.append(name)
        if fails:
            raise _FailedError(name)
        return 1

    return MaintenanceTask(name=name, interval_seconds=interval, run=run)


@pytest.fixture(autouse=True)
def no_database(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run_without_session(task: MaintenanceTask) -> int:
        return await task.run(None)  # type: ignore[arg-type]  # the fake tasks ignore it

    monkeypatch.setattr(maintenance, "_run_task", run_without_session)


async def test_once_runs_every_task_then_raises_the_first_error() -> None:
    calls: list[str] = []
    tasks = [_task("broken", calls, fails=True), _task("healthy", calls)]

    with pytest.raises(_FailedError, match="broken"):
        await run_maintenance(tasks, once=True)

    # The failing task did not stop the one after it.
    assert calls == ["broken", "healthy"]


async def test_once_without_errors_returns() -> None:
    calls: list[str] = []
    await run_maintenance([_task("a", calls), _task("b", calls)], once=True)
    assert calls == ["a", "b"]


async def test_tasks_repeat_on_their_interval_and_a_failure_is_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(maintenance, "FAILED_TASK_RETRY_SECONDS", 0.02)
    calls: list[str] = []
    stop = asyncio.Event()
    tasks = [_task("fast", calls, interval=0.02), _task("broken", calls, fails=True)]

    runner = asyncio.create_task(run_maintenance(tasks, stop=stop))
    await asyncio.sleep(0.2)
    stop.set()
    await asyncio.wait_for(runner, timeout=1)

    # Both ran again (the failure after min(interval, retry)), and the loop did not spin.
    assert 2 <= calls.count("fast") <= 20
    assert 2 <= calls.count("broken") <= 20


async def test_setting_stop_ends_a_waiting_loop_promptly() -> None:
    calls: list[str] = []
    stop = asyncio.Event()
    runner = asyncio.create_task(run_maintenance([_task("hourly", calls)], stop=stop))
    await asyncio.sleep(0.05)

    stop.set()
    await asyncio.wait_for(runner, timeout=1)

    assert calls == ["hourly"]


async def test_an_empty_task_list_returns() -> None:
    await asyncio.wait_for(run_maintenance([]), timeout=1)
