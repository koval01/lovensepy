"""Live browser presence for the host / remote control split.

Local (LAN / localhost) browsers are *hosts*: they see who is connected through
the Cloudflare tunnel, what that person is doing, and can measure a true
browser↔browser round-trip via an echo relayed through this process.

External browsers are *remotes*: after the access-gate code they drive toys, but
they never receive other remotes' IP / country / user-agent.
"""

from __future__ import annotations

import contextlib
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from starlette.datastructures import Headers
from starlette.types import Scope
from starlette.websockets import WebSocket

from .ua_labels import browser_label, device_label

Role = Literal["host", "remote"]

CLIENT_HEADER = "x-lovensepy-client"
_STALE_SEC = 45.0

# Re-export for tests / callers that imported labels from this module.
__all__ = ("PresenceClient", "PresenceHub", "browser_label", "device_label")


def _country_from_headers(headers: Headers) -> str | None:
    raw = (headers.get("cf-ipcountry") or headers.get("x-country-code") or "").strip().upper()
    if not raw or raw in {"XX", "T1", "ZZ"}:
        return None
    if re.fullmatch(r"[A-Z]{2}", raw):
        return raw
    return None


@dataclass
class PresenceClient:
    client_id: str
    role: Role
    connected_at: float
    last_seen_mono: float
    ip: str | None = None
    country: str | None = None
    user_agent: str | None = None
    device: str = "Unknown device"
    browser: str = "Unknown browser"
    tab: str | None = None
    activity: str | None = None
    activity_at: float | None = None
    rtt_ms: float | None = None
    rtt_at: float | None = None
    socket: WebSocket | None = field(default=None, repr=False)


