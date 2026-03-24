"""
WebSocket transport: raw connection, send, receive.

Protocol-agnostic. Clients layer Engine.IO, Toy Events, etc. on top.
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import aiohttp
from aiohttp import WSMsgType

__all__ = ["WsTransport"]


async def _close_transport(
    session: aiohttp.ClientSession | None,
    ws: aiohttp.ClientWebSocketResponse | None,
) -> None:
    if ws is not None and not ws.closed:
        try:
            await ws.close()
        except (OSError, aiohttp.ClientError):
            pass
    if session is not None and not session.closed:
        try:
            await session.close()
        except (OSError, aiohttp.ClientError):
            pass


def _is_open(ws: Any) -> bool:
    """True if aiohttp client WebSocket is connected."""
    if ws is None:
        return False
    closed = getattr(ws, "closed", True)
    return not bool(closed)


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
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._send_lock = asyncio.Lock()

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
        session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(sock_connect=self._open_timeout),
        )
        try:
            ws = await session.ws_connect(
                self._url,
                headers=self._headers or None,
                timeout=aiohttp.ClientWSTimeout(
                    ws_close=self._close_timeout,
                    ws_receive=None,
                ),
                autoping=True,
            )
        except (
            OSError,
            TimeoutError,
            aiohttp.ClientError,
            aiohttp.WSServerHandshakeError,
        ):
            await session.close()
            return False

        self._session = session
        self._ws = ws
        return True

    async def send(self, message: str) -> bool:
        """Send text message. Returns False if not connected or send failed.

        aiohttp (like most asyncio WS clients) must not interleave concurrent ``send_str``
        calls; SocketAPIClient may schedule many sends via ``create_task``, and the ping
        loop runs in parallel, so all writes go through this lock.
        """
        async with self._send_lock:
            ws = self._ws
            if not _is_open(ws):
                return False
            try:
                await ws.send_str(message)
                return True
            except (OSError, TypeError, aiohttp.ClientError, ConnectionResetError):
                return False

    async def receive(self) -> AsyncIterator[str]:
        """Async iterator of received text messages."""
        # Hold the socket for the whole loop: disconnect() clears ``self._ws`` while the
        # recv task may still be running (websockets ``async for`` kept the same behavior).
        ws = self._ws
        if not ws:
            return
        try:
            while True:
                msg = await ws.receive()
                if msg.type == WSMsgType.TEXT:
                    yield msg.data
                elif msg.type == WSMsgType.BINARY:
                    yield msg.data.decode("utf-8")
                elif msg.type in (
                    WSMsgType.CLOSE,
                    WSMsgType.CLOSING,
                    WSMsgType.CLOSED,
                    WSMsgType.ERROR,
                ):
                    break
        except asyncio.CancelledError:
            raise
        except (OSError, aiohttp.ClientError):
            pass

    def close(self) -> None:
        """Close connection.

        With a running event loop, schedules an async close. Without one (e.g. sync
        teardown), runs a short ``asyncio.run`` close so the socket is not left open
        until GC.
        """
        session = self._session
        ws = self._ws
        self._session = None
        self._ws = None
        if session is None and ws is None:
            return
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(lambda: asyncio.create_task(_close_transport(session, ws)))
        except RuntimeError:
            try:
                asyncio.run(_close_transport(session, ws))
            except RuntimeError:
                # Nested event-loop edge case; best-effort only.
                pass
