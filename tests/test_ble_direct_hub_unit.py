"""Unit tests for :class:`BleDirectHub` (mocked clients)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lovensepy._constants import Actions, Presets
from lovensepy._models import CommandResponse
from lovensepy.ble_direct.hub import BleDirectHub
from lovensepy.ble_direct.uart_replies import DeviceTypeFields
from lovensepy.exceptions import LovenseBLEError


def _mock_client() -> MagicMock:
    c = MagicMock()
    c.is_connected = True
    c.connect = AsyncMock()
    c.cancel_deferred_playback = AsyncMock()
    c.disconnect = AsyncMock()
    c.fetch_battery_percent = AsyncMock(return_value=77)
    ok = CommandResponse(code=200, type="OK", result=True)
    c.function_request = AsyncMock(return_value=ok)
    c.stop = AsyncMock(return_value=ok)
    c.preset_request = AsyncMock(return_value=ok)
    c.pattern_request = AsyncMock(return_value=ok)
    c.pattern_request_raw = AsyncMock(return_value=ok)
    c.position_request = AsyncMock(return_value=ok)
    c.send_command = AsyncMock(return_value={"code": 200, "type": "OK"})
    c.silence_all_motors = AsyncMock()
    return c


def test_hub_preset_all_toys_when_toy_id_none():
    a = _mock_client()
    b = _mock_client()

    with patch("lovensepy.ble_direct.hub.BleDirectClient", side_effect=[a, b]):
        h = BleDirectHub()
        h.add_toy("edge-a", "aa:bb")
        h.add_toy("lush-b", "cc:dd")

    asyncio.run(h.preset_request(Presets.PULSE, time=1.0, toy_id=None))

    a.preset_request.assert_awaited_once()
    b.preset_request.assert_awaited_once()


def test_hub_send_command_get_toys_no_per_client():
    a = _mock_client()
    with patch("lovensepy.ble_direct.hub.BleDirectClient", return_value=a):
        h = BleDirectHub()
        h.add_toy("t1", "x", name="LVS-X")

    out = asyncio.run(h.send_command({"command": "GetToys"}))
    assert out["code"] == 200
    assert out["data"]["toys"]
    assert out["data"]["toys"][0]["id"] == "t1"
    a.send_command.assert_not_awaited()


def test_hub_function_request_multi_toy_uses_single_shared_sleep():
    """Several toys + ``time > 0`` → start all with ``time=0``, one ``asyncio.sleep``.

    Then stop all.
    """
    a = _mock_client()
    b = _mock_client()
    sleeps: list[float] = []

    async def _track_sleep(t: float) -> None:
        sleeps.append(float(t))

    with patch("lovensepy.ble_direct.hub.BleDirectClient", side_effect=[a, b]):
        h = BleDirectHub()
        h.add_toy("t1", "aa:bb", toy_type="edge")
        h.add_toy("t2", "cc:dd", toy_type="gush")

    async def _run() -> None:
        with patch("lovensepy.ble_direct.hub.asyncio.sleep", side_effect=_track_sleep):
            await h.function_request({Actions.VIBRATE: 8}, time=2.5, toy_id=None)

    asyncio.run(_run())

    assert sleeps == [2.5]
    a.function_request.assert_awaited_once()
    b.function_request.assert_awaited_once()
    _, ak = a.function_request.call_args
    assert ak["time"] == 0 and ak["stop_previous"] is False
    _, bk = b.function_request.call_args
    assert bk["time"] == 0 and bk["stop_previous"] is False
    a.stop.assert_awaited_once()
    b.stop.assert_awaited_once()


def test_coordinated_hold_ends_early_when_stop_runs():
    """Long multi-toy hold should not block until ``stop`` sets the cancel event."""
    import time

    a = _mock_client()
    b = _mock_client()

    with patch("lovensepy.ble_direct.hub.BleDirectClient", side_effect=[a, b]):
        h = BleDirectHub()
        h.add_toy("t1", "aa:bb", toy_type="edge")
        h.add_toy("t2", "cc:dd", toy_type="gush")

    async def _run() -> None:
        t0 = time.monotonic()
        fr = asyncio.create_task(h.function_request({Actions.VIBRATE: 8}, time=3600.0, toy_id=None))
        await asyncio.sleep(0)
        await h.stop()
        await fr
        assert time.monotonic() - t0 < 2.0

    asyncio.run(_run())

    assert a.stop.await_count >= 1
    assert b.stop.await_count >= 1


def test_hub_unknown_toy_raises():
    h = BleDirectHub()
    h.add_toy("only", "addr")

    async def _run() -> None:
        with pytest.raises(LovenseBLEError, match="Unknown toy"):
            await h.function_request({h.actions.VIBRATE: 5}, toy_id="nope")

    asyncio.run(_run())


def test_discover_renames_toy_id_from_device_type_mac():
    """After UART enrich, prefer real BT MAC from ``DeviceType`` over OS address tail."""
    a = _mock_client()
    a.fetch_ble_snapshot = AsyncMock(
        return_value={
            "battery_percent": 88,
            "device_type": DeviceTypeFields(
                model_letter="P",
                firmware="240",
                bt_addr_hex="0082059AD3BD",
                raw="P:240:0082059AD3BD;",
            ),
            "suggested_features": ("Vibrate1", "Vibrate2"),
        }
    )

    async def _scan(*_a: object, **_k: object) -> list[tuple[str, str | None]]:
        return [("AA:BB:CC:DD:EE:01", "LVS-Edge")]

    async def _run() -> None:
        with patch("lovensepy.ble_direct.hub.BleDirectClient", return_value=a):
            with patch("lovensepy.ble_direct.hub.scan_lovense_ble_devices", _scan):
                h = BleDirectHub()
                ids = await h.discover_and_connect(timeout=1.0, enrich_uart=True)
                assert ids == ["edge_82059ad3bd"]

    asyncio.run(_run())


def test_discover_and_connect_registers_and_enriches():
    a = _mock_client()
    a.fetch_ble_snapshot = AsyncMock(
        return_value={
            "battery_percent": 88,
            "device_type": DeviceTypeFields(
                model_letter="P",
                firmware="240",
                bt_addr_hex="00",
                raw="P:240:00;",
            ),
            "suggested_features": ("Vibrate1", "Vibrate2"),
        }
    )

    async def _scan(*_a: object, **_k: object) -> list[tuple[str, str | None]]:
        return [("AA:BB:CC:DD:EE:01", "LVS-Edge")]

    async def _run() -> None:
        with patch("lovensepy.ble_direct.hub.BleDirectClient", return_value=a):
            with patch("lovensepy.ble_direct.hub.scan_lovense_ble_devices", _scan):
                h = BleDirectHub()
                ids = await h.discover_and_connect(timeout=1.0, enrich_uart=True)
                assert len(ids) == 1
                r = await h.get_toys(query_battery=False)
                assert r.data and r.data.toys[0].version == "240"

    asyncio.run(_run())


def test_get_toys_battery_fallback_from_enrich_cache():
    """If a fresh ``Battery;`` read fails, reuse percent from UART enrich snapshot."""
    a = _mock_client()
    a.fetch_battery_percent = AsyncMock(side_effect=RuntimeError("no second line"))
    a.fetch_ble_snapshot = AsyncMock(
        return_value={
            "battery_percent": 42,
            "device_type": DeviceTypeFields(
                model_letter="P",
                firmware="1",
                bt_addr_hex="00",
                raw="P:1:00;",
            ),
            "suggested_features": ("Vibrate",),
        }
    )

    async def _scan(*_a: object, **_k: object) -> list[tuple[str, str | None]]:
        return [("AA:BB:CC:DD:EE:01", "LVS-Gush")]

    async def _run() -> None:
        with patch("lovensepy.ble_direct.hub.BleDirectClient", return_value=a):
            with patch("lovensepy.ble_direct.hub.scan_lovense_ble_devices", _scan):
                h = BleDirectHub()
                await h.discover_and_connect(timeout=1.0, enrich_uart=True)
                r = await h.get_toys(query_battery=True)
                assert r.data and r.data.toys[0].battery == 42

    asyncio.run(_run())


def test_hub_replace_requires_disconnect():
    a = _mock_client()
    a.is_connected = True
    with patch("lovensepy.ble_direct.hub.BleDirectClient", return_value=a):
        h = BleDirectHub()
        h.add_toy("t1", "addr1")

    with pytest.raises(LovenseBLEError, match="still connected"):
        h.add_toy("t1", "addr2", replace=True)
