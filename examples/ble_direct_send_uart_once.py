#!/usr/bin/env python3
"""Send one raw UART line over BLE (e.g. isolate ``Vibrate2`` on Edge).

Disconnect Lovense Remote first — only one BLE central at a time.

Usage:
  uv run python examples/ble_direct_send_uart_once.py AA:BB:CC:DD:EE:FF
  uv run python examples/ble_direct_send_uart_once.py
  uv run python examples/ble_direct_send_uart_once.py --name Edge
  uv run python examples/ble_direct_send_uart_once.py --pick 2
  uv run python examples/ble_direct_send_uart_once.py AA:BB:... --cmd 'Vibrate2:15;'
  uv run python examples/ble_direct_send_uart_once.py AA:BB:... --level 12 --hold 2
"""

from __future__ import annotations

import argparse
import asyncio
import sys


async def _resolve_address(
    address: str | None,
    *,
    scan_timeout: float,
    name_substr: str | None,
    pick: int | None,
) -> str | None:
    """Return explicit address or pick one from :func:`scan_lovense_ble_devices`."""
    if address and address.strip():
        return address.strip()

    from lovensepy.ble_direct import scan_lovense_ble_devices

    rows = await scan_lovense_ble_devices(timeout=scan_timeout, name_prefix="LVS-")
    if name_substr:
        needle = name_substr.strip().lower()
        rows = [(a, n) for a, n in rows if needle in (n or "").lower()]
    if not rows:
        print(
            "No matching Lovense advertisers (names starting with LVS-). "
            "Wake the toy, move it closer, or pass the BLE address explicitly.",
            file=sys.stderr,
        )
        return None
    if len(rows) > 1 and pick is None:
        print("Several devices found — choose one:", file=sys.stderr)
        for i, (addr, name) in enumerate(rows, 1):
            print(f"  {i}. {addr}  {name!r}", file=sys.stderr)
        print("Re-run with --pick N (1-based) or pass the address as the first argument.", file=sys.stderr)
        return None
    idx = (pick if pick is not None else 1) - 1
    if idx < 0 or idx >= len(rows):
        print(f"--pick must be between 1 and {len(rows)}.", file=sys.stderr)
        return None
    chosen_addr, chosen_name = rows[idx]
    print(f"Using {chosen_addr!r} ({chosen_name!r})", flush=True)
    return chosen_addr


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Send one Lovense UART command over BLE.")
    parser.add_argument(
        "address",
        nargs="?",
        default=None,
        help="BLE address (optional: omit to scan for LVS- advertisers)",
    )
    parser.add_argument(
        "--cmd",
        default="",
        help="Full UART line (default: Vibrate2 at --level)",
    )
    parser.add_argument("--level", type=int, default=15, help="Used when --cmd is omitted (0..20)")
    parser.add_argument(
        "--hold",
        type=float,
        default=2.0,
        help="Seconds to keep level before silence + disconnect",
    )
    parser.add_argument(
        "--toy-type",
        default="edge",
        help="For silence_all_motors() stop burst (default: edge)",
    )
    parser.add_argument(
        "--no-silence",
        action="store_true",
        help="Skip stop burst after --hold (motors may keep running)",
    )
    parser.add_argument(
        "--scan-timeout",
        type=float,
        default=8.0,
        help="Seconds to listen when resolving address by scan (default: 8)",
    )
    parser.add_argument(
        "--name",
        dest="name_substr",
        default=None,
        metavar="SUBSTR",
        help="When scanning: keep only devices whose advertised name contains this (case-insensitive)",
    )
    parser.add_argument(
        "--pick",
        type=int,
        default=None,
        metavar="N",
        help="When scanning: use Nth device from the scan list (1-based), if several match",
    )
    args = parser.parse_args()

    from lovensepy.ble_direct import BleDirectClient
    from lovensepy.exceptions import LovenseBLEError

    resolved = await _resolve_address(
        args.address,
        scan_timeout=args.scan_timeout,
        name_substr=args.name_substr,
        pick=args.pick,
    )
    if resolved is None:
        return 1

    cmd = args.cmd.strip()
    if not cmd:
        lv = max(0, min(20, int(args.level)))
        cmd = f"Vibrate2:{lv};"

    client = BleDirectClient(
        resolved,
        toy_type=args.toy_type,
        uart_inter_command_delay_s=0,
    )
    try:
        await client.connect()
        print(f"Connected. Sending: {cmd!r}", flush=True)
        await client.send_uart_command(cmd, ensure_semicolon=False)
        await asyncio.sleep(max(0.0, float(args.hold)))
        if not args.no_silence:
            await client.silence_all_motors(args.toy_type)
            print("Stop burst sent.", flush=True)
    except LovenseBLEError as e:
        print(e, file=sys.stderr)
        return 1
    finally:
        await client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
