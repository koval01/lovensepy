"""
Tests for Socket API — server (WebSocket, QR flow).

Run: LOVENSE_DEV_TOKEN=... LOVENSE_UID=... LOVENSE_PLATFORM="..." \\
    pytest tests/test_socket.py -v -s

LOVENSE_PLATFORM must match the Website Name from your Lovense Developer Dashboard.
For interactive (QR scan) tests, do NOT set LOVENSE_SKIP_INTERACTIVE.
"""

import asyncio
import os

import pytest

from lovensepy import (
    build_websocket_url,
    features_for_toy,
    get_socket_url,
    get_token,
)
from tests.conftest import requires_interactive, requires_socket
from tests.helpers.socket_scenarios import run_socket_function_demo
from tests.helpers.socket_session import socket_session


@pytest.fixture
def auth_token():
    """Get auth token from developer token and uid."""
    token = os.environ.get("LOVENSE_DEV_TOKEN")
    uid = os.environ.get("LOVENSE_UID", "test_user_lovensepy")
    if not token:
        pytest.skip("LOVENSE_DEV_TOKEN required")
    return get_token(token, uid, uname=f"user_{uid[:8]}")


@pytest.fixture
def ws_url(auth_token):
    """Build WebSocket URL. LOVENSE_PLATFORM must match Lovense Developer Dashboard."""
    platform = os.environ.get("LOVENSE_PLATFORM")
    if not platform:
        pytest.skip("LOVENSE_PLATFORM required (Website Name from Lovense Developer Dashboard)")
    info = get_socket_url(auth_token, platform)
    return build_websocket_url(info, auth_token)


def test_get_token(auth_token):
    """get_token returns non-empty auth token."""
    assert auth_token
    assert len(auth_token) > 10


def test_get_socket_url(auth_token):
    """get_socket_url returns socket info. Requires LOVENSE_PLATFORM."""
    platform = os.environ.get("LOVENSE_PLATFORM")
    if not platform:
        pytest.skip("LOVENSE_PLATFORM required")
    info = get_socket_url(auth_token, platform)
    assert "socketIoUrl" in info or "socketIoPath" in info


def test_build_websocket_url(auth_token):
    """build_websocket_url produces wss URL. Requires LOVENSE_PLATFORM."""
    platform = os.environ.get("LOVENSE_PLATFORM")
    if not platform:
        pytest.skip("LOVENSE_PLATFORM required")
    info = get_socket_url(auth_token, platform)
    url = build_websocket_url(info, auth_token)
    assert url.startswith("wss://")
    assert "EIO=3" in url
    assert "transport=websocket" in url


def _log(msg: str) -> None:
    print(msg, flush=True)


@pytest.mark.asyncio
@requires_socket
@requires_interactive
async def test_full_flow(ws_url):
    """
    Full Socket API flow: connect, show QR, wait for scan, verify toys, send command.

    You MUST scan the QR code with Lovense Remote app. LAN IP is NOT needed for Socket API.
    """
    async with socket_session(
        ws_url,
        use_local_commands=False,
        app_name="lovensepy_test",
        log_fn=_log,
    ) as (client, toys):
        _log(f">>> Detected {len(toys)} toy(s):")
        for tid, toy in toys.items():
            name = toy.get("name") or "—"
            model = toy.get("toyType") or toy.get("name") or "—"
            _log(f"    {tid}: {name} ({model}) — {features_for_toy(toy)}")
        await run_socket_function_demo(client, toys, log_fn=_log)


@pytest.mark.asyncio
@requires_socket
@requires_interactive
async def test_by_local(ws_url):
    """
    Socket API by local: QR flow + commands via HTTPS to device (same LAN).

    Same as full flow but use_local_commands=True. Phone and test machine must be on same network.
    """
    async with socket_session(
        ws_url,
        use_local_commands=True,
        app_name="lovensepy_by_local",
        log_fn=_log,
    ) as (client, toys):
        assert client.is_using_local_commands, (
            "Expected is_using_local_commands — device must be on same LAN as test machine"
        )
        _log(f">>> By local: {len(toys)} toy(s), commands via HTTPS to device")
        toy_id = next(iter(toys.keys()))
        _log(f"Sending Vibrate:5 to {toy_id} for 3s (via local HTTPS)...")
        client.send_command("Function", "Vibrate:5", time_sec=3, toy=toy_id)
        await asyncio.sleep(3.5)
        await client.send_command_await("Function", "Stop", time_sec=0, toy=toy_id)
        _log(">>> Done.")
