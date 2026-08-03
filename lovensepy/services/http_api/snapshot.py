"""One aggregated status document for the web UI (``GET /state`` and ``/ws``).

A phone on a flaky Wi-Fi link should need exactly one round-trip to render the whole
control panel, so toys, active sessions, BLE discovery and Socket API pairing are
merged into a single snapshot instead of six polled endpoints.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from lovensepy import Actions, Presets, __version__
from lovensepy._constants import FUNCTION_RANGES
from lovensepy.toy_utils import features_for_toy

from .models import PATTERN_TEMPLATES
from .presence import PresenceClient
from .toy_cache import toy_rows

if TYPE_CHECKING:
    from .runtime import ServiceRuntime

_STOP_ONLY_ACTIONS = frozenset({str(Actions.ALL), str(Actions.STOP)})


def capabilities() -> dict[str, Any]:
    """Static protocol surface: what the UI is allowed to send."""
    return {
        "actions": [str(item) for item in Actions],
        "controllable_actions": [
            str(item) for item in Actions if str(item) not in _STOP_ONLY_ACTIONS
        ],
        "presets": [str(item) for item in Presets],
        "pattern_templates": {str(k): list(v) for k, v in PATTERN_TEMPLATES.items()},
        "function_ranges": {name: list(rng) for name, rng in FUNCTION_RANGES.items()},
        "pattern_limits": {
            "max_steps": 50,
            "min_level": 0,
            "max_level": 20,
            "interval_ms": [100, 1000],
        },
    }


def _ble_registry_by_id(runtime: ServiceRuntime) -> dict[str, dict[str, Any]]:
    if runtime.ble_hub is None:
        return {}
    return {str(row["toy_id"]): row for row in runtime.ble_hub.registry_rows()}


def _toy_view(row: dict[str, Any], ble_row: dict[str, Any] | None) -> dict[str, Any]:
    toy_id = str(row.get("id") or "")
    features = features_for_toy(row)
    status = str(row.get("status") or "").strip()
    online = status != "0" if status else True
    if ble_row is not None:
        online = bool(ble_row.get("connected"))
    battery = row.get("battery")
    if battery is None and ble_row is not None:
        battery = ble_row.get("battery")
    return {
        "id": toy_id,
        "name": row.get("name") or toy_id,
        "nick_name": row.get("nickName") or row.get("name") or toy_id,
        "toy_type": row.get("toyType") or row.get("type") or (ble_row or {}).get("toy_type"),
        "firmware": row.get("version") or (ble_row or {}).get("firmware"),
        "battery": battery,
        "online": online,
        "features": features,
        "transport": "ble" if ble_row is not None else "app",
        "ble": (
            {
                "address": ble_row.get("address"),
                "connected": bool(ble_row.get("connected")),
                "model_letter": ble_row.get("model_letter"),
            }
            if ble_row is not None
            else None
        ),
    }


async def build_state(
    runtime: ServiceRuntime,
    *,
    force_toys: bool = False,
    viewer: PresenceClient | None = None,
) -> dict[str, Any]:
    """Collect the full status document. Never raises for transport failures.

    ``viewer`` controls whether remote-controller details (IP, country, UA, RTT)
    are included — only local *host* browsers receive that block.
    """
    cfg = runtime.cfg
    snapshot = await runtime.toys.get(force=force_toys)
    ble_registry = _ble_registry_by_id(runtime)

    rows = toy_rows(snapshot)
    seen = {str(row.get("id") or "") for row in rows}
    toys = [_toy_view(row, ble_registry.get(str(row.get("id") or ""))) for row in rows]
    # Registered-but-offline BLE toys never show up in GetToys with LAN-only shape;
    # surface them so the UI can offer "reconnect" instead of silently losing a device.
    for toy_id, ble_row in ble_registry.items():
        if toy_id in seen:
            continue
        toys.append(
            _toy_view(
                {
                    "id": toy_id,
                    "name": ble_row.get("name"),
                    "nickName": ble_row.get("nickName"),
                    "type": ble_row.get("toy_type"),
                    "version": ble_row.get("firmware"),
                    "fullFunctionNames": ble_row.get("features") or None,
                    "status": "0",
                },
                ble_row,
            )
        )
    toys.sort(key=lambda item: (not item["online"], item["nick_name"].lower(), item["id"]))

    tasks = await runtime.scheduler.list_tasks() if runtime.scheduler is not None else []

    state: dict[str, Any] = {
        "rev": runtime.rev,
        "version": __version__,
        "server_time": datetime.now(UTC).isoformat(),
        "uptime_sec": round(time.monotonic() - runtime.started_mono, 1),
        "mode": cfg.mode,
        "transports": {
            "lan": cfg.enable_lan,
            "ble": cfg.enable_ble,
            "socket": cfg.enable_socket,
        },
        "configured": bool(cfg.enable_lan or cfg.enable_ble or cfg.enable_socket),
        "config": cfg.public_summary(),
        "capabilities": capabilities(),
        "toys": toys,
        "tasks": tasks,
        "toys_error": runtime.toys.last_error,
    }

    if cfg.enable_ble:
        state["ble"] = {
            "registry": list(ble_registry.values()),
            "advertisements": sorted(
                (dict(row) for row in runtime.advertisements.values()),
                key=lambda row: (-(row.get("rssi") or -999), str(row.get("name") or "")),
            ),
            "monitor": {
                "enabled": bool(cfg.ble_advertisement_monitor),
                "interval_sec": cfg.ble_monitor_interval_sec,
            },
            "scan": {
                "timeout_sec": cfg.ble_scan_timeout,
                "name_prefix": cfg.ble_scan_name_prefix,
            },
            "supervisor": runtime.supervisor.status(),
        }
    else:
        state["ble"] = None

    if cfg.enable_socket and runtime.socket_backend is not None:
        backend = runtime.socket_backend
        try:
            status = backend.status_info()
        except Exception:
            status = {}
        state["socket"] = {"status": status, "qr": backend.qr_info}
    else:
        state["socket"] = None

    state["tunnel"] = runtime.tunnel.status()
    gate = runtime.gate.status()
    role = viewer.role if viewer is not None else "host"
    # Hosts see the live console code + waiting visitors; remotes never get those.
    if role == "host":
        peeked = runtime.gate.peek_code()
        if peeked is not None:
            gate = {**gate, **peeked}
        gate = {**gate, "pending_approvals": runtime.gate.pending_approvals()}
    else:
        gate = {**gate, "pending_approvals": []}
    state["gate"] = gate
    state["presence"] = runtime.presence.snapshot_for(viewer)
    state["access"] = {
        "role": role,
        "capabilities": (
            ["control", "admin", "setup"] if role == "host" else ["control"]
        ),
    }
    if role == "remote":
        return redact_state_for_remote(state)
    return state


def redact_state_for_remote(state: dict[str, Any]) -> dict[str, Any]:
    """Strip admin / setup material from a snapshot shown to tunnel visitors.

    Remotes may drive toys (levels, presets, patterns, battery via ``toys``) but must
    not see tunnel URLs, pairing QR codes, BLE scan results, or mutable config.
    """
    out = dict(state)
    out["config"] = {
        "mode": (state.get("config") or {}).get("mode"),
        "session_max_sec": (state.get("config") or {}).get("session_max_sec"),
        "webui_enabled": True,
        "events_interval_sec": (state.get("config") or {}).get("events_interval_sec"),
        "external_gate": True,
        "lan": {"ip": None, "port": None, "enabled": bool((state.get("transports") or {}).get("lan"))},
        "ble": {
            "enabled": bool((state.get("transports") or {}).get("ble")),
            "scan_timeout_sec": None,
            "scan_name_prefix": None,
            "advertisement_monitor": False,
            "advertisement_monitor_interval_sec": None,
            "preset_uart_keyword": None,
            "preset_emulate_pattern": False,
            "auto_reconnect": False,
            "auto_reconnect_interval_sec": None,
            "battery_refresh_sec": None,
        },
        "socket": {
            "enabled": bool((state.get("transports") or {}).get("socket")),
            "platform": None,
            "uname": None,
            "has_developer_token": False,
            "has_uid": False,
            "use_local_commands": False,
            "auto_request_qr": False,
        },
        "tunnel": {"enabled": False, "listen_port": None, "listen_host": None},
        "app_name": (state.get("config") or {}).get("app_name"),
    }
    # Toys already carry battery / online / features — drop discovery & pairing surfaces.
    out["ble"] = None
    out["socket"] = None
    tunnel = state.get("tunnel") or {}
    out["tunnel"] = {
        "available": False,
        "binary": None,
        "desired": bool(tunnel.get("desired")),
        "running": bool(tunnel.get("running")),
        "url": None,
        "local_url": None,
        "pid": None,
        "last_error": None,
        "restarts": 0,
        "uptime_sec": None,
        "recent": [],
    }
    gate = state.get("gate") or {}
    out["gate"] = {
        "enabled": bool(gate.get("enabled")),
        "code_pending": False,
        "code_expires_in_sec": None,
        "active_sessions": 0,
        "code": None,
        "display": None,
        "pending_approval_count": 0,
        "pending_approvals": [],
    }
    return out
