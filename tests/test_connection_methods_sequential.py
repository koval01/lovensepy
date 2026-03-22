"""
Run integration checks for each connection path in a fixed order (see test names).

This file is meant for manual or CI hardware runs: each step is independent and
skips when required env vars are missing.

Typical full run (LAN + server + Socket URL + Toy Events; QR steps optional):

  export LOVENSE_LAN_IP=...
  export LOVENSE_LAN_PORT=20011
  export LOVENSE_DEV_TOKEN=...
  export LOVENSE_UID=...
  export LOVENSE_PLATFORM=\"Your Website Name\"
  pytest tests/test_connection_methods_sequential.py -v -s

Interactive Socket (QR scan) also needs LOVENSE_SKIP_INTERACTIVE unset.

Direct BLE: pip install 'lovensepy[ble]'; optional LOVENSE_BLE_SCAN_TIMEOUT, LOVENSE_BLE_STEP_SEC

Order: Standard LAN → Async LAN → Standard Server → Async Server → Socket URL smoke
→ Toy Events → Socket WebSocket (cloud) → Socket by local → Direct BLE.
"""

from __future__ import annotations

import os

import pytest

from lovensepy import (
    AsyncLANClient,
    AsyncServerClient,
    LANClient,
    ServerClient,
    build_websocket_url,
    get_socket_url,
    get_token,
)
from lovensepy.exceptions import LovenseError
from tests.conftest import (
    requires_interactive,
    requires_lan,
    requires_platform,
    requires_server_uid,
    requires_socket,
)
from tests.helpers.ble_integration_scenario import run_ble_discovery_exercise
from tests.helpers.socket_scenarios import run_socket_function_demo
from tests.helpers.socket_session import socket_session
from tests.helpers.test_utils import assert_has_code, call_or_skip
from tests.helpers.toy_events_helpers import collect_toy_events


def _log(msg: str) -> None:
    print(msg, flush=True)


async def _call_or_skip_async(coro):
    try:
        return await coro
    except LovenseError as exc:
        pytest.skip(f"Network error: {exc}")


def _lan_client() -> LANClient:
    ip = os.environ["LOVENSE_LAN_IP"]
    port = int(os.environ.get("LOVENSE_LAN_PORT", "20011"))
    return LANClient("lovensepy_sequential", ip, port=port)


def _async_lan_client() -> AsyncLANClient:
    ip = os.environ["LOVENSE_LAN_IP"]
    port = int(os.environ.get("LOVENSE_LAN_PORT", "20011"))
    return AsyncLANClient("lovensepy_sequential_async", ip, port=port)


def _server_clients() -> tuple[str, str]:
    token = os.environ["LOVENSE_DEV_TOKEN"]
    uid = os.environ["LOVENSE_UID"]
    return token, uid


@requires_lan
def test_01_standard_lan_get_toys():
    """Standard API — local (Game Mode HTTP)."""
    client = _lan_client()
    resp = call_or_skip(client.get_toys)
    assert_has_code(resp)
    _log(">>> [1/9] Standard LAN: get_toys OK")


@requires_lan
@pytest.mark.asyncio
async def test_02_async_lan_get_toys():
    """Standard API — async local."""
    client = _async_lan_client()
    async with client:
        resp = await _call_or_skip_async(client.get_toys())
    assert_has_code(resp)
    _log(">>> [2/9] Async LAN: get_toys OK")


@requires_server_uid
def test_03_standard_server_stop():
    """Standard API — server (HTTPS to Lovense cloud)."""
    token, uid = _server_clients()
    client = ServerClient(token, uid)
    resp = call_or_skip(client.stop)
    assert_has_code(resp)
    _log(">>> [3/9] Standard Server: stop OK")


@requires_server_uid
@pytest.mark.asyncio
async def test_04_async_server_stop():
    """Standard API — async server."""
    token, uid = _server_clients()
    async with AsyncServerClient(token, uid) as client:
        resp = await _call_or_skip_async(client.stop())
    assert_has_code(resp)
    _log(">>> [4/9] Async Server: stop OK")


