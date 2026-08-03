"""``/ws``: live state stream, presence, and host↔remote echo relay.

Frames are protobuf (`ServerMessage` / `ClientMessage` in ``proto/ws.proto``).
Pushing a snapshot beats polling on mobile: a phone that wakes from sleep gets the
current truth in one frame, and holding a socket open costs far less battery than a
1 Hz fetch loop. Clients that cannot keep a socket (corporate proxies, older Safari
on http) fall back to polling ``GET /state``, so this endpoint stays optional.

Echo frames are relayed peer-to-peer through this process so a localhost host can
measure the real browser↔browser round-trip of a remote controller on the tunnel —
not ICMP ping to Cloudflare.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
from typing import Any

from fastapi.routing import APIRouter
from fastapi.websockets import WebSocket, WebSocketDisconnect

from lovensepy import __version__

from .. import ws_codec
from ..presence import PresenceClient
from ..runtime import ServiceRuntime
from ..snapshot import build_state

_logger = logging.getLogger(__name__)

router = APIRouter(tags=["events"])

_HEARTBEAT_SEC = 15.0
_VOLATILE_TOP_LEVEL = ("server_time", "uptime_sec", "rev")
_VOLATILE_REMOTE_KEYS = (
    "idle_for_sec",
    "connected_for_sec",
    "activity_age_sec",
    "rtt_age_sec",
)


def _fingerprint(state: dict[str, Any]) -> str:
    """Hash the meaningful part of a snapshot so unchanged states are not re-sent.

    Clocks and countdowns are excluded: the browser ticks those locally, otherwise
    every single second would look like a change.
    """
    trimmed = {key: value for key, value in state.items() if key not in _VOLATILE_TOP_LEVEL}
    tasks = trimmed.get("tasks")
    if isinstance(tasks, list):
        trimmed["tasks"] = [
            {
                key: value
                for key, value in task.items()
                if key not in ("remaining_sec", "started_monotonic_sec", "ends_mono")
            }
            for task in tasks
            if isinstance(task, dict)
        ]
    presence = trimmed.get("presence")
    if isinstance(presence, dict):
        remotes = presence.get("remotes")
        if isinstance(remotes, list):
            trimmed["presence"] = {
                **presence,
                "remotes": [
                    {key: value for key, value in row.items() if key not in _VOLATILE_REMOTE_KEYS}
                    for row in remotes
                    if isinstance(row, dict)
                ],
            }
    blob = json.dumps(trimmed, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


async def _read_commands(
    socket: WebSocket,
    runtime: ServiceRuntime,
    client: PresenceClient,
    force: asyncio.Event,
    closed: asyncio.Event,
) -> None:
    """Handle client protobuf messages: refresh, presence, echo relay, server ping."""
    try:
        while True:
            raw = await socket.receive_bytes()
            try:
                message = ws_codec.decode_client(raw)
            except Exception:  # nosec B112  # pylint: disable=broad-exception-caught
                continue
            kind = message.WhichOneof("body")
            if kind == "refresh":
                force.set()
            elif kind == "ping":
                await socket.send_bytes(ws_codec.pong())
            elif kind == "presence":
                tab = message.presence.tab or None
                activity = message.presence.activity or None
                await runtime.presence.touch(
                    client.client_id,
                    tab=tab,
                    activity=activity,
                )
            elif kind == "rtt":
                peer_id = message.rtt.peer_id
                if peer_id:
                    await runtime.presence.touch(
                        client.client_id,
                        rtt_ms=float(message.rtt.rtt_ms),
                        peer_id=peer_id,
                        notify=False,
                    )
            elif kind == "echo":
                echo = message.echo
                t1 = echo.t1 if echo.HasField("t1") else None
                await runtime.presence.relay_echo(
                    from_id=client.client_id,
                    to_id=echo.to_id or None,
                    echo_id=echo.id,
                    t0=echo.t0,
                    t1=t1,
                    reply=bool(echo.reply),
                )
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception:  # pylint: disable=broad-exception-caught
        _logger.debug("WebSocket reader failed", exc_info=True)
    finally:
        closed.set()


@router.websocket("/ws")
async def events(socket: WebSocket) -> None:
    await socket.accept()
    runtime: ServiceRuntime | None = getattr(socket.app.state, "runtime", None)
    if runtime is None:
        await socket.send_bytes(ws_codec.error("Service is not ready."))
        await socket.close(code=1013)
        return

    preferred_id = None
    # Optional first-frame hello with a stable client id (tab session).
    # Starlette has no peek, so clients send hello as the first text after open;
    # we also accept query ?client_id= for simpler reconnects.
    query = socket.scope.get("query_string") or b""
    if isinstance(query, (bytes, bytearray)):
        from urllib.parse import parse_qs

        params = parse_qs(query.decode("utf-8", errors="ignore"))
        values = params.get("client_id") or []
        if values:
            preferred_id = values[0]

    client = await runtime.presence.connect(socket, preferred_id=preferred_id)
    interval = max(0.2, float(runtime.cfg.events_interval_sec))
    force = asyncio.Event()
    closed = asyncio.Event()
    reader = asyncio.create_task(
        _read_commands(socket, runtime, client, force, closed),
        name="lovensepy:ws_reader",
    )

    await socket.send_bytes(
        ws_codec.hello(
            version=__version__,
            interval_sec=interval,
            heartbeat_sec=_HEARTBEAT_SEC,
            client_id=client.client_id,
            role=client.role,
        )
    )

    last_fingerprint: str | None = None
    idle_for = 0.0
    try:
        while not closed.is_set():
            wanted_fresh = force.is_set()
            force.clear()
            # Refresh the live client row — connect may have replaced metadata.
            live = runtime.presence.get(client.client_id) or client
            state = await build_state(runtime, force_toys=wanted_fresh, viewer=live)
            fingerprint = _fingerprint(state)
            if fingerprint != last_fingerprint or wanted_fresh:
                await socket.send_bytes(ws_codec.state(state))
                last_fingerprint = fingerprint
                idle_for = 0.0
            elif idle_for >= _HEARTBEAT_SEC:
                await socket.send_bytes(ws_codec.heartbeat(int(state["rev"])))
                idle_for = 0.0

            changed = await runtime.wait_for_change(timeout=interval)
            idle_for = 0.0 if changed else idle_for + interval
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception:  # pylint: disable=broad-exception-caught
        _logger.debug("WebSocket writer failed", exc_info=True)
    finally:
        reader.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await reader
        await runtime.presence.disconnect(client.client_id, socket)
        with contextlib.suppress(Exception):
            await socket.close()
