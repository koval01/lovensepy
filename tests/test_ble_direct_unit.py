"""
Unit tests for BLE direct client (mocked bleak; no radio).
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lovensepy import LovenseBLEError
from lovensepy._constants import Actions, Presets
from lovensepy.ble_direct import client as ble_client_module
from lovensepy.ble_direct.client import (
    DEFAULT_UART_RX_UUIDS,
    DEFAULT_UART_TX_UUIDS,
    BleDirectClient,
    _slug_from_adv_name,
    ble_direct_client_preset_kwargs_from_env,
    ble_preset_connect_kwargs,
    discover_uart_rx_notify,
    discover_writable_uart_tx,
)
from lovensepy.ble_direct.hub import make_ble_toy_id
from lovensepy.ble_direct.uart_catalog import default_full_stop_payloads


def _svc(chars: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(characteristics=chars)


def test_ble_preset_connect_kwargs_matches_fastapi_defaults():
    assert ble_preset_connect_kwargs(uart_keyword_raw=None, emulate_pattern=False) == {
        "ble_preset_uart_keyword": "Preset",
    }
    assert ble_preset_connect_kwargs(uart_keyword_raw="Pat", emulate_pattern=True) == {
        "ble_preset_uart_keyword": "Pat",
        "ble_preset_emulate_with_pattern": True,
    }


def test_ble_direct_client_preset_kwargs_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOVENSEPY_BLE_PRESET_UART", raising=False)
    monkeypatch.delenv("LOVENSEPY_BLE_PRESET_EMULATE_PATTERN", raising=False)
    assert ble_direct_client_preset_kwargs_from_env() == {"ble_preset_uart_keyword": "Preset"}

    monkeypatch.setenv("LOVENSEPY_BLE_PRESET_UART", "Pat")
    assert ble_direct_client_preset_kwargs_from_env() == {"ble_preset_uart_keyword": "Pat"}

    monkeypatch.setenv("LOVENSEPY_BLE_PRESET_EMULATE_PATTERN", "1")
    assert ble_direct_client_preset_kwargs_from_env() == {
        "ble_preset_uart_keyword": "Pat",
        "ble_preset_emulate_with_pattern": True,
    }


def test_discover_explicit_uuid_ok():
    tx = DEFAULT_UART_TX_UUIDS[0]
    char = SimpleNamespace(uuid=tx, properties=["write"])
    services = [_svc([char])]
    found = discover_writable_uart_tx(services, uart_tx_uuid=tx)
    assert found == tx.lower()


def test_discover_explicit_uuid_case_insensitive():
    tx = DEFAULT_UART_TX_UUIDS[0]
    char = SimpleNamespace(uuid=tx.upper(), properties=["write-without-response"])
    services = [_svc([char])]
    found = discover_writable_uart_tx(services, uart_tx_uuid=tx)
    assert found == tx.lower()


def test_discover_explicit_uuid_trusted_without_write_props():
    """Explicit uart_tx_uuid: accept characteristic even if props omit write (some stacks)."""
    tx = DEFAULT_UART_TX_UUIDS[0]
    char = SimpleNamespace(uuid=tx, properties=["notify"])
    services = [_svc([char])]
    found = discover_writable_uart_tx(services, uart_tx_uuid=tx)
    assert found == tx.lower()


def test_discover_explicit_uuid_missing():
    tx = DEFAULT_UART_TX_UUIDS[0]
    char = SimpleNamespace(uuid="00000000-0000-1000-8000-00805f9b34fb", properties=["write"])
    services = [_svc([char])]
    with pytest.raises(LovenseBLEError, match="No GATT characteristic"):
        discover_writable_uart_tx(services, uart_tx_uuid=tx)


def test_discover_default_candidate():
    tx = DEFAULT_UART_TX_UUIDS[0]
    char = SimpleNamespace(uuid=tx, properties=["write"])
    services = [_svc([char])]
    found = discover_writable_uart_tx(services, uart_tx_uuid=None)
    assert found == tx.lower()


def test_discover_default_uuid_object():
    tx = DEFAULT_UART_TX_UUIDS[0]
    char = SimpleNamespace(uuid=uuid.UUID(tx), properties=["write"])
    services = [_svc([char])]
    found = discover_writable_uart_tx(services, uart_tx_uuid=None)
    assert found == tx.lower()


def test_discover_no_match():
    char = SimpleNamespace(uuid="00000000-0000-1000-8000-00805f9b34fb", properties=["write"])
    services = [_svc([char])]
    with pytest.raises(LovenseBLEError, match="No known"):
        discover_writable_uart_tx(services, uart_tx_uuid=None)


def test_discover_default_fallback_when_props_not_writable():
    tx = DEFAULT_UART_TX_UUIDS[0]
    char = SimpleNamespace(uuid=tx, properties=["notify"])
    services = [_svc([char])]
    found = discover_writable_uart_tx(services, uart_tx_uuid=None)
    assert found == tx.lower()


def test_discover_bleak_style_characteristics_dict():
    tx = DEFAULT_UART_TX_UUIDS[0]
    char = SimpleNamespace(uuid=tx, properties=["write"])
    services = SimpleNamespace(characteristics={99: char})
    found = discover_writable_uart_tx(services, uart_tx_uuid=None)
    assert found == tx.lower()


def test_discover_flexible_lovense_tx_middle_segment():
    """50300002-????-4bd4-bbd5-a6920e4c5653 (e.g. 0024) without listing every variant."""
    tx = "50300002-00ab-4bd4-bbd5-a6920e4c5653"
    char = SimpleNamespace(uuid=tx, properties=["notify"])
    services = [_svc([char])]
    found = discover_writable_uart_tx(services, uart_tx_uuid=None)
    assert found == tx.lower()


def test_discover_flexible_lovense_rx_from_tx_sibling():
    tx = "50300002-00ab-4bd4-bbd5-a6920e4c5653"
    rx = "50300003-00ab-4bd4-bbd5-a6920e4c5653"
    char_tx = SimpleNamespace(uuid=tx, properties=["write"])
    char_rx = SimpleNamespace(uuid=rx, properties=["notify"])
    services = [_svc([char_tx, char_rx])]
    found = discover_uart_rx_notify(services, uart_rx_uuid=None, tx_uuid=tx)
    assert found == rx.lower()


def test_fetch_battery_percent_mock():
    tx = DEFAULT_UART_TX_UUIDS[0]
    rx = DEFAULT_UART_RX_UUIDS[0]
    char_tx = SimpleNamespace(uuid=tx, properties=["write"])
    char_rx = SimpleNamespace(uuid=rx, properties=["notify"])
    services = [_svc([char_tx, char_rx])]

    captured: dict[str, Any] = {}

    inst = MagicMock()
    inst.is_connected = True
    inst.services = services
    inst.connect = AsyncMock()
    inst.disconnect = AsyncMock()

    async def _start_notify(u: str, handler: Any) -> None:
        captured["handler"] = handler

    async def _write(u: str, data: bytes, response: bool = False) -> None:
        h = captured.get("handler")
        if h:
            h(None, b"85;")

    inst.start_notify = AsyncMock(side_effect=_start_notify)
    inst.stop_notify = AsyncMock()
    inst.write_gatt_char = AsyncMock(side_effect=_write)

    client_cls = MagicMock(return_value=inst)

    async def _run() -> None:
        with patch("lovensepy.ble_direct.client._bleak_client_cls", return_value=client_cls):
            c = BleDirectClient("addr")
            await c.connect()
            pct = await c.fetch_battery_percent()
            assert pct == 85

    asyncio.run(_run())


def test_discover_gush_style_family_prefix_tx():
    """Gush and other lines use *0002 with a different first four hex digits than 5030."""
    tx = "455a0002-0023-4bd4-bbd5-a6920e4c5653"
    char = SimpleNamespace(uuid=tx, properties=["write"])
    services = [_svc([char])]
    found = discover_writable_uart_tx(services, uart_tx_uuid=None)
    assert found == tx.lower()


def _assert_bleak_client_kwargs(mock_cls: MagicMock, address: str) -> None:
    mock_cls.assert_called_once()
    args, kwargs = mock_cls.call_args
    assert args[0] == address
    assert callable(kwargs.get("disconnected_callback"))


def _mock_ble_stack(*, connected: bool = True):
    tx = DEFAULT_UART_TX_UUIDS[0]
    char = SimpleNamespace(uuid=tx, properties=["write"])
    services = [_svc([char])]

    instance = MagicMock()
    instance.is_connected = connected
    instance.services = services
    instance.connect = AsyncMock()
    instance.disconnect = AsyncMock()
    instance.write_gatt_char = AsyncMock()

    client_cls = MagicMock(return_value=instance)
    return client_cls, instance


def test_ble_direct_connect_write_and_disconnect():
    client_cls, instance = _mock_ble_stack()

    async def _run() -> None:
        with patch("lovensepy.ble_direct.client._bleak_client_cls", return_value=client_cls):
            c = BleDirectClient("AA:BB:CC:DD:EE:FF")
            await c.connect()
            assert c.is_connected
            assert c.uart_tx_uuid == DEFAULT_UART_TX_UUIDS[0].lower()
            await c.set_vibration(10)
            await c.set_vibration(10)
            await c.disconnect()
            assert not c.is_connected

    asyncio.run(_run())

    _assert_bleak_client_kwargs(client_cls, "AA:BB:CC:DD:EE:FF")
    instance.connect.assert_awaited_once()
    assert instance.write_gatt_char.await_count == 1
    call = instance.write_gatt_char.await_args
    assert call.args[0].lower() == DEFAULT_UART_TX_UUIDS[0].lower()
    assert call.args[1] == b"Vibrate:10;"
    assert call.kwargs.get("response") is False
    instance.disconnect.assert_awaited()


def test_ble_direct_connect_fails_when_not_connected():
    client_cls, instance = _mock_ble_stack(connected=False)

    async def _run() -> None:
        with patch("lovensepy.ble_direct.client._bleak_client_cls", return_value=client_cls):
            c = BleDirectClient("x")
            with pytest.raises(LovenseBLEError, match="connection failed"):
                await c.connect()

    asyncio.run(_run())
    instance.disconnect.assert_awaited()


def test_ble_direct_set_vibration_when_not_connected():
    async def _run() -> None:
        c = BleDirectClient("x")
        with pytest.raises(LovenseBLEError, match="Not connected"):
            await c.set_vibration(1)

    asyncio.run(_run())


def test_set_vibration_routes_edge_to_vibrate1_and_vibrate2():
    """LAN-like UX: one set_vibration() drives every Vibrate* channel for the toy type."""
    client_cls, instance = _mock_ble_stack()

    async def _run() -> None:
        with patch("lovensepy.ble_direct.client._bleak_client_cls", return_value=client_cls):
            c = BleDirectClient(
                "AA:BB:CC:DD:EE:FF",
                toy_type="edge",
                uart_inter_command_delay_s=0,
            )
            await c.connect()
            await c.set_vibration(10)
            await c.disconnect()

    asyncio.run(_run())
    payloads = [c.args[1] for c in instance.write_gatt_char.await_args_list]
    assert payloads[0] == b"Vibrate1:10;"
    assert payloads[1] == b"Vibrate2:10;"


def test_dual_vibrate_inserts_inter_command_delay_between_writes():
    """Back-to-back GATT writes can drop the second command; default spacing uses asyncio.sleep."""
    from unittest.mock import AsyncMock

    from lovensepy.ble_direct.client import DEFAULT_UART_INTER_COMMAND_DELAY_S

    client_cls, instance = _mock_ble_stack()
    sleep_mock = AsyncMock()

    async def _run() -> None:
        with patch("lovensepy.ble_direct.client._bleak_client_cls", return_value=client_cls):
            with patch("lovensepy.ble_direct.client.asyncio.sleep", sleep_mock):
                c = BleDirectClient("AA:BB:CC:DD:EE:FF", toy_type="edge")
                await c.connect()
                await c.set_vibration(5)
                await c.disconnect()

    asyncio.run(_run())
    sleep_mock.assert_awaited_once()
    sleep_mock.assert_awaited_with(DEFAULT_UART_INTER_COMMAND_DELAY_S)
    payloads = [c.args[1] for c in instance.write_gatt_char.await_args_list]
    assert payloads == [b"Vibrate1:5;", b"Vibrate2:5;"]


def test_coerce_dual_vibrate_zeros_peer_when_only_one_channel_given():
    from lovensepy.ble_direct.client import BleDirectClient

    c = BleDirectClient("aa:bb", toy_type="edge")
    c._dual_vibrate_levels = (6, 0)
    assert c._coerce_dual_vibrate_actions({"Vibrate2": 4}) == {"Vibrate1": 0, "Vibrate2": 4}


def test_dual_motor_no_peer_prime_on_first_single_channel_command():
    """First Vibrate1-only after connect has no peer :0; prime (last motor unknown)."""
    client_cls, instance = _mock_ble_stack()

    async def _run() -> None:
        with patch("lovensepy.ble_direct.client._bleak_client_cls", return_value=client_cls):
            c = BleDirectClient(
                "AA:BB:CC:DD:EE:FF",
                toy_type="edge",
                uart_inter_command_delay_s=0,
                dual_single_channel_prime_delay_s=0,
            )
            await c.connect()
            await c.function_request({Actions.VIBRATE1: 6}, time=0)
            await c.disconnect()

    asyncio.run(_run())
    payloads = [c.args[1] for c in instance.write_gatt_char.await_args_list]
    assert payloads[0] == b"Vibrate1:6;"


def test_dual_motor_primes_peer_only_when_switching_channels():
    """Peer :0; prime runs when the active motor changes, not on every single-channel write."""
    client_cls, instance = _mock_ble_stack()

    async def _run() -> None:
        with patch("lovensepy.ble_direct.client._bleak_client_cls", return_value=client_cls):
            c = BleDirectClient(
                "AA:BB:CC:DD:EE:FF",
                toy_type="edge",
                uart_inter_command_delay_s=0,
                dual_single_channel_prime_delay_s=0,
            )
            await c.connect()
            await c.function_request({Actions.VIBRATE1: 6}, time=0)
            await c.function_request({Actions.VIBRATE2: 5}, time=0)
            await c.function_request({Actions.VIBRATE2: 4}, time=0)
            await c.disconnect()

    asyncio.run(_run())
    payloads = [c.args[1] for c in instance.write_gatt_char.await_args_list]
    assert payloads[:4] == [
        b"Vibrate1:6;",
        b"Vibrate1:0;",
        b"Vibrate2:5;",
        b"Vibrate2:4;",
    ]


def test_dual_motor_primes_v2_zero_when_switching_to_v1_after_v2():
    client_cls, instance = _mock_ble_stack()

    async def _run() -> None:
        with patch("lovensepy.ble_direct.client._bleak_client_cls", return_value=client_cls):
            c = BleDirectClient(
                "AA:BB:CC:DD:EE:FF",
                toy_type="edge",
                uart_inter_command_delay_s=0,
                dual_single_channel_prime_delay_s=0,
            )
            await c.connect()
            await c.function_request({Actions.VIBRATE2: 6}, time=0)
            await c.function_request({Actions.VIBRATE1: 5}, time=0)
            await c.disconnect()

    asyncio.run(_run())
    payloads = [c.args[1] for c in instance.write_gatt_char.await_args_list]
    assert payloads[:3] == [b"Vibrate2:6;", b"Vibrate2:0;", b"Vibrate1:5;"]


def test_dual_motor_single_channel_priming_can_be_disabled():
    client_cls, instance = _mock_ble_stack()

    async def _run() -> None:
        with patch("lovensepy.ble_direct.client._bleak_client_cls", return_value=client_cls):
            c = BleDirectClient(
                "AA:BB:CC:DD:EE:FF",
                toy_type="edge",
                uart_inter_command_delay_s=0,
                dual_single_channel_prime_peer_zero=False,
            )
            await c.connect()
            await c.function_request({Actions.VIBRATE1: 6}, time=0)
            await c.disconnect()

    asyncio.run(_run())
    payloads = [c.args[1] for c in instance.write_gatt_char.await_args_list]
    assert payloads[0] == b"Vibrate1:6;"


def test_unsolicited_disconnect_triggers_silence_writes():
    tx = DEFAULT_UART_TX_UUIDS[0]
    char = SimpleNamespace(uuid=tx, properties=["write"])
    services = [_svc([char])]
    stop_writes: list[bytes] = []
    callbacks: list[Any] = []

    main_inst = MagicMock()
    main_inst.is_connected = True
    main_inst.services = services
    main_inst.connect = AsyncMock()
    main_inst.disconnect = AsyncMock()

    temp_inst = MagicMock()
    temp_inst.is_connected = True
    temp_inst.services = services
    temp_inst.connect = AsyncMock()
    temp_inst.disconnect = AsyncMock()

    async def _w(u: str, data: bytes, response: bool = False) -> None:
        stop_writes.append(data)

    temp_inst.write_gatt_char = AsyncMock(side_effect=_w)

    def make_instance(*a: Any, **kw: Any) -> MagicMock:
        if kw.get("disconnected_callback") is not None:
            callbacks.append(kw["disconnected_callback"])
            return main_inst
        return temp_inst

    bleak_class = MagicMock(side_effect=make_instance)

    async def _run() -> None:
        with patch(
            "lovensepy.ble_direct.client._bleak_client_cls",
            return_value=bleak_class,
        ):
            c = BleDirectClient("addr-x", link_loss_silence_timeout=5.0)
            await c.connect()
            assert len(callbacks) == 1
            callbacks[0](MagicMock())
            assert c._link_loss_task is not None
            await c._link_loss_task

    asyncio.run(_run())

    assert stop_writes == list(default_full_stop_payloads())
    temp_inst.connect.assert_awaited_once()
    temp_inst.disconnect.assert_awaited_once()


def test_silence_on_link_loss_false_skips_background_task():
    tx = DEFAULT_UART_TX_UUIDS[0]
    char = SimpleNamespace(uuid=tx, properties=["write"])
    services = [_svc([char])]
    callbacks: list[Any] = []

    main_inst = MagicMock()
    main_inst.is_connected = True
    main_inst.services = services
    main_inst.connect = AsyncMock()
    main_inst.disconnect = AsyncMock()

    def make_instance(*a: Any, **kw: Any) -> MagicMock:
        if kw.get("disconnected_callback") is not None:
            callbacks.append(kw["disconnected_callback"])
        return main_inst

    bleak_class = MagicMock(side_effect=make_instance)

    async def _run() -> None:
        with patch(
            "lovensepy.ble_direct.client._bleak_client_cls",
            return_value=bleak_class,
        ):
            c = BleDirectClient("addr-y", silence_on_link_loss=False)
            await c.connect()
            callbacks[0](MagicMock())
            assert c._link_loss_task is None

    asyncio.run(_run())


def test_two_clients_gather_mock():
    results: list[tuple[str, bytes]] = []

    def make_one(addr: str) -> tuple[MagicMock, MagicMock]:
        tx = DEFAULT_UART_TX_UUIDS[0]
        char = SimpleNamespace(uuid=tx, properties=["write"])
        services = [_svc([char])]
        inst = MagicMock()
        inst.is_connected = True
        inst.services = services
        inst.connect = AsyncMock()
        inst.disconnect = AsyncMock()

        async def _write(u: str, data: bytes, response: bool = False) -> None:
            results.append((addr, data))

        inst.write_gatt_char = AsyncMock(side_effect=_write)
        return MagicMock(return_value=inst), inst

    cls_a, _ = make_one("addr-a")
    cls_b, _ = make_one("addr-b")

    async def _run() -> None:
        class _BleakRouter:
            """``_bleak_client_cls`` returns a class; route instances by BLE address."""

            def __new__(cls, address: str, *args: object, **kwargs: object) -> MagicMock:
                return (cls_a if address == "addr-a" else cls_b)()

        with patch(
            "lovensepy.ble_direct.client._bleak_client_cls",
            return_value=_BleakRouter,
        ):
            a = BleDirectClient("addr-a")
            b = BleDirectClient("addr-b")
            await asyncio.gather(a.connect(), b.connect())
            try:
                await asyncio.gather(a.set_vibration(3), b.set_vibration(7))
            finally:
                await asyncio.gather(a.disconnect(), b.disconnect())

    asyncio.run(_run())

    assert set(results) == {("addr-a", b"Vibrate:3;"), ("addr-b", b"Vibrate:7;")}


def test_ble_connect_serializer_reuses_lock_for_same_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run() -> None:
        monkeypatch.setattr(ble_client_module.sys, "platform", "darwin", raising=False)
        lock1 = ble_client_module._ble_connect_serializer()
        lock2 = ble_client_module._ble_connect_serializer()
        assert lock1 is not None
        assert lock1 is lock2

    asyncio.run(_run())


def test_lovensepy_lazy_ble_direct_client():
    import lovensepy as lp

    assert lp.BleDirectClient is BleDirectClient


def test_build_vibrate_command():
    from lovensepy.ble_direct.client import build_vibrate_command

    assert build_vibrate_command(0) == "Vibrate:0;"
    assert build_vibrate_command(20) == "Vibrate:20;"
    assert build_vibrate_command(99) == "Vibrate:20;"
    assert build_vibrate_command(-1) == "Vibrate:0;"


def test_send_uart_command_semicolon_and_dedupe_reset():
    client_cls, instance = _mock_ble_stack()

    async def _run() -> None:
        with patch("lovensepy.ble_direct.client._bleak_client_cls", return_value=client_cls):
            c = BleDirectClient("AA:BB:CC:DD:EE:FF")
            await c.connect()
            await c.set_vibration(10)
            await c.set_vibration(10)
            await c.send_uart_command("Battery")
            await c.set_vibration(10)
            await c.disconnect()

    asyncio.run(_run())

    assert instance.write_gatt_char.await_count == 3
    payloads = [c.args[1] for c in instance.write_gatt_char.await_args_list]
    assert payloads == [b"Vibrate:10;", b"Battery;", b"Vibrate:10;"]


def test_scan_lovense_ble_devices_filters_prefix():
    from lovensepy.ble_direct.client import scan_lovense_ble_devices

    d1 = SimpleNamespace(address="a1", name="LVS-Edge")
    d2 = SimpleNamespace(address="b2", name="Other")
    d3 = SimpleNamespace(address="c3", name=None)

    mock_scanner_cls = MagicMock()
    mock_scanner_cls.discover = AsyncMock(return_value=[d2, d1, d3])

    async def _run() -> None:
        with patch("bleak.BleakScanner", mock_scanner_cls):
            rows = await scan_lovense_ble_devices(timeout=1.0)
        assert rows == [("a1", "LVS-Edge")]

    asyncio.run(_run())
    mock_scanner_cls.discover.assert_awaited_once_with(timeout=1.0)


def test_ble_direct_client_exposes_standard_constants():
    c = BleDirectClient("aa:bb")
    assert c.actions is Actions
    assert c.presets is Presets
    assert 200 in c.error_codes


def test_ble_direct_function_request_writes_uart():
    client_cls, instance = _mock_ble_stack()

    async def _run() -> None:
        with patch("lovensepy.ble_direct.client._bleak_client_cls", return_value=client_cls):
            c = BleDirectClient("AA:BB:CC:DD:EE:FF", toy_type="lush")
            await c.connect()
            r = await c.function_request({Actions.VIBRATE: 10})
            assert r.code == 200
            assert r.data and r.data.get("transport") == "ble"
            await c.disconnect()

    asyncio.run(_run())
    payloads = [c.args[1] for c in instance.write_gatt_char.await_args_list]
    assert b"Vibrate:10;" in payloads


def test_ble_direct_send_command_function_json():
    client_cls, instance = _mock_ble_stack()

    async def _run() -> None:
        with patch("lovensepy.ble_direct.client._bleak_client_cls", return_value=client_cls):
            c = BleDirectClient("AA:BB:CC:DD:EE:FF")
            await c.connect()
            out = await c.send_command(
                {
                    "command": "Function",
                    "action": "Vibrate:12",
                    "timeSec": 0,
                    "apiVer": 1,
                }
            )
            assert out["code"] == 200
            assert c.last_command is not None
            assert c.last_command["command"] == "Function"
            await c.disconnect()

    asyncio.run(_run())
    payloads = [c.args[1] for c in instance.write_gatt_char.await_args_list]
    assert b"Vibrate:12;" in payloads


def test_ble_direct_preset_builtin_open_ended_sends_pat_index():
    client_cls, instance = _mock_ble_stack()

    async def _run() -> None:
        with patch("lovensepy.ble_direct.client._bleak_client_cls", return_value=client_cls):
            c = BleDirectClient("AA:BB:CC:DD:EE:FF", toy_type="lush")
            await c.connect()
            r = await c.preset_request(Presets.WAVE, open_ended=True)
            assert r.code == 200
            assert not (r.data and r.data.get("deferred"))
            await c.disconnect()

    asyncio.run(_run())
    payloads = [c.args[1] for c in instance.write_gatt_char.await_args_list]
    assert b"Pat:2;" in payloads


def test_ble_direct_preset_default_time_triggers_stop_burst():
    client_cls, instance = _mock_ble_stack()
    sleep_mock = AsyncMock()

    async def _run() -> None:
        with patch("lovensepy.ble_direct.client._bleak_client_cls", return_value=client_cls):
            with patch("lovensepy.ble_direct.client.asyncio.sleep", sleep_mock):
                c = BleDirectClient("AA:BB:CC:DD:EE:FF", toy_type="lush")
                await c.connect()
                await c.preset_request(Presets.PULSE, time=0, open_ended=False)
                await c.disconnect()

    asyncio.run(_run())
    sleep_mock.assert_awaited()
    payloads = [c.args[1] for c in instance.write_gatt_char.await_args_list]
    assert b"Pat:1;" in payloads
    assert b"Vibrate:0;" in payloads


def test_ble_direct_preset_wait_false_writes_pat_before_return():
    """Timed preset: Pat UART before return; hold deferred if wait_for_completion=False."""
    client_cls, instance = _mock_ble_stack()
    sleep_mock = AsyncMock()

    async def _run() -> None:
        with patch("lovensepy.ble_direct.client._bleak_client_cls", return_value=client_cls):
            with patch("lovensepy.ble_direct.client.asyncio.sleep", sleep_mock):
                c = BleDirectClient("AA:BB:CC:DD:EE:FF", toy_type="lush")
                await c.connect()
                r = await c.preset_request(Presets.WAVE, time=4.0, wait_for_completion=False)
                assert r.data and r.data.get("deferred") is True
                payloads_now = [x.args[1] for x in instance.write_gatt_char.await_args_list]
                assert b"Pat:2;" in b"".join(payloads_now)
                await asyncio.sleep(0)
                await c.disconnect()

    asyncio.run(_run())
    sleep_mock.assert_awaited()


def test_ble_direct_preset_unknown_name_raises():
    client_cls, instance = _mock_ble_stack()

    async def _run() -> None:
        with patch("lovensepy.ble_direct.client._bleak_client_cls", return_value=client_cls):
            c = BleDirectClient("AA:BB:CC:DD:EE:FF", toy_type="lush")
            await c.connect()
            with pytest.raises(LovenseBLEError, match="Unknown BLE preset"):
                await c.preset_request("not_a_preset", time=1.0)
            await c.disconnect()

    asyncio.run(_run())


def test_ble_direct_preset_numeric_string_sends_pat():
    client_cls, instance = _mock_ble_stack()

    async def _run() -> None:
        with patch("lovensepy.ble_direct.client._bleak_client_cls", return_value=client_cls):
            c = BleDirectClient("AA:BB:CC:DD:EE:FF", toy_type="lush")
            await c.connect()
            await c.preset_request("7", time=1.0)
            await c.disconnect()

    asyncio.run(_run())
    payloads = [c.args[1] for c in instance.write_gatt_char.await_args_list]
    assert b"Pat:7;" in payloads


def test_ble_direct_preset_numeric_out_of_range_raises():
    client_cls, _instance = _mock_ble_stack()

    async def _run() -> None:
        with patch("lovensepy.ble_direct.client._bleak_client_cls", return_value=client_cls):
            c = BleDirectClient("AA:BB:CC:DD:EE:FF", toy_type="lush")
            await c.connect()
            with pytest.raises(LovenseBLEError, match="out of range"):
                await c.preset_request("21", time=1.0)
            await c.disconnect()

    asyncio.run(_run())


def test_ble_direct_preset_emulate_pattern_skips_pat_uart():
    client_cls, instance = _mock_ble_stack()

    async def _run() -> None:
        with patch("lovensepy.ble_direct.client._bleak_client_cls", return_value=client_cls):
            c = BleDirectClient(
                "AA:BB:CC:DD:EE:FF",
                toy_type="lush",
                ble_preset_emulate_with_pattern=True,
            )
            await c.connect()
            await c.preset_request(Presets.PULSE, time=2.0)
            await c.disconnect()

    asyncio.run(_run())
    payloads = [c.args[1] for c in instance.write_gatt_char.await_args_list]
    assert not any(b"Pat:" in p or b"Preset:" in p for p in payloads)
    assert any(b"Vibrate:" in p for p in payloads)


def test_ble_direct_preset_preset_keyword_sends_preset_uart():
    client_cls, instance = _mock_ble_stack()

    async def _run() -> None:
        with patch("lovensepy.ble_direct.client._bleak_client_cls", return_value=client_cls):
            c = BleDirectClient(
                "AA:BB:CC:DD:EE:FF",
                toy_type="lush",
                ble_preset_uart_keyword="Preset",
            )
            await c.connect()
            await c.preset_request(Presets.PULSE, time=1.0)
            await c.disconnect()

    asyncio.run(_run())
    payloads = [c.args[1] for c in instance.write_gatt_char.await_args_list]
    assert b"Preset:1;" in payloads


def test_ble_direct_get_toys_raises():
    client_cls, _instance = _mock_ble_stack()

    async def _run() -> None:
        with patch("lovensepy.ble_direct.client._bleak_client_cls", return_value=client_cls):
            c = BleDirectClient("AA:BB:CC:DD:EE:FF")
            await c.connect()
            with pytest.raises(LovenseBLEError, match="GetToys"):
                await c.get_toys()
            await c.disconnect()

    asyncio.run(_run())


def test_ble_actions_to_uart_strings_expands_all_for_edge():
    from lovensepy.ble_direct.standard_compat import ble_actions_to_uart_strings

    lines = ble_actions_to_uart_strings({"All": 5}, toy_type_hint="edge")
    assert lines == ["Vibrate1:5;", "Vibrate2:5;"]


def test_ble_actions_dual_motor_primes_sibling_channel():
    """Dual Vibrate* → two UART lines (two GATT writes); single-key callers prepend sibling zero."""
    from lovensepy.ble_direct.standard_compat import ble_actions_to_uart_strings

    v1 = ble_actions_to_uart_strings({"Vibrate1": 6}, toy_type_hint="edge")
    assert v1 == ["Vibrate1:6;"]

    v2 = ble_actions_to_uart_strings({"Vibrate2": 6}, toy_type_hint="edge")
    assert v2 == ["Vibrate2:6;"]

    both = ble_actions_to_uart_strings({"Vibrate1": 3, "Vibrate2": 4}, toy_type_hint="edge")
    assert both == ["Vibrate1:3;", "Vibrate2:4;"]

    only2 = ble_actions_to_uart_strings({"Vibrate1": 0, "Vibrate2": 6}, toy_type_hint="edge")
    assert only2 == ["Vibrate2:6;"]

    only1 = ble_actions_to_uart_strings({"Vibrate1": 7, "Vibrate2": 0}, toy_type_hint="edge")
    assert only1 == ["Vibrate1:7;"]

    lush = ble_actions_to_uart_strings({"Vibrate": 6}, toy_type_hint="lush")
    assert lush == ["Vibrate:6;"]


def test_slug_from_adv_name_no_space_before_underscore_in_toy_id():
    """``LVS-Edge 2`` style names must not yield ``edge _…`` toy ids (trailing space bug)."""
    assert _slug_from_adv_name("LVS-Edge 2") == "edge"
    assert _slug_from_adv_name("LVS-Gush 2") == "gush"
    tid = make_ble_toy_id("AA:BB:CC:DD:EE:FF", "LVS-Edge 2", 0)
    assert " " not in tid
    assert tid.startswith("edge_")


def test_gatt_write_resilient_retries_transient_oserror():
    client_cls, instance = _mock_ble_stack()
    n = {"c": 0}

    async def flaky_write(u: str, data: bytes, response: bool = False) -> None:
        n["c"] += 1
        if n["c"] < 3:
            raise OSError(5, "EIO")

    instance.write_gatt_char = AsyncMock(side_effect=flaky_write)

    async def _run() -> None:
        with patch("lovensepy.ble_direct.client._bleak_client_cls", return_value=client_cls):
            c = BleDirectClient(
                "addr",
                gatt_write_max_attempts=5,
                gatt_write_retry_base_delay=0.0,
                gatt_write_retry_max_delay=0.0,
            )
            await c.connect()
            await c.send_uart_bytes(b"X;", reset_dual_motor_route=False)
            await c.disconnect()

    asyncio.run(_run())
    assert n["c"] == 3


def test_gatt_write_resilient_no_retry_on_value_error():
    client_cls, instance = _mock_ble_stack()
    instance.write_gatt_char = AsyncMock(side_effect=ValueError("not transient"))

    async def _run() -> None:
        with patch("lovensepy.ble_direct.client._bleak_client_cls", return_value=client_cls):
            c = BleDirectClient(
                "addr",
                gatt_write_max_attempts=5,
                gatt_write_retry_base_delay=0.0,
                gatt_write_retry_max_delay=0.0,
            )
            await c.connect()
            with pytest.raises(LovenseBLEError, match="not transient"):
                await c.send_uart_bytes(b"X;", reset_dual_motor_route=False)
            await c.disconnect()

    asyncio.run(_run())
    assert instance.write_gatt_char.await_count == 1
