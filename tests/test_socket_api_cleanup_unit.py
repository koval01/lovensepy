"""Tests for :class:`SocketAPIClient` cleanup when no event loop is running."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from lovensepy.socket_api.client import SocketAPIClient, _close_async_lan_client


def test_close_async_lan_client_from_sync_context() -> None:
    lan = MagicMock()
    lan.aclose = AsyncMock()
    _close_async_lan_client(lan)
    lan.aclose.assert_awaited_once()


def test_socket_disconnect_closes_lan_when_no_loop() -> None:
    client = SocketAPIClient("ws://example.invalid")
    lan = MagicMock()
    lan.aclose = AsyncMock()
    client._lan_client = lan

    client.disconnect()

    lan.aclose.assert_awaited_once()
    assert client._lan_client is None


@pytest.mark.asyncio
async def test_close_async_lan_client_from_running_loop() -> None:
    lan = MagicMock()
    lan.aclose = AsyncMock()
    _close_async_lan_client(lan)
    await asyncio.sleep(0)
    lan.aclose.assert_awaited_once()
