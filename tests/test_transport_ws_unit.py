"""Tests for :class:`lovensepy.transport.ws.WsTransport` lifecycle."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from lovensepy.transport.ws import WsTransport


def test_ws_transport_close_uses_asyncio_run_when_no_loop() -> None:
    """Closing without a running loop should still await ``ws.close()``."""
    transport = WsTransport("ws://example.invalid")
    mock_ws = MagicMock()
    mock_ws.open = True
    close_coro = AsyncMock()
    mock_ws.close = close_coro
    transport._ws = mock_ws

    transport.close()

    close_coro.assert_awaited_once()


def test_ws_transport_close_schedules_task_when_loop_running() -> None:
    async def _runner() -> None:
        transport = WsTransport("ws://example.invalid")
        mock_ws = MagicMock()
        mock_ws.open = True
        close_coro = AsyncMock()
        mock_ws.close = close_coro
        transport._ws = mock_ws

        transport.close()
        await asyncio.sleep(0.05)
        close_coro.assert_awaited_once()

    asyncio.run(_runner())
