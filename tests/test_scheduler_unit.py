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


def test_scheduler_indefinite_hold_updates_in_place_without_cancel_dance() -> None:
    """Slider ticks must not stop/re-query on every level change."""

    async def _run() -> None:
        backend = _mock_backend()
        scheduler = ControlScheduler(backend)
        try:
            first = await scheduler.schedule_function(
                "toy-a",
                {Actions.VIBRATE: 4},
                0,
                stop_previous=False,
                loop_on_time=None,
                loop_off_time=None,
            )
            task_id = first["scheduled"][0]["task_id"]
            # Let the hold task apply the first snapshot.
            await asyncio.sleep(0)
            backend.function_request.reset_mock()
            backend.get_toys.reset_mock()
            backend.stop.reset_mock()

            second = await scheduler.schedule_function(
                "toy-a",
                {Actions.VIBRATE: 12},
                0,
                stop_previous=False,
                loop_on_time=None,
                loop_off_time=None,
            )
            assert second["scheduled"][0]["task_id"] == task_id
            assert second["scheduled"][0]["level"] == 12.0

            # One Function write for the new level — no GetToys / stop burst.
            assert backend.function_request.await_count >= 1
            for call in backend.function_request.await_args_list:
                assert call.args[0].get("Vibrate") == 12.0
                assert call.kwargs.get("wait_for_completion") is False
            backend.get_toys.assert_not_awaited()
            backend.stop.assert_not_awaited()

            rows = await scheduler.list_tasks()
            assert len(rows) == 1
            assert rows[0]["level"] == 12.0
        finally:
            await scheduler.shutdown()

    asyncio.run(_run())


def test_scheduler_rapid_slider_ticks_never_send_stop() -> None:
    """Dragging a slider must overwrite levels continuously — never Function(0) between ticks."""

    async def _run() -> None:
        backend = _mock_backend()
        scheduler = ControlScheduler(backend)
        try:
            await scheduler.schedule_function(
                "toy-a",
                {Actions.VIBRATE: 1},
                0,
                stop_previous=False,
                loop_on_time=None,
                loop_off_time=None,
            )
            await asyncio.sleep(0)
            backend.function_request.reset_mock()
            backend.stop.reset_mock()

            task_ids: list[str] = []
            for level in range(2, 16):
                result = await scheduler.schedule_function(
                    "toy-a",
                    {Actions.VIBRATE: float(level)},
                    0,
                    stop_previous=False,
                    loop_on_time=None,
                    loop_off_time=None,
                )
                task_ids.append(result["scheduled"][0]["task_id"])

            assert len(set(task_ids)) == 1, "continuous holds must keep one task id"
            backend.stop.assert_not_awaited()
            for call in backend.function_request.await_args_list:
                actions = call.args[0]
                assert actions.get("Vibrate", 1) > 0, actions
            rows = await scheduler.list_tasks()
            assert rows[0]["level"] == 15.0
        finally:
            await scheduler.shutdown()

    asyncio.run(_run())


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
