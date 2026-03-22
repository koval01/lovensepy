"""
Single-entry test runner for full lovensepy validation.

Usage:
    python -m tests.run_all
    python -m tests.run_all --stop-on-fail
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Phase:
    name: str
    targets: tuple[str, ...]
    extra_args: tuple[str, ...] = ()


PHASES: tuple[Phase, ...] = (
    Phase("Unit", ("tests/test_unit.py",)),
    Phase("Async transports/client unit", ("tests/test_async_clients.py",)),
    Phase("Socket client unit", ("tests/test_socket_client_unit.py",)),
    Phase("Home Assistant MQTT unit", ("tests/test_home_assistant_mqtt_unit.py",)),
    Phase(
        "BLE / UART / transport unit (no devices)",
        (
            "tests/test_ble_direct_unit.py",
            "tests/test_ble_direct_hub_unit.py",
            "tests/test_ble_direct_sync_hub_unit.py",
            "tests/test_uart_replies.py",
            "tests/test_ble_uart_catalog.py",
            "tests/test_transport_ws_unit.py",
            "tests/test_socket_api_cleanup_unit.py",
        ),
    ),
    Phase("LAN integration", ("tests/test_local.py",), ("-s",)),
    Phase("Toy events integration", ("tests/test_toy_events.py",), ("-s",)),
    Phase("Socket integration", ("tests/test_socket.py",), ("-s",)),
    Phase("Server integration", ("tests/test_standard_server.py",), ("-s",)),
    Phase(
        "Connection methods sequential",
        ("tests/test_connection_methods_sequential.py",),
        ("-s",),
    ),
    Phase("BLE integration (hardware)", ("tests/test_ble_direct_integration.py",), ("-s",)),
)


def _run_phase(phase: Phase, pytest_args: list[str]) -> int:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *phase.targets,
        "-v",
        *phase.extra_args,
        *pytest_args,
    ]
    print(f"\n=== [{phase.name}] ===")
    print(" ".join(cmd), flush=True)
    return subprocess.run(cmd, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Run full lovensepy test suite in fixed order.")
    parser.add_argument(
        "--stop-on-fail",
        action="store_true",
        help="Stop immediately when a phase fails.",
    )
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Additional args forwarded to pytest (use after `--`, e.g. -- -x --maxfail=1).",
    )
    args = parser.parse_args()

    failures: list[tuple[str, int]] = []
    for phase in PHASES:
        forwarded = [arg for arg in args.pytest_args if arg != "--"]
        rc = _run_phase(phase, forwarded)
        if rc != 0:
            failures.append((phase.name, rc))
            if args.stop_on_fail:
                break

    print("\n=== Full suite summary ===")
    if not failures:
        print("All phases passed.")
        return 0

    for name, rc in failures:
        print(f"- {name}: failed (exit code {rc})")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
