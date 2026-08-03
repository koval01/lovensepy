"""Direct BLE: discovery, pairing-free connection management and branding lookups."""

from __future__ import annotations

import logging
from typing import Any

from fastapi.exceptions import HTTPException
from fastapi.param_functions import Depends, Query
from fastapi.routing import APIRouter

from lovensepy import LovenseError
from lovensepy.ble_direct.branding_resolve import resolve_ble_branding_nickname
from lovensepy.ble_direct.client import (
    LovenseBleAdvertisement,
    _slug_from_adv_name,
    scan_lovense_ble_advertisements,
)
from lovensepy.ble_direct.hub import BleDirectHub, make_ble_toy_id

from ..deps import BleHub, Runtime, require_local_network
from ..models import BleAutoConnectBody, BleBrandingResolveBody, BleConnectBody
from ..monitor import merge_ble_advertisement_rows
from ..runtime import ServiceRuntime
from ..util import gap_name_from_ble_advertisement_cache

_logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/ble",
    tags=["ble"],
    dependencies=[Depends(require_local_network)],
)


async def _scan(runtime: ServiceRuntime, timeout: float | None) -> list[LovenseBleAdvertisement]:
    cfg = runtime.cfg
    use_timeout = float(timeout) if timeout is not None else cfg.ble_scan_timeout
    try:
        rows = await scan_lovense_ble_advertisements(
            timeout=use_timeout,
            name_prefix=cfg.ble_scan_prefix_or_none(),
        )
    except LovenseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    merge_ble_advertisement_rows(runtime.advertisements, rows)
    runtime.bump()
    return rows


async def _after_registry_change(runtime: ServiceRuntime) -> None:
    runtime.toys.invalidate()
    await runtime.refresh_openapi_toy_ids(best_effort=True)
    runtime.bump()


