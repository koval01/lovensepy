"""
Standard Socket API: async WebSocket client with Engine.IO.

Business logic: Engine.IO protocol, event handling, command building.
Transport: WsTransport (lovensepy.transport).
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from .._http_identity import user_agent_string
from ..exceptions import LovenseDeviceOfflineError, LovenseError
from ..standard.async_lan import AsyncLANClient
from ..transport import WsTransport
from .events import (
    BASICAPI_SEND_TOY_COMMAND_TS,
    BASICAPI_UPDATE_DEVICE_INFO_TC,
)

PING_INTERVAL = 20.0  # seconds
_logger = logging.getLogger(__name__)


def _close_async_lan_client(lan: AsyncLANClient | None) -> None:
    """Close ``AsyncLANClient`` whether or not an event loop is running."""
    if lan is None:
        return
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(lan.aclose())
    except RuntimeError:
        asyncio.run(lan.aclose())


class SocketAPIClient:
    """
    Async Lovense Socket API client.

    Engine.IO protocol over WsTransport. With use_local_commands=True and device
    on same LAN, sends commands via HTTPS (AsyncLANClient) instead of WebSocket.
    """

    def __init__(
        self,
        ws_url: str,
        *,
        use_local_commands: bool = False,
        app_name: str = "lovensepy",
        raise_on_disconnect: bool = False,
        on_socket_open: Callable[[], Awaitable[None] | None] | None = None,
        on_socket_close: Callable[[], Awaitable[None] | None] | None = None,
        on_socket_error: Callable[[Exception], Awaitable[None] | None] | None = None,
        on_socket_io_connected: Callable[[], Awaitable[None] | None] | None = None,
        on_event: Callable[[str, Any], Awaitable[None] | None] | None = None,
    ) -> None:
        self._transport = WsTransport(
            ws_url,
            headers={
                "Origin": "http://localhost:3000",
                "User-Agent": user_agent_string(),
            },
            open_timeout=30,
        )
        self._use_local_commands = use_local_commands
        self._app_name = app_name
        self._raise_on_disconnect = raise_on_disconnect
        self._lan_client: AsyncLANClient | None = None
        self._on_open = on_socket_open
        self._on_close = on_socket_close
        self._on_error = on_socket_error
        self._on_connected = on_socket_io_connected
        self._on_event = on_event
        self._event_handlers: dict[str, list[Callable[[Any], Awaitable[None] | None]]] = {}
        self._callback_tasks: set[asyncio.Task] = set()
        self._socket_io_connected = False
        self._ping_task: asyncio.Task | None = None
        self._recv_task: asyncio.Task | None = None
        self._runner_task: asyncio.Task | None = None
        self._stop_requested = False
        self._closed = asyncio.Event()
        self._closed.set()

    @property
    def is_socket_io_connected(self) -> bool:
        """True when Socket.IO handshake is complete and ready for commands."""
        return self._socket_io_connected

    @property
    def is_using_local_commands(self) -> bool:
        """True when commands are sent via local HTTPS (LAN) instead of WebSocket."""
        return self._lan_client is not None

    def on(self, event_name: str) -> Callable[[Callable[[Any], Awaitable[None] | None]], Callable]:
        """Decorator to subscribe a handler for a specific event name."""

        def decorator(func: Callable[[Any], Awaitable[None] | None]) -> Callable:
            self._event_handlers.setdefault(event_name, []).append(func)
            return func

        return decorator

    def add_event_handler(
        self, event_name: str, handler: Callable[[Any], Awaitable[None] | None]
    ) -> None:
        """Register an event handler programmatically."""
        self._event_handlers.setdefault(event_name, []).append(handler)

    async def connect(self) -> None:
        """Connect and start background ping/receive tasks.

        This method is non-blocking after startup. To block until disconnect, use
        ``run_forever()``.
        """
        self.disconnect()
        self._stop_requested = False
        ok = await asyncio.wait_for(self._transport.connect(), timeout=35)
        if not ok:
            if self._on_error:
                cb = self._on_error(ConnectionError("WebSocket connect failed"))
                if asyncio.iscoroutine(cb):
                    await cb
            return

        if self._on_open:
            cb = self._on_open()
            if asyncio.iscoroutine(cb):
                await cb

        # Engine.IO handshake
        await self._transport.send("2probe")

        self._closed.clear()
        self._ping_task = asyncio.create_task(self._ping_loop())
        self._recv_task = asyncio.create_task(self._recv_loop())
        self._runner_task = asyncio.create_task(self._run_connection())

    async def run_forever(self) -> None:
        """Connect and block until disconnected."""
        await self.connect()
        try:
            await self.wait_closed()
        except asyncio.CancelledError:
            # If the caller cancels the task (common in 24/7 bot shutdown),
            # ensure we close the websocket + background tasks.
            self.disconnect()
            raise

    def start_background(
        self,
        *,
        auto_reconnect: bool = False,
        retry_delay: float = 5.0,
    ) -> asyncio.Task:
        """Start the client in background and return the task."""
        loop = asyncio.get_running_loop()
        if auto_reconnect:
            return loop.create_task(self.connect_with_retry(retry_delay=retry_delay))
        return loop.create_task(self.run_forever())

    async def connect_with_retry(
        self,
        *,
        retry_delay: float = 5.0,
        max_retries: int | None = None,
    ) -> None:
        """Keep connection alive with reconnect loop.

        Stops when ``disconnect()`` is called.
        """
        attempts = 0
        while not self._stop_requested:
            try:
                await self.run_forever()
            except asyncio.CancelledError:
                self.disconnect()
                raise
            except Exception as exc:  # pylint: disable=broad-exception-caught
                if self._on_error:
                    cb = self._on_error(exc)
                    if asyncio.iscoroutine(cb):
                        await cb
            if self._stop_requested:
                break
            attempts += 1
            if max_retries is not None and attempts > max_retries:
                break
            await asyncio.sleep(retry_delay)

    async def wait_closed(self) -> None:
        """Wait until current connection is fully closed."""
        await self._closed.wait()

    async def _run_connection(self) -> None:
        try:
            await asyncio.gather(self._ping_task, self._recv_task)
        except asyncio.CancelledError:
            pass
        finally:
            self._cleanup()

    def disconnect(self) -> None:
        """Close connection."""
        self._stop_requested = True
        if self._ping_task:
            self._ping_task.cancel()
            self._ping_task = None
        if self._recv_task:
            self._recv_task.cancel()
            self._recv_task = None
        if self._runner_task:
            self._runner_task.cancel()
            self._runner_task = None
        for task in list(self._callback_tasks):
            task.cancel()
        self._callback_tasks.clear()
        self._transport.close()
        self._socket_io_connected = False
        lan = self._lan_client
        self._lan_client = None
        _close_async_lan_client(lan)
        self._closed.set()

    def _cleanup(self) -> None:
        """Clean up connection. on_close callback is scheduled but not awaited."""
        self._socket_io_connected = False
        if self._ping_task:
            self._ping_task.cancel()
            self._ping_task = None
        if self._recv_task:
            self._recv_task.cancel()
            self._recv_task = None
        for task in list(self._callback_tasks):
            task.cancel()
        self._callback_tasks.clear()
        self._runner_task = None
        self._transport.close()
        lan = self._lan_client
        self._lan_client = None
        _close_async_lan_client(lan)
        if self._on_close:
            cb = self._on_close()
            if asyncio.iscoroutine(cb):
                asyncio.create_task(cb)
        self._closed.set()

    async def _ping_loop(self) -> None:
        while True:
            await asyncio.sleep(PING_INTERVAL)
            if not await self._transport.send("2"):
                break

    async def _recv_loop(self) -> None:
        async for msg in self._transport.receive():
            await self._handle_message(msg)

    async def _handle_message(self, message: str) -> None:
        # Engine.IO open packet — respond with 40
        if message.startswith("0{"):
            await self._transport.send("40")
            return
        if message == "3probe":
            await self._transport.send("5")
            return
        if message in ("3", "3probe"):
            return
        if message.startswith("40"):
            if not self._socket_io_connected:
                self._socket_io_connected = True
                if self._on_connected:
                    cb = self._on_connected()
                    if asyncio.iscoroutine(cb):
                        await cb
            return
        if not message.startswith("42"):
            return
        try:
            raw = message[2:]
            arr = json.loads(raw)
            if not isinstance(arr, list) or len(arr) < 1:
                return
            event = arr[0]
            payload = arr[1] if len(arr) >= 2 else None
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    pass
            if (
                self._use_local_commands
                and event == BASICAPI_UPDATE_DEVICE_INFO_TC
                and isinstance(payload, dict)
            ):
                domain = payload.get("domain")
                https_port = payload.get("httpsPort", 30011)
                if domain:
                    # Socket API provides a HTTPS host in `domain`, often derived from the
                    # local LAN IP (e.g. 192-168-1-10.lovense.club).
                    # For 24/7/bot usage we want local commands to work even when DNS for
                    # `lovense.club` is flaky; derive the LAN IP back and connect directly.
                    local_ip: str | None = None
                    if isinstance(domain, str) and domain.endswith(".lovense.club"):
                        # Inverse of ip_to_domain(): strip suffix and replace '-' with '.'
                        local_ip = domain[: -len(".lovense.club")].replace("-", ".")

                    if local_ip:
                        self._lan_client = AsyncLANClient(
                            self._app_name,
                            local_ip=local_ip,
                            use_https=True,
                            verify_ssl=False,  # fingerprint pinning for local HTTPS
                            ssl_port=https_port,
                        )
                    else:
                        self._lan_client = AsyncLANClient.from_device_info(
                            self._app_name, domain, https_port=https_port
                        )
            await self._dispatch_event(event, payload)
        except (json.JSONDecodeError, TypeError):
            pass

    async def _dispatch_event(self, event: str, payload: Any) -> None:
        if self._on_event:
            try:
                cb = self._on_event(event, payload)
                if asyncio.iscoroutine(cb):
                    self._schedule_callback_task(cb, event_name=event, handler_name="on_event")
            except Exception:  # pylint: disable=broad-exception-caught
                _logger.exception("Socket callback error in on_event for '%s'", event)
        for handler in self._event_handlers.get(event, []):
            try:
                cb = handler(payload)
                if asyncio.iscoroutine(cb):
                    self._schedule_callback_task(
                        cb,
                        event_name=event,
                        handler_name=getattr(handler, "__name__", "handler"),
                    )
            except Exception:  # pylint: disable=broad-exception-caught
                _logger.exception("Socket callback error in handler for '%s'", event)

    def _schedule_callback_task(
        self,
        coro: Awaitable[Any],
        *,
        event_name: str,
        handler_name: str,
    ) -> None:
        task = asyncio.create_task(coro)
        self._callback_tasks.add(task)

        def _on_done(done_task: asyncio.Task) -> None:
            self._callback_tasks.discard(done_task)
            try:
                exc = done_task.exception()
            except asyncio.CancelledError:
                return
            if exc is not None:
                exc_info = (type(exc), exc, exc.__traceback__)
                _logger.error(
                    "Socket callback task failed for event '%s' in '%s'",
                    event_name,
                    handler_name,
                    exc_info=exc_info,
                )

        task.add_done_callback(_on_done)

    def send_event(self, event: str, payload: Any = None) -> None:
        """Send Socket.IO app message. Call when is_socket_io_connected.

        When not connected, returns silently by default. Set raise_on_disconnect=True
        in the constructor to raise ConnectionError instead.
        """
        if not self._transport.is_connected or not self._socket_io_connected:
            if self._raise_on_disconnect:
                raise ConnectionError("Cannot send: WebSocket not connected")
            return
        data = [event] if payload is None else [event, payload]
        msg = "42" + json.dumps(data, separators=(",", ":"))
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._send(msg))
        except RuntimeError as exc:
            if self._raise_on_disconnect:
                raise ConnectionError("Cannot send: no event loop running") from exc

    async def _send(self, msg: str) -> None:
        await self._transport.send(msg)

    def _build_command_payload(
        self,
        command: str,
        action: str,
        time_sec: float = 0,
        toy: str | list[str] | None = None,
        loop_running_sec: float | None = None,
        loop_pause_sec: float | None = None,
        stop_previous: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "command": command,
            "action": action,
            "timeSec": time_sec,
            "apiVer": 1,
            **kwargs,
        }
        if toy is not None:
            payload["toy"] = toy
        if loop_running_sec is not None:
            payload["loopRunningSec"] = loop_running_sec
        if loop_pause_sec is not None:
            payload["loopPauseSec"] = loop_pause_sec
        if stop_previous is not None:
            payload["stopPrevious"] = stop_previous
        return payload

    def send_command(
        self,
        command: str,
        action: str,
        time_sec: float = 0,
        toy: str | list[str] | None = None,
        loop_running_sec: float | None = None,
        loop_pause_sec: float | None = None,
        stop_previous: int | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Send toy command. Uses local HTTPS when is_using_local_commands, else WebSocket.

        When using WebSocket and not connected, returns silently by default.
        Set raise_on_disconnect=True to raise ConnectionError instead.
        """
        payload = self._build_command_payload(
            command,
            action,
            time_sec,
            toy,
            loop_running_sec,
            loop_pause_sec,
            stop_previous,
            **kwargs,
        )
        if self._lan_client:
            try:
                loop = asyncio.get_running_loop()
                task = loop.create_task(self._lan_client.send_command(payload))

                def _on_done(done_task: asyncio.Task) -> None:
                    try:
                        exc = done_task.exception()
                    except asyncio.CancelledError:
                        return
                    if exc is not None:
                        _logger.error("Local LAN command task failed: %s", exc, exc_info=exc)

                task.add_done_callback(_on_done)
            except RuntimeError as exc:
                if self._raise_on_disconnect:
                    raise ConnectionError("Cannot send: no event loop running") from exc
        else:
            self.send_event(BASICAPI_SEND_TOY_COMMAND_TS, payload)

    async def send_command_await(
        self,
        command: str,
        action: str,
        time_sec: float = 0,
        toy: str | list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Send command and await delivery. Use for critical stops.

        When not connected, returns silently by default. Set raise_on_disconnect=True
        to raise ConnectionError instead.
        """
        payload = self._build_command_payload(command, action, time_sec, toy=toy, **kwargs)
        if self._lan_client:
            try:
                await self._lan_client.send_command(payload)
            except LovenseDeviceOfflineError as exc:
                _logger.warning(
                    "Local command routing failed (use_local_commands=True, LAN unreachable): %s",
                    exc,
                )
            except LovenseError as exc:
                # For 24/7 bots we prefer to keep the websocket receiver alive.
                _logger.warning("Local command failed: %s", exc)
            except Exception:  # pylint: disable=broad-exception-caught
                _logger.exception("Unexpected error while sending local command")
            return
        if not self._transport.is_connected or not self._socket_io_connected:
            if self._raise_on_disconnect:
                raise ConnectionError("Cannot send: WebSocket not connected")
            return
        data = [BASICAPI_SEND_TOY_COMMAND_TS, payload]
        msg = "42" + json.dumps(data, separators=(",", ":"))
        await self._send(msg)
