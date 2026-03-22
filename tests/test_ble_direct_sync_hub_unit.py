"""Tests for :class:`BleDirectHubSync` and :func:`run_ble_coroutine`."""

from __future__ import annotations

import asyncio
import concurrent.futures
from unittest.mock import AsyncMock, MagicMock

import pytest

from lovensepy._constants import Actions
from lovensepy._models import CommandResponse
from lovensepy.ble_direct.sync_hub import (
    BleDirectHubSync,
    ble_sync_default_timeout,
    run_ble_coroutine,
)


def test_ble_sync_default_timeout_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOVENSEPY_BLE_SYNC_TIMEOUT", "none")
    assert ble_sync_default_timeout() is None
    monkeypatch.setenv("LOVENSEPY_BLE_SYNC_TIMEOUT", "42")
    assert ble_sync_default_timeout() == 42.0


def test_run_ble_coroutine_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOVENSEPY_BLE_SYNC_TIMEOUT", "0.05")

    async def _slow() -> None:
        await asyncio.sleep(3600)

    with pytest.raises(concurrent.futures.TimeoutError):
        run_ble_coroutine(_slow())


def test_run_ble_coroutine_explicit_timeout_kwarg() -> None:
    async def _slow() -> None:
        await asyncio.sleep(3600)

    with pytest.raises(concurrent.futures.TimeoutError):
        run_ble_coroutine(_slow(), timeout=0.05)


def test_run_ble_coroutine_runs_simple_coro():
    async def _one() -> int:
        return 7

    assert run_ble_coroutine(_one()) == 7


def test_run_ble_coroutine_raises_when_loop_running():
    async def _async_identity(x: int) -> int:
        return x

    async def _inner() -> None:
        coro = _async_identity(1)
        try:
            with pytest.raises(RuntimeError, match="event loop"):
                run_ble_coroutine(coro)
        finally:
            coro.close()

    asyncio.run(_inner())


def test_sync_hub_play_calls_function_and_stop():
    ok = CommandResponse(code=200, type="OK", result=True)
    h = BleDirectHubSync()
    mock_hub = MagicMock()
    mock_hub.function_request = AsyncMock(return_value=ok)
    mock_hub.stop = AsyncMock(return_value=ok)
    h._hub = mock_hub

    with h.play({Actions.VIBRATE: 5}, time=0.1, toy_id="t1"):
        pass

    mock_hub.function_request.assert_awaited_once()
    mock_hub.stop.assert_awaited_once()


def test_sync_hub_get_toys_delegates():
    from lovensepy._models import GetToysResponse

    h = BleDirectHubSync()
    mock_hub = MagicMock()
    out = GetToysResponse.model_validate({"data": {"toys": []}})
    mock_hub.get_toys = AsyncMock(return_value=out)
    h._hub = mock_hub

    r = h.get_toys(query_battery=False)
    assert r == out
    mock_hub.get_toys.assert_awaited_once_with(query_battery=False)


def test_lovensepy_lazy_import_ble_direct_hub_sync():
    import lovensepy

    assert lovensepy.BleDirectHubSync is BleDirectHubSync
