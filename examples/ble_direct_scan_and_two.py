#!/usr/bin/env python3
"""
CLI: scan BLE, pick Lovense toys (advertised as LVS-Name), send a short test pattern.

Requires:
    pip install 'lovensepy[ble]'

Interactive menu: ``pip install 'lovensepy[ble]'`` includes ``pick`` (arrow keys, Space to
    toggle, Enter to confirm). Use ``--no-tui`` to type device numbers instead.

Important:
    Disconnect Lovense Remote from the toys first — most devices allow only one
    BLE central at a time.

Usage:
    # Interactive: scan (LVS-* only), then pick one or more toys
    python examples/ble_direct_scan_and_two.py
    python examples/ble_direct_scan_and_two.py --timeout 15

    # List-only scan
    python examples/ble_direct_scan_and_two.py --scan
    python examples/ble_direct_scan_and_two.py --scan --all

    # Non-interactive: explicit addresses
    python examples/ble_direct_scan_and_two.py <ADDR1> <ADDR2> ...

    # Sine-wave drive (checks smooth updates; uses send_uart_command every step)
    python examples/ble_direct_scan_and_two.py --wave
    python examples/ble_direct_scan_and_two.py --wave --no-pulse --wave-seconds 12 --wave-interval 0.04
"""

from __future__ import annotations

import argparse
import asyncio
import math
import re
import sys
import time
from typing import Any

from lovensepy.exceptions import LovenseBLEError


def _is_lovense_adv_name(name: str | None) -> bool:
    if not name:
        return False
    return name.strip().upper().startswith("LVS-")


def _filter_devices(
    devices: list[Any],
    *,
    lovense_only: bool,
    name_substr: str | None,
) -> list[Any]:
    out: list[Any] = []
    for d in devices:
        name = d.name
        if lovense_only and not _is_lovense_adv_name(name):
            continue
        if name_substr and name_substr.lower() not in (name or "").lower():
            continue
        out.append(d)
    return sorted(out, key=lambda x: ((x.name or "").lower(), x.address))


def _print_device_table(devices: list[Any], *, numbered: bool) -> None:
    if numbered:
        header = f"{'#':>3}  {'Address':<40} {'RSSI':>5}  Name"
    else:
        header = f"{'Address':<40} {'RSSI':>5}  Name"
    print(header)
    print("-" * 72)
    for i, d in enumerate(devices, 1):
        rssi = getattr(d, "rssi", None)
        rssi_s = "" if rssi is None else str(rssi)
        prefix = f"{i:>3}  " if numbered else ""
        print(f"{prefix}{d.address:<40} {rssi_s:>5}  {d.name or '—'}")


def _parse_index_line(line: str, n: int) -> list[int]:
    """Parse '1,2' / '1 2' / '1, 3' into 0-based indices."""
    parts = re.split(r"[\s,;]+", line.strip())
    seen: set[int] = set()
    for p in parts:
        if not p:
            continue
        idx = int(p) - 1
        if idx < 0 or idx >= n:
            raise ValueError(f"Invalid choice {p!r} (use 1–{n})")
        seen.add(idx)
    if not seen:
        raise ValueError("Select at least one number")
    return sorted(seen)


def _select_devices_interactive(devices: list[Any], *, prefer_pick: bool) -> list[Any]:
    if not devices:
        print("No devices to select.", file=sys.stderr)
        raise SystemExit(1)

    pick_fn: Any = None
    if prefer_pick:
        try:
            from pick import pick as pick_fn  # type: ignore[import-not-found]
        except ImportError:
            pick_fn = None

    if pick_fn is not None:
        options = [f"{(d.name or '—'):<22}  {d.address}" for d in devices]
        selected = pick_fn(
            options,
            "Lovense toys — Space: toggle · Enter: confirm · Ctrl+C: cancel",
            multiselect=True,
            min_selection_count=1,
        )
        indices = sorted({idx for _, idx in selected})
        return [devices[i] for i in indices]

    _print_device_table(devices, numbered=True)
    print("\nEnter numbers of toys to test, separated by comma or space (e.g. 1,2):")
    while True:
        try:
            line = input("> ").strip()
            if not line:
                continue
            indices = _parse_index_line(line, len(devices))
            return [devices[i] for i in indices]
        except ValueError as exc:
            print(f"  {exc}. Try again.")


