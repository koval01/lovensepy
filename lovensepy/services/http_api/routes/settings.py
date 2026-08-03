"""Runtime configuration: enable transports without restarting or setting env vars."""

from __future__ import annotations

from typing import Any

from fastapi.exceptions import HTTPException
from fastapi.param_functions import Depends
from fastapi.routing import APIRouter

from lovensepy import LovenseError

from ..deps import Runtime, require_local_network
from ..models import SetBleOptionsBody, SetLanIpBody, SetSocketBody, SetTransportsBody
from ..runtime import ServiceRuntime

router = APIRouter(
    prefix="/config",
    tags=["config"],
    dependencies=[Depends(require_local_network)],
)


def _result(runtime: ServiceRuntime) -> dict[str, Any]:
    cfg = runtime.cfg
    return {
        "status": "ok",
        "transports": {
            "lan": cfg.enable_lan,
            "ble": cfg.enable_ble,
            "socket": cfg.enable_socket,
        },
        "lan": {"ip": cfg.lan_ip, "port": cfg.lan_port},
        "config": cfg.public_summary(),
    }


async def _apply(runtime: ServiceRuntime, update: dict[str, Any]) -> dict[str, Any]:
    try:
        await runtime.apply_config(update)
    except LovenseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pylint: disable=broad-exception-caught
        # Socket pairing reaches Lovense cloud; surface network/auth failures as upstream errors.
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc
    return _result(runtime)


@router.get("", summary="Current configuration (no secrets)")
async def get_config(runtime: Runtime) -> dict[str, Any]:
    return _result(runtime)


@router.post(
    "/lan-ip",
    summary="Point LAN (Game Mode) at the Lovense app",
    description=(
        "Enables the LAN transport and rebuilds the backend in place. Live BLE links and "
        "an authenticated Socket API session are preserved."
    ),
)
async def set_lan_ip(runtime: Runtime, body: SetLanIpBody) -> dict[str, Any]:
    update: dict[str, Any] = {"lan_ip": body.lan_ip, "enable_lan": True}
    if body.lan_port is not None:
        update["lan_port"] = int(body.lan_port)
    return await _apply(runtime, update)


@router.post(
    "/socket",
    summary="Enable the Lovense Socket API (cloud pairing)",
    description=(
        "Stores credentials in memory only (never written to disk) and opens the Socket.IO "
        "session, so `GET /socket/qr` can hand back a pairing QR code."
    ),
)
async def set_socket(runtime: Runtime, body: SetSocketBody) -> dict[str, Any]:
    update: dict[str, Any] = {
        "socket_developer_token": body.developer_token.strip(),
        "socket_uid": body.uid.strip(),
        "socket_platform": body.platform.strip(),
        "enable_socket": True,
    }
    if body.uname is not None:
        update["socket_uname"] = body.uname.strip() or None
    if body.use_local_commands is not None:
        update["socket_use_local_commands"] = bool(body.use_local_commands)
    if body.auto_request_qr is not None:
        update["socket_auto_request_qr"] = bool(body.auto_request_qr)
    return await _apply(runtime, update)


@router.post(
    "/ble",
    summary="BLE behaviour (auto-reconnect, scanning, preset dialect)",
)
async def set_ble_options(runtime: Runtime, body: SetBleOptionsBody) -> dict[str, Any]:
    update: dict[str, Any] = {}
    if body.auto_reconnect is not None:
        update["ble_auto_reconnect"] = bool(body.auto_reconnect)
    if body.advertisement_monitor is not None:
        update["ble_advertisement_monitor"] = bool(body.advertisement_monitor)
    if body.scan_timeout_sec is not None:
        update["ble_scan_timeout"] = float(body.scan_timeout_sec)
    if body.scan_name_prefix is not None:
        update["ble_scan_name_prefix"] = body.scan_name_prefix.strip() or None
    if body.preset_uart_keyword is not None:
        update["ble_preset_uart_keyword"] = body.preset_uart_keyword
    if body.preset_emulate_pattern is not None:
        update["ble_preset_emulate_pattern"] = bool(body.preset_emulate_pattern)
    if not update:
        raise HTTPException(status_code=400, detail="No BLE options provided.")
    return await _apply(runtime, update)


@router.post(
    "/transports",
    summary="Enable or disable transports",
    description=(
        "Disabling BLE disconnects every registered toy. Enabling LAN or Socket requires "
        "their settings to be present already (see /config/lan-ip and /config/socket)."
    ),
)
async def set_transports(runtime: Runtime, body: SetTransportsBody) -> dict[str, Any]:
    update: dict[str, Any] = {}
    if body.lan is not None:
        update["enable_lan"] = bool(body.lan)
    if body.ble is not None:
        update["enable_ble"] = bool(body.ble)
    if body.socket is not None:
        update["enable_socket"] = bool(body.socket)
    return await _apply(runtime, update)
