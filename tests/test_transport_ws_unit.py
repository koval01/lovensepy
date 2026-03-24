"""Tests for :class:`lovensepy.transport.ws.WsTransport` lifecycle."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from lovensepy.transport.ws import WsTransport


def test_ws_transport_close_uses_asyncio_run_when_no_loop() -> None:
    """Closing without a running loop should still await ``ws.close()``."""
    transport = WsTransport("ws://example.invalid")
    close_coro = AsyncMock()
    transport._ws = SimpleNamespace(closed=False, close=close_coro)
    transport._session = None

    transport.close()

    close_coro.assert_awaited_once()


def test_ws_transport_close_schedules_task_when_loop_running() -> None:
    async def _runner() -> None:
        transport = WsTransport("ws://example.invalid")
        close_coro = AsyncMock()
        transport._ws = SimpleNamespace(closed=False, close=close_coro)
        transport._session = None

        transport.close()
        await asyncio.sleep(0.05)
        close_coro.assert_awaited_once()

    asyncio.run(_runner())
