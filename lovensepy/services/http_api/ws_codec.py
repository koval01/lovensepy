"""Encode / decode binary protobuf frames for the control-panel ``/ws`` channel."""

from __future__ import annotations

import json
from typing import Any

from . import ws_pb2


def encode_server(message: ws_pb2.ServerMessage) -> bytes:
    return message.SerializeToString()


def decode_client(raw: bytes) -> ws_pb2.ClientMessage:
    message = ws_pb2.ClientMessage()
    message.ParseFromString(raw)
    return message


def decode_server(raw: bytes) -> ws_pb2.ServerMessage:
    message = ws_pb2.ServerMessage()
    message.ParseFromString(raw)
    return message


def hello(
    *,
    version: str,
    interval_sec: float,
    heartbeat_sec: float,
    client_id: str,
    role: str,
) -> bytes:
    msg = ws_pb2.ServerMessage()
    msg.hello.version = version
    msg.hello.interval_sec = float(interval_sec)
    msg.hello.heartbeat_sec = float(heartbeat_sec)
    msg.hello.client_id = client_id
    msg.hello.role = role
    return encode_server(msg)


def state(data: dict[str, Any]) -> bytes:
    msg = ws_pb2.ServerMessage()
    msg.state.json = json.dumps(data, default=str, separators=(",", ":")).encode("utf-8")
    return encode_server(msg)


def heartbeat(rev: int) -> bytes:
    msg = ws_pb2.ServerMessage()
    msg.heartbeat.rev = int(rev)
    return encode_server(msg)


def error(detail: str) -> bytes:
    msg = ws_pb2.ServerMessage()
    msg.error.detail = detail
    return encode_server(msg)


def pong() -> bytes:
    msg = ws_pb2.ServerMessage()
    msg.pong.CopyFrom(ws_pb2.Pong())
    return encode_server(msg)


def echo(
    *,
    echo_id: str | None,
    t0: float | None,
    t1: float | None = None,
    from_id: str,
    to_id: str,
    reply: bool = False,
) -> bytes:
    msg = ws_pb2.ServerMessage()
    msg.echo.id = "" if echo_id is None else str(echo_id)
    msg.echo.t0 = 0.0 if t0 is None else float(t0)
    if t1 is not None:
        msg.echo.t1 = float(t1)
    msg.echo.from_id = from_id
    msg.echo.to_id = to_id
    msg.echo.reply = bool(reply)
    return encode_server(msg)


def state_to_dict(message: ws_pb2.State) -> dict[str, Any]:
    if not message.json:
        return {}
    parsed = json.loads(message.json.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise TypeError("state payload must be a JSON object")
    return parsed


def client_refresh() -> bytes:
    msg = ws_pb2.ClientMessage()
    msg.refresh.CopyFrom(ws_pb2.Refresh())
    return msg.SerializeToString()


def client_ping() -> bytes:
    msg = ws_pb2.ClientMessage()
    msg.ping.CopyFrom(ws_pb2.Ping())
    return msg.SerializeToString()


def client_presence(*, tab: str | None = None, activity: str | None = None) -> bytes:
    msg = ws_pb2.ClientMessage()
    if tab is not None:
        msg.presence.tab = tab
    if activity is not None:
        msg.presence.activity = activity
    return msg.SerializeToString()


def client_rtt(*, peer_id: str, rtt_ms: float) -> bytes:
    msg = ws_pb2.ClientMessage()
    msg.rtt.peer_id = peer_id
    msg.rtt.rtt_ms = float(rtt_ms)
    return msg.SerializeToString()


def client_echo(
    *,
    echo_id: str,
    t0: float,
    to_id: str | None = None,
    t1: float | None = None,
    reply: bool = False,
) -> bytes:
    msg = ws_pb2.ClientMessage()
    msg.echo.id = echo_id
    msg.echo.t0 = float(t0)
    if t1 is not None:
        msg.echo.t1 = float(t1)
    if to_id:
        msg.echo.to_id = to_id
    msg.echo.reply = bool(reply)
    return msg.SerializeToString()
