"""Helpers for protobuf ``/ws`` frames in tests."""

from __future__ import annotations

from typing import Any

from lovensepy.services.http_api import ws_codec
from lovensepy.services.http_api.ws_pb2 import ServerMessage


def recv_server(socket: Any) -> dict[str, Any]:
    """Receive one binary frame and return a JSON-shaped dict for assertions."""
    raw = socket.receive_bytes()
    message = ws_codec.decode_server(raw)
    kind = message.WhichOneof("body")
    if kind == "hello":
        h = message.hello
        return {
            "type": "hello",
            "data": {
                "version": h.version,
                "interval_sec": h.interval_sec,
                "heartbeat_sec": h.heartbeat_sec,
                "client_id": h.client_id,
                "role": h.role,
            },
        }
    if kind == "state":
        return {"type": "state", "data": ws_codec.state_to_dict(message.state)}
    if kind == "heartbeat":
        return {"type": "heartbeat", "rev": message.heartbeat.rev}
    if kind == "error":
        return {"type": "error", "detail": message.error.detail}
    if kind == "pong":
        return {"type": "pong"}
    if kind == "echo":
        echo = message.echo
        return {
            "type": "echo_reply" if echo.reply else "echo",
            "id": echo.id,
            "t0": echo.t0,
            "t1": echo.t1 if echo.HasField("t1") else None,
            "from": echo.from_id,
            "to": echo.to_id,
            "reply": echo.reply,
        }
    raise AssertionError(f"unexpected server frame: {kind!r} ({ServerMessage})")


def send_refresh(socket: Any) -> None:
    socket.send_bytes(ws_codec.client_refresh())


def send_ping(socket: Any) -> None:
    socket.send_bytes(ws_codec.client_ping())


def send_echo(
    socket: Any,
    *,
    echo_id: str,
    t0: float,
    to_id: str | None = None,
    t1: float | None = None,
    reply: bool = False,
) -> None:
    socket.send_bytes(ws_codec.client_echo(echo_id=echo_id, t0=t0, to_id=to_id, t1=t1, reply=reply))