@requires_socket
@requires_platform
def test_05_socket_get_url_smoke():
    """Socket API — token + getSocketUrl + WebSocket URL (no live WebSocket)."""
    token = get_token(
        os.environ["LOVENSE_DEV_TOKEN"],
        os.environ.get("LOVENSE_UID", "test_user_lovensepy"),
        uname="user_seq",
    )
    info = get_socket_url(token, os.environ["LOVENSE_PLATFORM"])
    url = build_websocket_url(info, token)
    assert url.startswith("wss://")
    _log(">>> [5/9] Socket URL smoke: OK")


@requires_lan
@pytest.mark.asyncio
async def test_06_toy_events_short_listen():
    """Toy Events — WebSocket to Lovense Remote (short listen)."""
    ip = os.environ["LOVENSE_LAN_IP"]
    port = int(
        os.environ.get("LOVENSE_TOY_EVENTS_PORT") or os.environ.get("LOVENSE_LAN_PORT", "20011")
    )
    if port == 34567:
        pytest.skip("Toy Events exists only on Lovense Remote (port 20011), not Connect")

    events, _access, connect_error = await collect_toy_events(
        ip,
        port,
        app_name="lovensepy_sequential",
        duration_sec=5.0,
        log_fn=_log,
    )
    if connect_error is not None:
        pytest.skip(f"Toy Events connection failed: {connect_error}")
    if not events:
        pytest.skip("No Toy Events in window — grant access in Lovense Remote")
    _log(">>> [6/9] Toy Events: received events OK")


@pytest.mark.asyncio
@requires_socket
@requires_platform
@requires_interactive
async def test_07_socket_session_cloud():
    """Socket API — WebSocket + QR; commands via cloud."""
    token = get_token(
        os.environ["LOVENSE_DEV_TOKEN"],
        os.environ.get("LOVENSE_UID", "test_user_lovensepy"),
        uname="user_seq_socket",
    )
    info = get_socket_url(token, os.environ["LOVENSE_PLATFORM"])
    ws_url = build_websocket_url(info, token)

    async with socket_session(
        ws_url,
        use_local_commands=False,
        app_name="lovensepy_seq_cloud",
        log_fn=_log,
    ) as (client, toys):
        assert toys, "Scan QR and wait until toys appear in Lovense Remote"
        await run_socket_function_demo(client, toys, log_fn=_log)
    _log(">>> [7/9] Socket (cloud commands): OK")


@pytest.mark.asyncio
@requires_lan
@requires_socket
@requires_platform
@requires_interactive
async def test_08_socket_session_by_local():
    """Socket API — WebSocket + QR; commands via HTTPS to app on LAN."""
    token = get_token(
        os.environ["LOVENSE_DEV_TOKEN"],
        os.environ.get("LOVENSE_UID", "test_user_lovensepy"),
        uname="user_seq_local",
    )
    info = get_socket_url(token, os.environ["LOVENSE_PLATFORM"])
    ws_url = build_websocket_url(info, token)

    async with socket_session(
        ws_url,
        use_local_commands=True,
        app_name="lovensepy_seq_by_local",
        log_fn=_log,
    ) as (client, toys):
        assert client.is_using_local_commands
        assert toys
        await run_socket_function_demo(client, toys, log_fn=_log)
    _log(">>> [8/9] Socket (local HTTPS commands): OK")


@pytest.mark.asyncio
async def test_09_direct_ble_connect_disconnect():
    """Direct BLE — scan LVS-*, connect all, exercise (see ble_integration_scenario)."""
    pytest.importorskip("bleak")
    n = await run_ble_discovery_exercise(log=_log)
    if n == 0:
        pytest.skip("No LVS-* devices — disconnect Lovense app from toys and retry")
    _log(">>> [9/9] Direct BLE: OK")