def _toy_is_dual_vibrate(name: str | None) -> bool:
    """Edge / Diamo-style toys expose Vibrate1 + Vibrate2 over UART."""
    n = (name or "").lower()
    return "edge" in n or "diamo" in n


async def _silence_client(client: Any, dev: Any) -> None:
    """Stop vibration; dual-motor toys get Vibrate1/2 then Vibrate."""
    if _toy_is_dual_vibrate(dev.name):
        await client.send_uart_command("Vibrate1:0")
        await client.send_uart_command("Vibrate2:0")
    await client.send_uart_command("Vibrate:0")


async def _silence_all(clients: list[Any], devices: list[Any]) -> None:
    await asyncio.gather(*(_silence_client(c, d) for c, d in zip(clients, devices, strict=True)))


def _sine_level(t: float, duration: float, phase: float = 0.0) -> int:
    if duration <= 0:
        return 0
    p = (t / duration) * 2.0 * math.pi + phase
    raw = (math.sin(p) * 0.5 + 0.5) * 20.0
    return max(0, min(20, int(round(raw))))


async def _wave_one_feature(
    client: Any,
    *,
    duration: float,
    interval: float,
    feature: str,
    phase: float = 0.0,
) -> tuple[int, float]:
    """Send feature:N; on a sine 0..20. Returns (write_count, elapsed_monotonic)."""
    t0 = time.monotonic()
    writes = 0
    while True:
        now = time.monotonic() - t0
        if now >= duration:
            break
        level = _sine_level(now, duration, phase)
        await client.send_uart_command(f"{feature}:{level}")
        writes += 1
        await asyncio.sleep(interval)
    return writes, time.monotonic() - t0


async def _wave_per_toy(
    clients: list[Any],
    devices: list[Any],
    labels: list[str],
    *,
    duration: float,
    interval: float,
) -> None:
    print("\n--- Wave: one toy at a time (others silenced) ---")
    for i, c in enumerate(clients):
        await _silence_all(clients, devices)
        print(f"  → {labels[i]}  Vibrate sine, {duration:.1f}s, step {interval*1000:.0f}ms")
        n, elapsed = await _wave_one_feature(c, duration=duration, interval=interval, feature="Vibrate")
        rate = f"{n / elapsed:.1f}" if elapsed > 0 else "—"
        print(f"     writes={n}  elapsed={elapsed:.2f}s  (~{rate} cmd/s)")
    await _silence_all(clients, devices)


async def _wave_per_motor(
    clients: list[Any],
    devices: list[Any],
    labels: list[str],
    *,
    duration: float,
    interval: float,
) -> None:
    print("\n--- Wave: dual motors separately (Edge/Diamo only) ---")
    for i, c in enumerate(clients):
        if not _toy_is_dual_vibrate(devices[i].name):
            print(f"  (skip {labels[i]} — single-motor name heuristic)")
            continue
        await _silence_all(clients, devices)
        print(f"  → {labels[i]}  Vibrate1 wave, Vibrate2=0")
        t0 = time.monotonic()
        w1 = 0
        while time.monotonic() - t0 < duration:
            now = time.monotonic() - t0
            v1 = _sine_level(now, duration, 0.0)
            await c.send_uart_command(f"Vibrate1:{v1}")
            await c.send_uart_command("Vibrate2:0")
            w1 += 2
            await asyncio.sleep(interval)
        print(f"     Vibrate1+Vibrate2(0) pairs ≈ {w1//2}")

        await _silence_all(clients, devices)
        print(f"  → {labels[i]}  Vibrate2 wave, Vibrate1=0")
        t0 = time.monotonic()
        w2 = 0
        while time.monotonic() - t0 < duration:
            now = time.monotonic() - t0
            v2 = _sine_level(now, duration, 0.0)
            await c.send_uart_command("Vibrate1:0")
            await c.send_uart_command(f"Vibrate2:{v2}")
            w2 += 2
            await asyncio.sleep(interval)
        print(f"     Vibrate1(0)+Vibrate2 pairs ≈ {w2//2}")

        await _silence_all(clients, devices)
        print(f"  → {labels[i]}  Vibrate1 & Vibrate2 in counter-phase (stereo check)")
        t0 = time.monotonic()
        pairs = 0
        while time.monotonic() - t0 < duration:
            now = time.monotonic() - t0
            a = _sine_level(now, duration, 0.0)
            b = _sine_level(now, duration, math.pi)
            await c.send_uart_command(f"Vibrate1:{a}")
            await c.send_uart_command(f"Vibrate2:{b}")
            pairs += 1
            await asyncio.sleep(interval)
        print(f"     dual updates={pairs}")
    await _silence_all(clients, devices)


