#!/usr/bin/env python3
"""
Send the same built-in preset to one or many BLE toys in parallel (direct BLE).

Each toy needs its own :class:`~lovensepy.ble_direct.BleDirectClient`. Preset names
match :class:`~lovensepy._constants.Presets` (``pulse``, ``wave``, …). Over BLE,
:meth:`~lovensepy.ble_direct.client.BleDirectClient.preset_request` sends UART
``Pat:{n};`` (integer slot), like Lovense Connect — see :data:`~lovensepy.PRESET_BLE_PAT_INDEX`.

Requires::

    pip install 'lovensepy[ble]'

Disconnect Lovense Remote from the toys first — most devices allow only one BLE
central at a time.

Usage::

    # One toy
    python examples/ble_direct_preset_multi.py AA:BB:CC:DD:EE:FF

    # Several toys (any count): same preset on all
    python examples/ble_direct_preset_multi.py ADDR1 ADDR2 ADDR3 ADDR4 ADDR5 \\
        --preset wave --time 20

    # Preset names: pulse | wave | fireworks | earthquake
    python examples/ble_direct_preset_multi.py AA:... --preset earthquake --time 8
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from lovensepy._constants import Presets
from lovensepy.ble_direct import BleDirectClient
from lovensepy.exceptions import LovenseBLEError


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Send one built-in app preset (pulse/wave/…) to one or more BLE addresses at once.",
    )
    p.add_argument(
        "addresses",
        nargs="+",
        metavar="ADDR",
        help="BLE address per toy (one client each). Pass as many as you need.",
    )
    p.add_argument(
        "--preset",
        choices=[x.value for x in Presets],
        default=Presets.PULSE.value,
        help="Built-in preset name (default: %(default)s).",
    )
    p.add_argument(
        "--time",
        type=float,
        default=15.0,
        metavar="SEC",
        help="How long to let the preset run before sending a motor stop burst (default: %(default)s).",
    )
    p.add_argument(
        "--toy-type",
        default=None,
        metavar="TYPE",
        help="Optional Lovense type hint for all clients (e.g. lush, edge) — improves stop/silence lists.",
    )
    return p.parse_args()


async def _run_preset_on_all(addresses: list[str], *, preset: Presets, seconds: float, toy_type: str | None) -> None:
    clients = [
        BleDirectClient(addr, toy_type=toy_type) for addr in addresses
    ]

    async def connect_one(c: BleDirectClient) -> None:
        try:
            await c.connect()
        except LovenseBLEError as e:
            raise LovenseBLEError(f"{c.address}: {e}") from e

    await asyncio.gather(*(connect_one(c) for c in clients))
    try:
        await asyncio.gather(
            *(c.preset_request(preset, time=seconds) for c in clients)
        )
    finally:
        await asyncio.gather(*(c.disconnect() for c in clients), return_exceptions=True)


def main() -> None:
    args = _parse_args()
    preset = Presets(args.preset)
    try:
        asyncio.run(
            _run_preset_on_all(
                list(args.addresses),
                preset=preset,
                seconds=float(args.time),
                toy_type=args.toy_type,
            )
        )
    except LovenseBLEError as e:
        print(e, file=sys.stderr)
        raise SystemExit(1) from e


if __name__ == "__main__":
    main()
