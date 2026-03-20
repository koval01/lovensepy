"""Integration tests for Toy Events API (Lovense Remote)."""

import os
from typing import Any

import pytest

from tests.conftest import requires_lan
from tests.helpers.toy_events_helpers import collect_toy_events

LOVENSE_CONNECT_PORT = 34567
HANDSHAKE_EVENTS = {"access-granted", "toy-list"}


def _log(msg: str) -> None:
    print(msg, flush=True)


def _toy_events_endpoint_from_env() -> tuple[str, int]:
    ip = os.environ["LOVENSE_LAN_IP"]
    port = int(
        os.environ.get("LOVENSE_TOY_EVENTS_PORT") or os.environ.get("LOVENSE_LAN_PORT", "20011")
    )
    return ip, port


def _skip_if_invalid_port(port: int) -> None:
    if port == LOVENSE_CONNECT_PORT:
        pytest.skip("Toy Events API exists only in Lovense Remote (20011), not Lovense Connect")


async def _collect(
    *,
    app_name: str,
    duration_sec: float,
    intro: str,
) -> tuple[list[tuple[str, Any]], bool]:
    ip, port = _toy_events_endpoint_from_env()
    _skip_if_invalid_port(port)
    _log(intro)
    events, access_granted, connect_error = await collect_toy_events(
        ip,
        port,
        app_name=app_name,
        duration_sec=duration_sec,
        log_fn=_log,
    )
    if connect_error is not None:
        pytest.skip(f"Toy Events connection failed: {connect_error}")
    return events, access_granted


@requires_lan
@pytest.mark.anyio
async def test_toy_events_connect_and_events():
    events, access_granted = await _collect(
        app_name="lovensepy_test",
        duration_sec=10,
        intro="Connecting to Toy Events WebSocket...",
    )
    assert events, "No events received. Enable Game Mode and grant access in Lovense Remote"
    assert access_granted, "Access not granted in Lovense Remote"


@requires_lan
@pytest.mark.anyio
async def test_toy_events_interactive():
    events, access_granted = await _collect(
        app_name="lovensepy_events_test",
        duration_sec=30,
        intro="Listening for interactive Toy Events (30s)...",
    )
    if not access_granted:
        pytest.skip("Toy Events access was not granted in Lovense Remote")

    event_types = {event_type for event_type, _payload in events}
    if not (event_types - HANDSHAKE_EVENTS):
        pytest.skip("No interactive Toy Events received (unsupported toys or no interaction)")
