"""Tests for :func:`scan_lovense_ble_advertisements` (RSSI field)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_scan_lovense_ble_advertisements_includes_rssi() -> None:
    bleak = pytest.importorskip("bleak")
    from lovensepy.ble_direct.client import scan_lovense_ble_advertisements

    dev = MagicMock()
    dev.address = "AA:BB:CC:DD:EE:FF"
    dev.name = "LVS-TestToy"
    dev.rssi = -55

    with patch.object(bleak.BleakScanner, "discover", new=AsyncMock(return_value=[dev])):
        rows = await scan_lovense_ble_advertisements(timeout=0.01, name_prefix="LVS-")
    assert len(rows) == 1
    assert rows[0].address == dev.address
    assert rows[0].name == dev.name
    assert rows[0].rssi == -55
