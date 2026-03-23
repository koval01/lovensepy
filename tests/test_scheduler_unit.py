from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from lovensepy._constants import Actions
from lovensepy._models import CommandResponse, GetToysResponse
from lovensepy.services.fastapi.scheduler import ControlScheduler


def _mock_backend() -> MagicMock:
    backend = MagicMock()
    backend.get_toys = AsyncMock(
        return_value=GetToysResponse.model_validate(
            {"data": {"toys": [{"id": "toy-a", "name": "Toy A"}]}}
        )
    )
    backend.function_request = AsyncMock(return_value=CommandResponse(code=200, type="OK"))
    backend.preset_request = AsyncMock(return_value=CommandResponse(code=200, type="OK"))
    backend.pattern_request = AsyncMock(return_value=CommandResponse(code=200, type="OK"))
    backend.stop = AsyncMock(return_value=CommandResponse(code=200, type="OK"))
    return backend


def test_scheduler_concurrent_schedule_same_toy() -> None:
    async def _run() -> None:
        scheduler = ControlScheduler(_mock_backend())
        try:
            await asyncio.gather(
                scheduler.schedule_function(
                    "toy-a",
                    {Actions.VIBRATE1: 4},
                    0.5,
                    stop_previous=False,
                    loop_on_time=None,
                    loop_off_time=None,
                ),
                scheduler.schedule_function(
                    "toy-a",
                    {Actions.VIBRATE2: 7},
                    0.5,
                    stop_previous=False,
                    loop_on_time=None,
                    loop_off_time=None,
                ),
            )
            rows = await scheduler.list_tasks()
            assert any(row.get("feature") == "Vibrate1" for row in rows)
            assert any(row.get("feature") == "Vibrate2" for row in rows)
        finally:
            await scheduler.shutdown()

    asyncio.run(_run())


def test_scheduler_find_matching_session_methods_are_async_safe() -> None:
    async def _run() -> None:
        scheduler = ControlScheduler(_mock_backend(), session_max_sec=2.0)
        try:
            task_id = await scheduler.track_session(
                kind="preset",
                toy_id="toy-a",
                duration=1.0,
                detail={"preset": "Pulse"},
            )
            matched = await scheduler.find_matching_preset_session("toy-a", "Pulse")
            assert matched == task_id
            tasks = await scheduler.list_tasks()
            assert any(row["task_id"] == task_id for row in tasks)
        finally:
            await scheduler.shutdown()

    asyncio.run(_run())
