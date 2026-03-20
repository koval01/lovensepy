"""
Socket API session orchestration helpers for integration tests.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from typing import Any, AsyncIterator, Callable

from lovensepy import SocketAPIClient
from lovensepy.socket_api.events import BASICAPI_GET_QRCODE_TC, BASICAPI_UPDATE_DEVICE_INFO_TC


def log(msg: str) -> None:
    print(msg, flush=True)


async def _run_client(
    ws_url: str,
    on_connected: Callable[[], None],
    on_event: Callable[[str, Any], None],
    client_ref: list[SocketAPIClient],
    *,
    on_open: Callable[[], None] | None = None,
    on_error: Callable[[Exception], None] | None = None,
    use_local_commands: bool = False,
    app_name: str = "lovensepy_test",
) -> None:
    client = SocketAPIClient(
        ws_url,
        use_local_commands=use_local_commands,
        app_name=app_name,
        on_socket_open=on_open,
        on_socket_error=on_error,
        on_socket_io_connected=on_connected,
        on_event=on_event,
    )
    client_ref.append(client)
    await client.run_forever()


@asynccontextmanager
async def socket_session(
    ws_url: str,
    *,
    use_local_commands: bool,
    app_name: str,
    timeout_sec: int = 120,
    log_fn: Callable[[str], None] = log,
) -> AsyncIterator[tuple[SocketAPIClient, dict[str, Any]]]:
    """Start Socket API session, wait until toys are available, then cleanup on exit."""
    toys: dict[str, Any] = {}
    session_started = False
    qr_url: str | None = None
    qr_logged: set[str] = set()
    qr_requested = False
    client_ref: list[SocketAPIClient] = []

    def on_event(event: str, payload: Any) -> None:
        nonlocal session_started, qr_url
        if event == BASICAPI_GET_QRCODE_TC:
            data = (payload or {}).get("data", {})
            url = data.get("qrcodeUrl") or data.get("qrcode")
            if url:
                url_str = url if isinstance(url, str) else str(url)
                qr_url = url_str
                if url_str not in qr_logged and not toys:
                    qr_logged.add(url_str)
                    prefix = "[BY LOCAL] " if use_local_commands else ""
                    log_fn(f">>> {prefix}SCAN QR: {url_str}")
        elif event in ("basicapi_update_app_online_tc", "basicapi_update_app_status_tc"):
            if (payload or {}).get("status") == 1:
                session_started = True
        elif event == BASICAPI_UPDATE_DEVICE_INFO_TC:
            for toy in (payload or {}).get("toyList", []):
                if isinstance(toy, dict) and toy.get("connected"):
                    toys[toy["id"]] = toy

    def on_connected() -> None:
        nonlocal qr_requested
        if qr_requested:
            return
        qr_requested = True
        log_fn("Socket.IO connected.")

    async def maybe_request_qr() -> None:
        await asyncio.sleep(2.0)
        if not toys and client_ref:
            client_ref[0].send_event("basicapi_get_qrcode_ts", {"ackId": "1"})

    def on_open() -> None:
        log_fn("WebSocket opened.")

    def on_error(exc: Exception) -> None:
        log_fn(f"WebSocket error: {exc}")

    log_fn("Connecting to Lovense WebSocket...")
    runner = asyncio.create_task(
        _run_client(
            ws_url,
            on_connected,
            on_event,
            client_ref,
            on_open=on_open,
            on_error=on_error,
            use_local_commands=use_local_commands,
            app_name=app_name,
        )
    )
    qr_task = asyncio.create_task(maybe_request_qr())

    try:
        for second in range(timeout_sec):
            await asyncio.sleep(1)
            if session_started and toys and client_ref:
                break
            if qr_url and not session_started and (second % 10 == 0):
                log_fn(f"Waiting for QR scan... ({second}s)")

        assert session_started, "Session did not start — scan the QR with Lovense Remote"
        assert toys, "No toys detected — connect toy(s) before scanning"
        assert client_ref, "Socket client was not created"
        yield client_ref[0], toys
    finally:
        for task in (qr_task, runner):
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
