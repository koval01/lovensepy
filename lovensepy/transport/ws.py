"""
WebSocket transport: raw connection, send, receive.

Protocol-agnostic. Clients layer Engine.IO, Toy Events, etc. on top.
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed, InvalidState, WebSocketException

try:
    from websockets.protocol import State

    OPEN = State.OPEN
except ImportError:
    from websockets.protocol import OPEN

__all__ = ["WsTransport"]


async def _close_ws(ws: Any) -> None:
    try:
        await ws.close()
    except (OSError, WebSocketException, ConnectionClosed, InvalidState):
        pass


def _is_open(ws: Any) -> bool:
    """Check if WebSocket is open. Compatible with websockets 12 and 16+."""
    if ws is None:
        return False
    if hasattr(ws, "open"):
        return bool(ws.open)
    return getattr(ws, "state", None) is OPEN


class WsTransport:
    """
    Raw WebSocket transport: connect, send, receive.

    No protocol logic. Clients handle handshake, ping, message format.
    """

    def __init__(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        open_timeout: float = 30.0,
        close_timeout: float = 5.0,
    ) -> None:
        self._url = url
        self._headers = headers or {}
        self._open_timeout = open_timeout
        self._close_timeout = close_timeout
        self._ws: Any | None = None

    @property
    def url(self) -> str:
        """WebSocket URL."""
        return self._url

    @property
    def is_connected(self) -> bool:
        """True if WebSocket is open."""
        return _is_open(self._ws)

    async def connect(self) -> bool:
        """
        Connect to WebSocket. Returns True on success, False on error.
        """
        self.close()
        try:
            self._ws = await websockets.connect(
                self._url,
                additional_headers=self._headers,
                ping_interval=None,
                ping_timeout=None,
                close_timeout=self._close_timeout,
                open_timeout=self._open_timeout,
            )
            return True
        except (OSError, WebSocketException):
            self._ws = None
            return False

    async def send(self, message: str) -> bool:
        """Send text message. Returns False if not connected or send failed."""
        if not _is_open(self._ws):
            return False
        try:
            await self._ws.send(message)
            return True
        except (OSError, ConnectionClosed, InvalidState):
            return False

    async def receive(self) -> AsyncIterator[str]:
        """Async iterator of received text messages."""
        if not self._ws:
            return
        try:
            async for msg in self._ws:
                if isinstance(msg, bytes):
                    msg = msg.decode("utf-8")
                yield msg
        except websockets.ConnectionClosed:
            pass

    def close(self) -> None:
        """Close connection.

        With a running event loop, schedules an async close. Without one (e.g. sync
        teardown), runs a short ``asyncio.run`` close so the socket is not left open
        until GC.
        """
        ws = self._ws
        self._ws = None
        if ws and _is_open(ws):
            try:
                loop = asyncio.get_running_loop()
                loop.call_soon_threadsafe(lambda: asyncio.create_task(_close_ws(ws)))
            except RuntimeError:
                try:
                    asyncio.run(_close_ws(ws))
                except RuntimeError:
                    # Nested event-loop edge case; best-effort only.
                    pass
