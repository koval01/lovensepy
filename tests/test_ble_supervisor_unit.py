"""Unit tests for the BLE auto-reconnect supervisor."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytest.importorskip("fastapi")

from lovensepy.services.http_api.ble_supervisor import BleSupervisor
from lovensepy.services.http_api.config import ServiceConfig


class _FakeHub:
    """Registry-shaped stub: connect() succeeds only once the toy is 'in range'."""

    def __init__(self, *, reachable: bool = True) -> None:
        self.rows: list[dict[str, Any]] = [
            {"toy_id": "toy-1", "address": "AA:BB", "connected": False, "battery": None}
        ]
        self.reachable = reachable
        self.connect_calls: list[str] = []
        self.battery_calls: list[str] = []

    def registry_rows(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.rows]

    async def connect(self, toy_id: str) -> None:
        self.connect_calls.append(toy_id)
        if not self.reachable:
            raise RuntimeError("device not found")
        for row in self.rows:
            if row["toy_id"] == toy_id:
                row["connected"] = True

    async def refresh_battery(self, toy_id: str) -> int | None:
        self.battery_calls.append(toy_id)
        for row in self.rows:
            if row["toy_id"] == toy_id:
                row["battery"] = 66
        return 66


def _supervisor(
    hub: _FakeHub, cfg: ServiceConfig, changes: list[int] | None = None
) -> BleSupervisor:
    return BleSupervisor(
        hub_provider=lambda: hub,  # type: ignore[arg-type]
        config_provider=lambda: cfg,
        lock=asyncio.Lock(),
        on_change=(lambda: changes.append(1)) if changes is not None else None,
    )


async def test_round_reconnects_and_reads_battery() -> None:
    hub = _FakeHub()
    changes: list[int] = []
    supervisor = _supervisor(hub, ServiceConfig(mode="ble"), changes)

    await supervisor.run_once()

    assert hub.connect_calls == ["toy-1"]
    assert hub.battery_calls == ["toy-1"]
    assert changes, "reconnects must notify watchers so /ws pushes a new snapshot"

    status = supervisor.status()["toys"]["toy-1"]
    assert status["reconnects"] == 1
    assert status["attempts"] == 0
    assert status["last_error"] is None
    assert status["recent"][-1] == "reconnected"


async def test_failed_attempts_back_off_instead_of_hammering_the_radio() -> None:
    hub = _FakeHub(reachable=False)
    cfg = ServiceConfig(mode="ble")
    supervisor = _supervisor(hub, cfg)

    await supervisor.run_once()
    first = supervisor.status()["toys"]["toy-1"]
    assert first["attempts"] == 1
    assert "device not found" in (first["last_error"] or "")
    assert first["retry_in_sec"] > 0

    # A second round inside the backoff window must not touch the device again.
    await supervisor.run_once()
    assert hub.connect_calls == ["toy-1"]


async def test_manual_disconnect_pauses_until_the_user_asks_again() -> None:
    hub = _FakeHub()
    cfg = ServiceConfig(mode="ble")
    supervisor = _supervisor(hub, cfg)

    supervisor.pause("toy-1")
    await supervisor.run_once()
    assert hub.connect_calls == []
    assert supervisor.status()["toys"]["toy-1"]["paused"] is True

    supervisor.resume("toy-1")
    await supervisor.run_once()
    assert hub.connect_calls == ["toy-1"]


async def test_auto_reconnect_can_be_switched_off() -> None:
    hub = _FakeHub()
    cfg = ServiceConfig(mode="ble", ble_auto_reconnect=False)
    supervisor = _supervisor(hub, cfg)

    await supervisor.run_once()

    assert hub.connect_calls == []
    assert supervisor.status()["enabled"] is False


async def test_forgotten_toys_drop_out_of_status() -> None:
    hub = _FakeHub()
    cfg = ServiceConfig(mode="ble")
    supervisor = _supervisor(hub, cfg)
    await supervisor.run_once()
    assert "toy-1" in supervisor.status()["toys"]

    hub.rows.clear()
    await supervisor.run_once()
    assert supervisor.status()["toys"] == {}


async def test_start_and_stop_are_idempotent() -> None:
    hub = _FakeHub()
    cfg = ServiceConfig(mode="ble")
    supervisor = _supervisor(hub, cfg)

    supervisor.start()
    supervisor.start()
    assert supervisor.running is True
    await asyncio.sleep(0)

    await supervisor.stop()
    await supervisor.stop()
    assert supervisor.running is False
