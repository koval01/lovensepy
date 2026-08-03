"""Health, metadata, aggregated state and network discovery."""

from __future__ import annotations

import time
from typing import Any

from fastapi.exceptions import HTTPException
from fastapi.requests import Request
from fastapi.routing import APIRouter

from lovensepy import Actions, Presets, __version__

from ..deps import HostOnly, Runtime
from ..models import PATTERN_TEMPLATES, SetTunnelBody
from ..netinfo import network_info
from ..presence import CLIENT_HEADER, PresenceClient, PresenceHub
from ..snapshot import build_state
from ..util import extract_toy_ids
from ..webui import webui_info

router = APIRouter(tags=["system"])


def _request_port(request: Request) -> int | None:
    if request.url.port is not None:
        return int(request.url.port)
    host = request.headers.get("host") or ""
    if ":" in host:
        maybe = host.rsplit(":", 1)[-1]
        if maybe.isdigit():
            return int(maybe)
    return None


@router.get("/health", summary="Liveness probe")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/meta", summary="Service capabilities and transport flags")
async def meta(runtime: Runtime, _: HostOnly) -> dict[str, Any]:
    cfg = runtime.cfg
    try:
        toy_ids = await extract_toy_ids(runtime.backend)
    except Exception:
        toy_ids = []
    out: dict[str, Any] = {
        "mode": cfg.mode,
        "transports": {
            "lan": cfg.enable_lan,
            "ble": cfg.enable_ble,
            "socket": cfg.enable_socket,
        },
        "actions": [str(item) for item in Actions],
        "presets": [str(item) for item in Presets],
        "pattern_templates": list(PATTERN_TEMPLATES.keys()),
        "toy_ids": toy_ids,
        "session_max_sec": cfg.session_max_sec,
        "version": __version__,
        "webui": webui_info()["available"],
    }
    if cfg.enable_ble:
        out["ble_preset_uart_default"] = cfg.ble_connect_client_kwargs()["ble_preset_uart_keyword"]
        out["ble_preset_emulate_pattern"] = cfg.ble_preset_emulate_pattern
        out["ble_advertisement_monitor"] = bool(cfg.ble_advertisement_monitor)
        out["ble_advertisement_monitor_interval_sec"] = cfg.ble_monitor_interval_sec
        out["ble_auto_reconnect"] = bool(cfg.ble_auto_reconnect)
        out["ble_last_advertisements"] = dict(runtime.advertisements)
    return out


@router.get(
    "/state",
    summary="Everything the control panel needs in one call",
    response_description=(
        "Toys (merged across transports), active scheduler rows, BLE discovery and "
        "supervisor status, Socket API pairing state, capabilities and config. The toy "
        "list is cached for `config.state_cache_ttl_sec`; pass `fresh=true` to bypass."
    ),
)
async def state(request: Request, runtime: Runtime, fresh: bool = False) -> dict[str, Any]:
    client_id = (request.headers.get(CLIENT_HEADER) or "").strip() or None
    viewer = runtime.presence.get(client_id) if client_id else None
    if viewer is None:
        role = PresenceHub.role_for_scope(request.scope, request.headers)
        now = time.monotonic()
        viewer = PresenceClient(
            client_id=client_id or "http",
            role=role,
            connected_at=now,
            last_seen_mono=now,
        )
    return await build_state(runtime, force_toys=fresh, viewer=viewer)


@router.get(
    "/system/network",
    summary="URLs that reach this service",
    response_description=(
        "Used by the web UI to render a QR code so a phone on the same Wi-Fi can open "
        "the control panel without typing an IP address. When a Cloudflare tunnel is "
        "running, `tunnel_url` / `primary_url` point at the public https://*.trycloudflare.com "
        "address."
    ),
)
async def system_network(request: Request, runtime: Runtime, _: HostOnly) -> dict[str, Any]:
    forwarded_proto = request.headers.get("x-forwarded-proto")
    scheme = (forwarded_proto or request.url.scheme or "http").split(",")[0].strip()
    port = request.url.port or runtime.cfg.listen_port
    return network_info(
        scheme="https" if scheme == "https" else "http",
        port=port,
        host_header=request.headers.get("host"),
        tunnel=runtime.tunnel.status(),
    )


@router.get(
    "/system/tunnel",
    summary="Cloudflare quick-tunnel status",
)
async def tunnel_status(runtime: Runtime, _: HostOnly) -> dict[str, Any]:
    return runtime.tunnel.status()


@router.get(
    "/system/access-code",
    summary="Read the live external-access code (host only)",
    description=(
        "Returns the 6-digit challenge for the phone-share dialog. Minted on demand so "
        "the host can read it without watching the console. Never available over the tunnel."
    ),
)
async def get_access_code(runtime: Runtime, _: HostOnly) -> dict[str, Any]:
    result = runtime.gate.ensure_host_code(rotate=False)
    runtime.bump()
    return result


@router.post(
    "/system/access-code",
    summary="Rotate the external-access code (host only)",
)
async def rotate_access_code(runtime: Runtime, _: HostOnly) -> dict[str, Any]:
    result = runtime.gate.ensure_host_code(rotate=True)
    runtime.bump()
    return result


@router.get(
    "/system/access-approvals",
    summary="List tunnel visitors waiting for host approval",
)
async def list_access_approvals(runtime: Runtime, _: HostOnly) -> dict[str, Any]:
    return {"approvals": runtime.gate.pending_approvals()}


@router.post(
    "/system/access-approvals/{request_id}/allow",
    summary="Allow a waiting tunnel visitor (no access code needed)",
)
async def allow_access_approval(request_id: str, runtime: Runtime, _: HostOnly) -> dict[str, Any]:
    result = runtime.gate.approve(request_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No pending approval with that id.")
    return result


@router.post(
    "/system/access-approvals/{request_id}/deny",
    summary="Deny a waiting tunnel visitor",
)
async def deny_access_approval(request_id: str, runtime: Runtime, _: HostOnly) -> dict[str, Any]:
    result = runtime.gate.deny(request_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No pending approval with that id.")
    return result


@router.post(
    "/system/tunnel",
    summary="Start or stop the Cloudflare quick tunnel",
    description=(
        "Spawns `cloudflared tunnel --url http://127.0.0.1:<port>` and returns the public "
        "https://*.trycloudflare.com URL. The URL is reachable by anyone who has it for as "
        "long as the tunnel runs — stop it when you are done sharing. "
        "Local network only — tunnel visitors cannot start or stop the tunnel."
    ),
)
async def set_tunnel(
    runtime: Runtime, body: SetTunnelBody, request: Request, _: HostOnly
) -> dict[str, Any]:
    if body.enabled:
        port = body.port or runtime.cfg.listen_port or _request_port(request)
        if port is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Cannot start a tunnel: listen port is unknown. "
                    'Set LOVENSE_PORT or pass {"port": …}.'
                ),
            )
        runtime.set_listen_port(port)
        runtime.cfg = runtime.cfg.model_copy(update={"tunnel_enabled": True})
        try:
            status = await runtime.tunnel.start()
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc
        return {"status": "ok", "tunnel": status}

    runtime.cfg = runtime.cfg.model_copy(update={"tunnel_enabled": False})
    status = await runtime.tunnel.stop()
    return {"status": "ok", "tunnel": status}
