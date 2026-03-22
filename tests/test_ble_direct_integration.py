"""
BLE hardware integration: auto-scan LVS-* advertisers and run a broad exercise.

Requires: ``pip install 'lovensepy[ble]'``, Bluetooth enabled, toys advertising.
Disconnect Lovense Remote first (single central).

Run::

    uv run --extra ble pytest tests/test_ble_direct_integration.py -v -s

Tune: ``LOVENSE_BLE_SCAN_TIMEOUT``, ``LOVENSE_BLE_STEP_SEC``, ``LOVENSE_BLE_INTER_STEP_SEC``.

Set ``LOVENSE_BLE_STEP_TRACE=1`` to log ``→`` when a timed step **starts** (UART); ``ok:`` is
**after** hold+stop — avoid using ``ok`` as “motor on” timing.

Edge-class toys run an extra **dual probe** (``V1→V2`` then ``V2→V1`` single-motor steps);
look for ``dual probe`` in the log. If a step is silent, tune ``LOVENSE_BLE_DUAL_PROBE_*``
and ``BleDirectClient(..., post_timed_function_silence_cooldown_s=...)`` (see scenario docstring).
"""

from __future__ import annotations

import pytest

from tests.helpers.ble_integration_scenario import run_ble_discovery_exercise


@pytest.mark.asyncio
async def test_ble_discover_and_exercise_all():
    pytest.importorskip("bleak")
    n = await run_ble_discovery_exercise()
    if n == 0:
        pytest.skip("No LVS-* devices in range — disconnect app from toys and retry")
    assert n >= 1