async def _wave_all_together(
    clients: list[Any],
    devices: list[Any],
    labels: list[str],
    *,
    duration: float,
    interval: float,
) -> None:
    print("\n--- Wave: all selected toys together (Vibrate, quarter-period phase each) ---")
    await _silence_all(clients, devices)
    n = len(clients)
    t0 = time.monotonic()
    steps = 0
    while time.monotonic() - t0 < duration:
        now = time.monotonic() - t0
        tasks = []
        for j, c in enumerate(clients):
            phase = (j / max(n, 1)) * (0.5 * math.pi)
            level = _sine_level(now, duration, phase)
            tasks.append(c.send_uart_command(f"Vibrate:{level}"))
        await asyncio.gather(*tasks)
        steps += 1
        await asyncio.sleep(interval)
    print(f"  steps={steps}  toys={n}  ~{steps * n} writes")
    await _silence_all(clients, devices)


async def _scan(
    *,
    timeout: float,
    lovense_only: bool,
    name_substr: str | None,
    list_only: bool,
) -> int:
    from bleak import BleakScanner

    print(f"Scanning {timeout:.1f}s… (wake the toys if they sleep)\n")
    devices = await BleakScanner.discover(timeout=timeout)
    filtered = _filter_devices(devices, lovense_only=lovense_only, name_substr=name_substr)

    if not filtered:
        hint = " Try --all to see every BLE device." if lovense_only else ""
        print(f"No devices matched.{hint}")
        return 1

    _print_device_table(filtered, numbered=False)
    if list_only:
        print(
            f"\nRun without --scan to pick toys interactively, or:\n"
            f"  python {sys.argv[0]} <ADDR1> <ADDR2> ...\n"
        )
    return 0


async def _drive_many(
    selected: list[Any],
    *,
    run_pulse: bool = True,
    wave: bool = False,
    wave_seconds: float = 8.0,
    wave_interval: float = 0.05,
) -> int:
    from lovensepy.ble_direct import BleDirectClient

    clients = [BleDirectClient(d.address) for d in selected]
    labels = [f"{(d.name or '?')} ({d.address})" for d in selected]

    print("Connecting…")
    await asyncio.gather(*(c.connect() for c in clients))
    for i, c in enumerate(clients):
        print(f"  OK {labels[i]}  TX {c.uart_tx_uuid!r}")

    try:
        if run_pulse:
            levels = [min(20, 6 + (j * 4) % 15) for j in range(len(clients))]
            print(f"Vibrate levels {levels} for 2s…")
            await asyncio.gather(*(c.set_vibration(levels[i]) for i, c in enumerate(clients)))
            await asyncio.sleep(2.0)
            print("Stop all…")
            await asyncio.gather(*(c.set_vibration(0) for c in clients))

        if wave:
            if wave_seconds <= 0 or wave_interval <= 0:
                raise LovenseBLEError("--wave-seconds and --wave-interval must be positive")
            await _wave_per_toy(
                clients, selected, labels, duration=wave_seconds, interval=wave_interval
            )
            await _wave_per_motor(
                clients, selected, labels, duration=wave_seconds, interval=wave_interval
            )
            await _wave_all_together(
                clients, selected, labels, duration=wave_seconds, interval=wave_interval
            )
            print("\nWave tests finished (listen/feel for dropouts; UART has no RX here).")
    finally:
        try:
            await _silence_all(clients, selected)
        except Exception:
            pass
        await asyncio.gather(*(c.disconnect() for c in clients), return_exceptions=True)
    print("Done.")
    return 0