async def _connect_device(
    runtime: ServiceRuntime,
    hub: BleDirectHub,
    *,
    address: str,
    toy_id: str | None = None,
    name: str | None = None,
    toy_type: str | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    """Register (if needed), connect and enrich one peripheral.

    Enrichment reads UART ``DeviceType`` / battery, which is also what upgrades the toy
    id to a MAC-derived one, so the returned id is the id the rest of the API expects.
    """
    resolved_gap = gap_name_from_ble_advertisement_cache(
        dict(runtime.advertisements), address, name
    )
    gap_name = resolved_gap or name
    tid = toy_id or make_ble_toy_id(address, gap_name, 0)
    slug = toy_type or (_slug_from_adv_name(resolved_gap) if resolved_gap else None)
    display = (gap_name or "").strip() or tid

    async with runtime.ble_lock:
        if tid in hub.toy_ids and not replace:
            client = hub.get_client(tid)
            if not client.is_connected:
                await hub.connect(tid)
        else:
            hub.add_toy(
                tid,
                address,
                toy_type=slug,
                name=display,
                replace=replace,
                **runtime.cfg.ble_connect_client_kwargs(),
            )
            await hub.connect(tid)
        tid = await hub.enrich_toy_from_uart(tid, adv_name=gap_name or None)

    runtime.supervisor.note_connected(tid)
    out: dict[str, Any] = {"toy_id": tid, "type": "OK"}
    if resolved_gap:
        out["advertised_name_from_scan"] = resolved_gap
    return out


@router.post(
    "/scan",
    summary="Discover BLE peripherals",
    description=(
        "Runs an on-demand BLE scan. The response lists matching devices; the same rows "
        "are merged into **`GET /ble/advertisements`** (by address)."
    ),
)
async def ble_scan(
    runtime: Runtime,
    hub: BleHub,
    timeout: float | None = Query(default=None, ge=0.5, le=120.0),
) -> dict[str, Any]:
    rows = await _scan(runtime, timeout)
    registered = set(hub.toy_ids)
    return {
        "devices": [
            {
                "address": row.address,
                "name": row.name,
                "rssi": row.rssi,
                "suggested_toy_id": make_ble_toy_id(row.address, row.name, 0),
                "toy_type": _slug_from_adv_name(row.name),
                "registered": make_ble_toy_id(row.address, row.name, 0) in registered,
            }
            for row in rows
        ]
    }


@router.get(
    "/advertisements",
    summary="Cached BLE advertisements (scan + optional monitor)",
    description=(
        "Returns the in-memory map: keys are BLE addresses, values are "
        "`address`, `name`, `rssi`. It is updated by **`POST /ble/scan`** (each scan "
        "merges its results) and by the background monitor in **ble** mode "
        "(interval in **`GET /meta`** → `ble_advertisement_monitor_interval_sec`). "
        "Disable with **`LOVENSE_BLE_ADVERT_MONITOR=0`**. Older entries remain until "
        "overwritten by a newer advertisement for the same address."
    ),
)
async def ble_advertisements(runtime: Runtime, _: BleHub) -> dict[str, Any]:
    return {"advertisements": dict(runtime.advertisements)}


@router.post(
    "/branding/resolve",
    summary="Resolve marketing nickName (ToyConfig)",
    description=(
        "Returns the same string the BLE hub uses for ``nickName`` in "
        "``GET /toys``: firmware tables from packaged ToyConfig, then flat map, "
        "then UART detail suffix. No device required — use to verify branding "
        "after updating ``toy_config_ble_marketing*.json``."
    ),
)
async def ble_branding_resolve(branding: BleBrandingResolveBody) -> dict[str, str]:
    nick, source = resolve_ble_branding_nickname(
        advertised_name=branding.advertised_name,
        toy_type_slug=branding.toy_type_slug,
        model_letter=branding.device_type_letter,
        firmware=branding.firmware,
    )
    return {"nickName": nick, "source": source}


@router.get(
    "/toys",
    summary="Registered BLE toys and link state",
    description=(
        "Registration view of the BLE hub: address, whether the GATT link is up, cached "
        "UART metadata and the auto-reconnect state per toy. No BLE traffic."
    ),
)
async def ble_registry(runtime: Runtime, hub: BleHub) -> dict[str, Any]:
    return {
        "toys": hub.registry_rows(),
        "supervisor": runtime.supervisor.status(),
    }


@router.post(
    "/connect",
    summary="Connect one peripheral",
    description=(
        "Registers the address (if new), opens the GATT link and reads UART metadata. "
        "The returned `toy_id` is the id to use for commands — it can differ from a "
        "previously guessed id once the device reports its real MAC."
    ),
)
async def ble_connect(runtime: Runtime, hub: BleHub, ble: BleConnectBody) -> dict[str, Any]:
    try:
        out = await _connect_device(
            runtime,
            hub,
            address=ble.address,
            toy_id=ble.toy_id,
            name=ble.name,
            toy_type=ble.toy_type,
            replace=ble.replace,
        )
    except LovenseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _after_registry_change(runtime)
    return out


@router.post(
    "/connect/auto",
    summary="Scan and connect everything (one-tap setup)",
    description=(
        "The zero-configuration path used by the web UI: scan, connect every Lovense "
        "peripheral that answers, reconnect registered toys that went offline, and report "
        "per-device results. Failures for one device never abort the rest."
    ),
)
async def ble_auto_connect(
    runtime: Runtime, hub: BleHub, body: BleAutoConnectBody | None = None
) -> dict[str, Any]:
    payload = body or BleAutoConnectBody()
    wanted = (
        {addr.strip().lower() for addr in payload.addresses if addr.strip()}
        if payload.addresses
        else None
    )

    rows = await _scan(runtime, payload.timeout)
    results: list[dict[str, Any]] = []
    connected_ids: list[str] = []

    for row in rows:
        if wanted is not None and row.address.strip().lower() not in wanted:
            continue
        try:
            out = await _connect_device(
                runtime, hub, address=row.address, name=row.name, toy_type=None
            )
            connected_ids.append(out["toy_id"])
            results.append({"address": row.address, "name": row.name, "ok": True, **out})
        except Exception as exc:  # pylint: disable=broad-exception-caught
            _logger.debug("Auto-connect failed for %s", row.address, exc_info=True)
            results.append(
                {
                    "address": row.address,
                    "name": row.name,
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    if payload.include_registered:
        for registry_row in hub.registry_rows():
            toy_id = str(registry_row["toy_id"])
            if registry_row.get("connected") or toy_id in connected_ids:
                continue
            try:
                async with runtime.ble_lock:
                    await hub.connect(toy_id)
                runtime.supervisor.note_connected(toy_id)
                connected_ids.append(toy_id)
                results.append(
                    {"toy_id": toy_id, "address": registry_row.get("address"), "ok": True}
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                results.append(
                    {
                        "toy_id": toy_id,
                        "address": registry_row.get("address"),
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

    await _after_registry_change(runtime)
    return {
        "scanned": len(rows),
        "connected": sorted(set(connected_ids)),
        "results": results,
        "toys": hub.registry_rows(),
    }


@router.post(
    "/reconnect/{toy_id}",
    summary="Reconnect a registered toy",
    description="Also clears the auto-reconnect pause set by a manual disconnect.",
)
async def ble_reconnect(runtime: Runtime, hub: BleHub, toy_id: str) -> dict[str, Any]:
    if toy_id not in hub.toy_ids:
        raise HTTPException(status_code=404, detail=f"Unknown toy id {toy_id!r}.")
    runtime.supervisor.resume(toy_id)
    try:
        async with runtime.ble_lock:
            await hub.connect(toy_id)
            new_id = await hub.enrich_toy_from_uart(toy_id)
    except LovenseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    runtime.supervisor.note_connected(new_id)
    await _after_registry_change(runtime)
    return {"toy_id": new_id, "type": "OK"}


@router.post(
    "/disconnect/{toy_id}",
    summary="Disconnect (keep registration)",
    description="Auto-reconnect is paused for this toy until /ble/reconnect or /ble/connect.",
)
async def ble_disconnect(runtime: Runtime, hub: BleHub, toy_id: str) -> dict[str, Any]:
    runtime.supervisor.pause(toy_id)
    try:
        async with runtime.ble_lock:
            await hub.disconnect(toy_id)
    except LovenseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    await _after_registry_change(runtime)
    return {"toy_id": toy_id, "type": "OK"}


@router.delete(
    "/toys/{toy_id}",
    summary="Forget a toy",
    description="Silences motors, drops the GATT link and removes the registration.",
)
async def ble_remove_toy(runtime: Runtime, hub: BleHub, toy_id: str) -> dict[str, Any]:
    try:
        async with runtime.ble_lock:
            await hub.remove_toy(toy_id)
    except LovenseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    runtime.supervisor.forget(toy_id)
    await _after_registry_change(runtime)
    return {"toy_id": toy_id, "type": "OK"}