class PresenceHub:
    """Tracks open control-panel sockets and relays host↔remote echo frames."""

    def __init__(self, *, on_change: Callable[[], None] | None = None) -> None:
        self._on_change = on_change
        self._clients: dict[str, PresenceClient] = {}

    def _notify(self) -> None:
        if self._on_change is not None:
            self._on_change()

    @staticmethod
    def role_for_scope(scope: Scope, headers: Headers | None = None) -> Role:
        from .access_gate import is_external_request

        return "remote" if is_external_request(scope, headers) else "host"

    async def connect(
        self,
        socket: WebSocket,
        *,
        preferred_id: str | None = None,
    ) -> PresenceClient:
        from .access_gate import client_ip

        headers = Headers(scope=socket.scope)
        role = self.role_for_scope(socket.scope, headers)
        client_id = (preferred_id or "").strip()[:64] or secrets.token_urlsafe(12)
        now = time.monotonic()
        ua = headers.get("user-agent")
        row = PresenceClient(
            client_id=client_id,
            role=role,
            connected_at=now,
            last_seen_mono=now,
            ip=client_ip(socket.scope, headers),
            country=_country_from_headers(headers),
            user_agent=ua,
            device=device_label(ua),
            browser=browser_label(ua),
            socket=socket,
        )
        previous = self._clients.get(client_id)
        if previous is not None and previous.socket is not None and previous.socket is not socket:
            with contextlib.suppress(Exception):
                await previous.socket.close(code=4000)
        self._clients[client_id] = row
        self._notify()
        return row

    async def disconnect(self, client_id: str, socket: WebSocket | None = None) -> None:
        row = self._clients.get(client_id)
        if row is None:
            return
        if socket is not None and row.socket is not None and row.socket is not socket:
            return
        del self._clients[client_id]
        self._notify()

    async def touch(
        self,
        client_id: str,
        *,
        tab: str | None = None,
        activity: str | None = None,
        rtt_ms: float | None = None,
        peer_id: str | None = None,
        notify: bool | None = None,
    ) -> PresenceClient | None:
        row = self._clients.get(client_id)
        if row is None:
            return None
        row.last_seen_mono = time.monotonic()
        meaningful = False
        if tab is not None:
            next_tab = tab[:40] or None
            if next_tab != row.tab:
                row.tab = next_tab
                meaningful = True
        if activity is not None:
            cleaned = activity.strip()[:160] or None
            now = time.monotonic()
            if cleaned != row.activity:
                row.activity = cleaned
                row.activity_at = now if cleaned else None
                meaningful = True
            elif cleaned and (row.activity_at is None or now - row.activity_at > 2.0):
                # Same action again (slider moves): refresh "last active" for the host.
                row.activity_at = now
                meaningful = True
        target = self._clients.get(peer_id) if peer_id else None
        if rtt_ms is not None and target is not None and target.role == "remote":
            target.rtt_ms = max(0.0, float(rtt_ms))
            target.rtt_at = time.monotonic()
            # RTT is high-frequency; hosts already see it from the echo reply.
            # Only publish into /state when the caller asks (`notify=True`).
        should_notify = meaningful if notify is None else notify
        if should_notify:
            self._notify()
        return row

    async def mark_http_activity(self, client_id: str | None, activity: str) -> None:
        if not client_id:
            return
        await self.touch(client_id, activity=activity)

    async def relay_echo(
        self,
        *,
        from_id: str,
        to_id: str | None,
        echo_id: str | None = None,
        t0: float | None = None,
        t1: float | None = None,
        reply: bool = False,
        payload: dict[str, Any] | None = None,
    ) -> int:
        """Forward an echo / echo_reply protobuf frame. ``to_id=None`` fans out to remotes."""
        from . import ws_codec

        sender = self._clients.get(from_id)
        if sender is None:
            return 0
        if to_id:
            targets = [self._clients[to_id]] if to_id in self._clients else []
        elif sender.role == "host":
            targets = [row for row in self._clients.values() if row.role == "remote"]
        else:
            # Remotes may only answer the host that pinged them.
            targets = [row for row in self._clients.values() if row.role == "host"]

        # Back-compat for older call sites that still pass a JSON-shaped payload.
        if payload is not None:
            echo_id = payload.get("id", echo_id)
            t0 = payload.get("t0", t0)
            t1 = payload.get("t1", t1)
            reply = bool(payload.get("type") == "echo_reply" or payload.get("reply") or reply)

        sent = 0
        for row in targets:
            socket = row.socket
            if socket is None:
                continue
            try:
                await socket.send_bytes(
                    ws_codec.echo(
                        echo_id=None if echo_id is None else str(echo_id),
                        t0=None if t0 is None else float(t0),
                        t1=None if t1 is None else float(t1),
                        from_id=from_id,
                        to_id=row.client_id,
                        reply=reply,
                    )
                )
                sent += 1
            except Exception:  # pylint: disable=broad-exception-caught
                continue
        return sent

    def get(self, client_id: str) -> PresenceClient | None:
        return self._clients.get(client_id)

    def snapshot_for(self, viewer: PresenceClient | None) -> dict[str, Any]:
        """Presence block embedded in ``/state`` — sensitive fields for hosts only."""
        now = time.monotonic()
        self_view = None
        if viewer is not None:
            self_view = {
                "client_id": viewer.client_id,
                "role": viewer.role,
                "device": viewer.device,
                "browser": viewer.browser,
            }

        remotes: list[dict[str, Any]] = []
        if viewer is not None and viewer.role == "host":
            for row in self._clients.values():
                if row.role != "remote":
                    continue
                if now - row.last_seen_mono > _STALE_SEC:
                    continue
                remotes.append(
                    {
                        "client_id": row.client_id,
                        "online": row.socket is not None,
                        "connected_for_sec": round(now - row.connected_at, 1),
                        "idle_for_sec": round(now - row.last_seen_mono, 1),
                        "ip": row.ip,
                        "country": row.country,
                        "device": row.device,
                        "browser": row.browser,
                        "user_agent": row.user_agent,
                        "tab": row.tab,
                        "activity": row.activity,
                        "activity_age_sec": (
                            None if row.activity_at is None else round(now - row.activity_at, 1)
                        ),
                        "rtt_ms": None if row.rtt_ms is None else round(row.rtt_ms, 1),
                        "rtt_age_sec": (None if row.rtt_at is None else round(now - row.rtt_at, 1)),
                    }
                )
            remotes.sort(key=lambda item: (item.get("idle_for_sec") or 0, item["client_id"]))

        hosts_online = sum(1 for row in self._clients.values() if row.role == "host")
        remotes_online = sum(1 for row in self._clients.values() if row.role == "remote")
        return {
            "self": self_view,
            "remotes": remotes,
            "hosts_online": hosts_online,
            "remotes_online": remotes_online,
        }


def activity_for_path(path: str, method: str) -> str | None:
    """Human label for a successful mutating HTTP call (shown to the host)."""
    if method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    if path.startswith("/command/function"):
        return "Adjusting intensity"
    if path.startswith("/command/preset"):
        return "Playing a preset"
    if path.startswith("/command/pattern"):
        return "Running a pattern"
    if path.startswith("/command/stop"):
        return "Stopping toys"
    if path.startswith("/ble/connect"):
        return "Connecting a Bluetooth toy"
    if path.startswith("/ble/disconnect") or path.startswith("/ble/reconnect"):
        return "Managing Bluetooth"
    if path.startswith("/ble/"):
        return "Bluetooth setup"
    if path.startswith("/config/"):
        return "Changing settings"
    if path.startswith("/system/tunnel"):
        return "Toggling the Cloudflare tunnel"
    return None


def install_presence_activity(app: Any, runtime: Any) -> None:
    """Record what authenticated browsers are doing via REST (for the host monitor)."""

    @app.middleware("http")
    async def _presence_activity(request: Any, call_next: Any) -> Any:  # noqa: ANN401
        response = await call_next(request)
        try:
            if response.status_code < 200 or response.status_code >= 300:
                return response
            client_id = (request.headers.get(CLIENT_HEADER) or "").strip()
            if not client_id:
                return response
            label = activity_for_path(request.url.path, request.method)
            if label:
                await runtime.presence.mark_http_activity(client_id, label)
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        return response