async def _interactive_main(
    *,
    timeout: float,
    lovense_only: bool,
    name_substr: str | None,
    prefer_pick: bool,
    run_pulse: bool = True,
    wave: bool = False,
    wave_seconds: float = 8.0,
    wave_interval: float = 0.05,
) -> int:
    from bleak import BleakScanner

    print(f"Scanning {timeout:.1f}s… (Lovense: names starting with LVS-)\n")
    devices = await BleakScanner.discover(timeout=timeout)
    filtered = _filter_devices(devices, lovense_only=lovense_only, name_substr=name_substr)

    if not filtered:
        hint = " Try --all if your toys use another advertisement name." if lovense_only else ""
        print(f"No matching devices.{hint}")
        return 1

    chosen = _select_devices_interactive(filtered, prefer_pick=prefer_pick)
    print()
    return await _drive_many(
        chosen,
        run_pulse=run_pulse,
        wave=wave,
        wave_seconds=wave_seconds,
        wave_interval=wave_interval,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="BLE: scan, pick LVS-* Lovense toys, run BleDirectClient test pattern",
    )
    parser.add_argument(
        "--scan",
        action="store_true",
        help="Only list devices (no connection)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=8.0,
        help="Scan duration in seconds (default: 8)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="show_all",
        help="Include non-Lovense BLE devices (no LVS- name filter)",
    )
    parser.add_argument(
        "--filter",
        dest="name_substr",
        metavar="SUBSTR",
        help="Additional filter: advertised name must contain this substring (case-insensitive)",
    )
    parser.add_argument(
        "--no-tui",
        action="store_true",
        help="Do not use the optional 'pick' TUI; type device numbers instead",
    )
    parser.add_argument(
        "addresses",
        nargs="*",
        metavar="ADDR",
        help="BLE addresses (skip scan/menu if provided)",
    )
    parser.add_argument(
        "--wave",
        action="store_true",
        help="After the pulse (unless --no-pulse), run sine-wave tests per toy, per motor, then all together",
    )
    parser.add_argument(
        "--no-pulse",
        action="store_true",
        help="Skip the 2s constant-level test (use with --wave)",
    )
    parser.add_argument(
        "--wave-seconds",
        type=float,
        default=8.0,
        metavar="SEC",
        help="Duration of each wave segment (default: 8)",
    )
    parser.add_argument(
        "--wave-interval",
        type=float,
        default=0.05,
        metavar="SEC",
        help="Delay between UART updates (default: 0.05 ≈ 20 Hz)",
    )
    args = parser.parse_args()

    lovense_only = not args.show_all
    run_pulse = not args.no_pulse
    if args.no_pulse and not args.wave:
        parser.error("--no-pulse requires --wave (otherwise nothing would run)")

    try:
        if args.scan:
            code = asyncio.run(
                _scan(
                    timeout=args.timeout,
                    lovense_only=lovense_only,
                    name_substr=args.name_substr,
                    list_only=True,
                )
            )
            raise SystemExit(code)

        if args.addresses:
            from types import SimpleNamespace

            selected = [SimpleNamespace(address=a, name=None) for a in args.addresses]
            code = asyncio.run(
                _drive_many(
                    selected,
                    run_pulse=run_pulse,
                    wave=args.wave,
                    wave_seconds=args.wave_seconds,
                    wave_interval=args.wave_interval,
                )
            )
            raise SystemExit(code)

        code = asyncio.run(
            _interactive_main(
                timeout=args.timeout,
                lovense_only=lovense_only,
                name_substr=args.name_substr,
                prefer_pick=not args.no_tui,
                run_pulse=run_pulse,
                wave=args.wave,
                wave_seconds=args.wave_seconds,
                wave_interval=args.wave_interval,
            )
        )
        raise SystemExit(code)
    except (LovenseBLEError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
