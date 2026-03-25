"""FastAPI application: LAN (Game Mode) or BLE hub control."""

import asyncio
import contextlib
import os
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi.applications import FastAPI
from fastapi.exceptions import HTTPException
from fastapi.param_functions import Query
from fastapi.requests import Request
from pydantic import BaseModel

from lovensepy import Actions, LovenseError, Presets, __version__
from lovensepy.ble_direct.branding_resolve import resolve_ble_branding_nickname
from lovensepy.ble_direct.client import (
    LovenseBleAdvertisement,
    _slug_from_adv_name,
    scan_lovense_ble_advertisements,
)
from lovensepy.ble_direct.hub import BleDirectHub, make_ble_toy_id
from lovensepy.standard.async_lan import AsyncLANClient

from .backend import LovenseControlBackend
from .config import ServiceConfig
from .models import (
    PATTERN_TEMPLATES,
    BleBrandingResolveBody,
    BleConnectBody,
    FunctionCommand,
    PatternCommand,
    PatternTemplate,
    PresetCommand,
    StopFeatureBody,
    StopFeaturesBatchBody,
    StopToyBody,
    StopToysBatchBody,
    pattern_session_signature,
)
from .monitor import merge_ble_advertisement_rows, start_ble_advertisement_monitor
from .multi_backend import CompositeLovenseControlBackend
from .openapi import patch_openapi_toy_ids
from .scheduler import ControlScheduler
from .socket_backend import SocketControlBackend
from .util import as_dict, extract_toy_ids, gap_name_from_ble_advertisement_cache


def _ensure_scheduler_open(scheduler: ControlScheduler) -> None:
    if scheduler.closed:
        raise HTTPException(status_code=503, detail="Server is shutting down.")


def _raise_api_error(exc: Exception, *, value_error_status: int = 400) -> None:
    if isinstance(exc, LovenseError):
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=value_error_status, detail=str(exc)) from exc
    if isinstance(exc, RuntimeError) and str(exc) == "scheduler_closed":
        raise HTTPException(status_code=503, detail="Server is shutting down.") from exc
    raise exc


async def _refresh_openapi_toy_ids(
    fastapi_instance: FastAPI, backend: LovenseControlBackend, cfg: ServiceConfig
) -> None:
    ids = await extract_toy_ids(backend)
    patch_openapi_toy_ids(fastapi_instance, sorted({*cfg.allowed_toy_ids, *ids}))


def create_app(
    config: ServiceConfig | None = None,
    *,
    on_ble_advertisement: Callable[[LovenseBleAdvertisement], None] | None = None,
    on_ble_advertisement_async: Callable[[LovenseBleAdvertisement], Awaitable[None]] | None = None,
) -> FastAPI:
    cfg = config or ServiceConfig.from_env()

    def _effective_cfg(svc_cfg: ServiceConfig) -> ServiceConfig:
        """Disable transports with missing prerequisites (start without env)."""
        enable_lan_eff = bool((svc_cfg.enable_lan) and (svc_cfg.lan_ip or "").strip())
        enable_ble_eff = bool(svc_cfg.enable_ble)
        enable_socket_eff = bool(
            svc_cfg.enable_socket
            and (svc_cfg.socket_developer_token or "").strip()
            and (svc_cfg.socket_uid or "").strip()
            and (svc_cfg.socket_platform or "").strip()
        )
        return svc_cfg.model_copy(
            update={
                "enable_lan": enable_lan_eff,
                "enable_ble": enable_ble_eff,
                "enable_socket": enable_socket_eff,
            }
        )

    cfg = _effective_cfg(cfg)

    backend_parts: dict[str, LovenseControlBackend] = {}
    ble_hub: BleDirectHub | None = None
    socket_backend: SocketControlBackend | None = None

    if cfg.enable_lan:
        backend_parts["lan"] = AsyncLANClient(
            cfg.app_name,
            str(cfg.lan_ip).strip(),  # validate_for_mode() ensures it's set
            port=cfg.lan_port,
        )

    if cfg.enable_ble:
        ble_hub = BleDirectHub()
        backend_parts["ble"] = ble_hub

    if cfg.enable_socket:
        socket_backend = SocketControlBackend(cfg)
        backend_parts["socket"] = socket_backend

    if len(backend_parts) == 1:
        backend = next(iter(backend_parts.values()))
    else:
        backend = CompositeLovenseControlBackend(backend_parts)

    monitor_stop: asyncio.Event | None = None
    monitor_task: asyncio.Task[None] | None = None

    @asynccontextmanager
    async def lifespan(fastapi_app: FastAPI):
        nonlocal monitor_stop, monitor_task
        fastapi_app.state.service_cfg = cfg
        fastapi_app.state.backend = backend
        fastapi_app.state.ble_hub = ble_hub
        fastapi_app.state.socket_backend = socket_backend
        fastapi_app.state.last_ble_advertisements = {}
        fastapi_app.state.scheduler = ControlScheduler(backend, session_max_sec=cfg.session_max_sec)

        if cfg.enable_lan or cfg.enable_socket:
            try:
                await asyncio.wait_for(
                    _refresh_openapi_toy_ids(fastapi_app, backend, cfg),
                    timeout=3.0,
                )
            except Exception:  # nosec B110
                pass  # OpenAPI toy-id refresh is best-effort at startup.
        else:
            patch_openapi_toy_ids(fastapi_app, sorted(set(cfg.allowed_toy_ids)))

        if socket_backend is not None:
            await socket_backend.connect()

        if cfg.enable_ble and cfg.ble_advertisement_monitor:
            monitor_stop, monitor_task = start_ble_advertisement_monitor(
                cfg=cfg,
                state=fastapi_app.state,
                on_sync=on_ble_advertisement,
                on_async=on_ble_advertisement_async,
            )

        yield

        sched: ControlScheduler = fastapi_app.state.scheduler
        await sched.shutdown()
        if monitor_stop is not None:
            monitor_stop.set()
        if monitor_task is not None:
            monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await monitor_task
        # Use the latest backend from app state, because handlers may rebuild transports.
        current_backend: LovenseControlBackend = fastapi_app.state.backend
        if hasattr(current_backend, "aclose"):
            await current_backend.aclose()  # type: ignore[attr-defined]
        else:
            if fastapi_app.state.ble_hub is not None:
                await fastapi_app.state.ble_hub.aclose()
            if fastapi_app.state.socket_backend is not None:
                await fastapi_app.state.socket_backend.aclose()

        fastapi_app.state.scheduler = None  # type: ignore[assignment]

    fastapi_app = FastAPI(
        title="LovensePy Service API",
        description=(
            "LovensePy service: LAN (Game Mode), direct BLE, Socket API "
            "(and optional hybrid) control with per-motor scheduling."
        ),
        version=__version__,
        lifespan=lifespan,
        docs_url="/",
        redoc_url=None,
    )

    @fastapi_app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @fastapi_app.get("/meta")
    async def meta(request: Request) -> dict[str, Any]:
        be: LovenseControlBackend = request.app.state.backend
        cfg_m: ServiceConfig = request.app.state.service_cfg
        try:
            # Backend `get_toys()` may attempt network. Keep `/meta` responsive.
            toy_ids = await asyncio.wait_for(extract_toy_ids(be), timeout=2.0)
        except Exception:
            toy_ids = []
        out: dict[str, Any] = {
            "mode": cfg_m.mode,
            "transports": {
                "lan": cfg_m.enable_lan,
                "ble": cfg_m.enable_ble,
                "socket": cfg_m.enable_socket,
            },
            "actions": [str(item) for item in Actions],
            "presets": [str(item) for item in Presets],
            "pattern_templates": list(PATTERN_TEMPLATES.keys()),
            "toy_ids": toy_ids,
            "session_max_sec": cfg_m.session_max_sec,
        }
        if cfg_m.enable_ble:
            out["ble_preset_uart_default"] = cfg_m.ble_connect_client_kwargs()[
                "ble_preset_uart_keyword"
            ]
            out["ble_preset_emulate_pattern"] = cfg_m.ble_preset_emulate_pattern
        if cfg_m.enable_ble:
            out["ble_advertisement_monitor"] = bool(cfg_m.ble_advertisement_monitor)
            out["ble_advertisement_monitor_interval_sec"] = cfg_m.ble_monitor_interval_sec
            out["ble_last_advertisements"] = dict(
                getattr(request.app.state, "last_ble_advertisements", {})
            )
        return out

    class _SetLanIpBody(BaseModel):
        lan_ip: str
        lan_port: int | None = None

    @fastapi_app.post("/config/lan-ip")
    async def set_lan_ip(request: Request, body: _SetLanIpBody) -> dict[str, Any]:
        """
        Enable LAN without requiring environment variables.
        Rebuilds backend + scheduler on the fly.
        """
        fastapi_app = request.app

        old_scheduler: ControlScheduler = fastapi_app.state.scheduler
        if old_scheduler is not None:
            await old_scheduler.shutdown()

        svc_cfg: ServiceConfig = fastapi_app.state.service_cfg
        svc_cfg_new = svc_cfg.model_copy(
            update={
                "lan_ip": body.lan_ip.strip(),
                "lan_port": int(body.lan_port) if body.lan_port is not None else svc_cfg.lan_port,
                "enable_lan": True,
            }
        )
        svc_cfg_new = _effective_cfg(svc_cfg_new)

        backend_parts: dict[str, LovenseControlBackend] = {}
        if svc_cfg_new.enable_lan:
            backend_parts["lan"] = AsyncLANClient(
                svc_cfg_new.app_name,
                str(svc_cfg_new.lan_ip).strip(),  # validated by _effective_cfg
                port=svc_cfg_new.lan_port,
            )

        ble_hub_local: BleDirectHub | None = None
        socket_backend_local: SocketControlBackend | None = None

        if svc_cfg_new.enable_ble:
            ble_hub_local = fastapi_app.state.ble_hub or BleDirectHub()
            backend_parts["ble"] = ble_hub_local

        if svc_cfg_new.enable_socket:
            socket_backend_local = fastapi_app.state.socket_backend or SocketControlBackend(
                svc_cfg_new
            )
            backend_parts["socket"] = socket_backend_local
            if fastapi_app.state.socket_backend is None:
                await socket_backend_local.connect()

        if len(backend_parts) == 1:
            new_backend: LovenseControlBackend = next(iter(backend_parts.values()))
        else:
            new_backend = CompositeLovenseControlBackend(backend_parts)

        fastapi_app.state.service_cfg = svc_cfg_new
        fastapi_app.state.backend = new_backend
        fastapi_app.state.ble_hub = ble_hub_local
        fastapi_app.state.socket_backend = socket_backend_local
        fastapi_app.state.scheduler = ControlScheduler(
            new_backend, session_max_sec=svc_cfg_new.session_max_sec
        )

        if svc_cfg_new.enable_lan or svc_cfg_new.enable_socket:
            # Best-effort: updating OpenAPI enums may require reaching the LAN/Socket backends.
            # Even if it fails (LAN not reachable yet), the control endpoints can still work later.
            try:
                await asyncio.wait_for(
                    _refresh_openapi_toy_ids(fastapi_app, new_backend, svc_cfg_new),
                    timeout=3.0,
                )
            except Exception:  # nosec B110
                pass  # OpenAPI refresh after /config/lan-ip is best-effort.

        return {
            "status": "ok",
            "transports": {
                "lan": svc_cfg_new.enable_lan,
                "ble": svc_cfg_new.enable_ble,
                "socket": svc_cfg_new.enable_socket,
            },
            "lan": {"ip": svc_cfg_new.lan_ip, "port": svc_cfg_new.lan_port},
        }

    @fastapi_app.get(
        "/toys",
        summary="Toy list (GetToys shape)",
        description=(
            "In **ble** mode, each toy's ``nickName`` is resolved from packaged ToyConfig "
            "(firmware-aware rules, then flat map, then UART detail fallback). "
            "Dry-run the resolver with **POST /ble/branding/resolve**."
        ),
    )
    async def get_toys(request: Request) -> dict[str, Any]:
        be = request.app.state.backend
        try:
            response = await be.get_toys()
            return as_dict(response)
        except LovenseError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @fastapi_app.get(
        "/tasks",
        summary="Active scheduler rows",
        response_description=(
            "Each item includes started_at (UTC ISO-8601) and started_monotonic_sec "
            "(time.monotonic() snapshot for remaining_sec math). "
            "kind=function_loop rows track POST /command/function with "
            "loop_on_time / loop_off_time."
        ),
    )
    async def list_tasks(request: Request) -> dict[str, Any]:
        scheduler: ControlScheduler = request.app.state.scheduler
        return {"tasks": await scheduler.list_tasks()}

    @fastapi_app.post("/command/function")
    async def function_command(request: Request, payload: FunctionCommand) -> dict[str, Any]:
        scheduler: ControlScheduler = request.app.state.scheduler
        _ensure_scheduler_open(scheduler)
        try:
            return await scheduler.schedule_function(
                payload.toy_id,
                payload.actions,
                payload.time,
                stop_previous=payload.stop_previous,
                loop_on_time=payload.loop_on_time,
                loop_off_time=payload.loop_off_time,
            )
        except Exception as exc:
            _raise_api_error(exc)

    @fastapi_app.post("/command/preset")
    async def preset_command(request: Request, payload: PresetCommand) -> dict[str, Any]:
        scheduler: ControlScheduler = request.app.state.scheduler
        be: LovenseControlBackend = request.app.state.backend
        _ensure_scheduler_open(scheduler)

        preset_name = str(payload.name)
        existing = await scheduler.find_matching_preset_session(payload.toy_id, preset_name)
        if existing:
            try:
                return await scheduler.extend_session(existing, float(payload.time))
            except Exception as exc:
                _raise_api_error(exc, value_error_status=404)

        if payload.toy_id:
            await scheduler.cancel_every_slot_for_toy(payload.toy_id)
        else:
            await scheduler.cancel_all_slots()

        try:
            response = as_dict(
                await be.preset_request(
                    payload.name,
                    time=payload.time,
                    toy_id=payload.toy_id,
                    wait_for_completion=False,
                )
            )
        except Exception as exc:
            _raise_api_error(exc)

        try:
            response["scheduler_task_id"] = await scheduler.track_session(
                kind="preset",
                toy_id=payload.toy_id,
                duration=float(payload.time),
                detail={"preset": preset_name},
            )
            response["renewed"] = False
            response["lovense_resent"] = True
        except Exception as exc:
            if isinstance(exc, RuntimeError) and str(exc) == "scheduler_closed":
                return response
            _raise_api_error(exc)
        return response

    @fastapi_app.post("/command/pattern")
    async def pattern_command(request: Request, payload: PatternCommand) -> dict[str, Any]:
        scheduler: ControlScheduler = request.app.state.scheduler
        be: LovenseControlBackend = request.app.state.backend
        _ensure_scheduler_open(scheduler)

        pattern = (
            payload.pattern
            if payload.pattern is not None
            else PATTERN_TEMPLATES[payload.template or PatternTemplate.SOFT]
        )
        sig = pattern_session_signature(
            pattern,
            interval=payload.interval,
            actions=payload.actions,
            template=payload.template,
        )
        existing = await scheduler.find_matching_pattern_session(payload.toy_id, sig)
        if existing:
            try:
                return await scheduler.extend_session(existing, float(payload.time))
            except Exception as exc:
                _raise_api_error(exc, value_error_status=404)

        if payload.toy_id:
            await scheduler.cancel_every_slot_for_toy(payload.toy_id)
        else:
            await scheduler.cancel_all_slots()

        try:
            response = as_dict(
                await be.pattern_request(
                    pattern,
                    actions=[str(action) for action in payload.actions]
                    if payload.actions
                    else None,
                    interval=payload.interval,
                    time=payload.time,
                    toy_id=payload.toy_id,
                    wait_for_completion=False,
                )
            )
        except Exception as exc:
            _raise_api_error(exc)

        detail: dict[str, Any] = {
            "interval": payload.interval,
            "pattern_length": len(pattern),
            "pattern_preview": pattern[:16],
            "pattern_session_key": sig,
            "pattern_data": list(pattern),
            "pattern_actions": [str(a) for a in payload.actions] if payload.actions else None,
        }
        if payload.template is not None:
            detail["template"] = str(payload.template)
        try:
            response["scheduler_task_id"] = await scheduler.track_session(
                kind="pattern",
                toy_id=payload.toy_id,
                duration=float(payload.time),
                detail=detail,
            )
            response["renewed"] = False
            response["lovense_resent"] = True
        except Exception as exc:
            if isinstance(exc, RuntimeError) and str(exc) == "scheduler_closed":
                return response
            _raise_api_error(exc)
        return response

    @fastapi_app.post("/command/stop/all")
    async def stop_all(request: Request) -> dict[str, Any]:
        scheduler: ControlScheduler = request.app.state.scheduler
        try:
            return await scheduler.stop_all()
        except LovenseError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @fastapi_app.post("/command/stop/toy")
    async def stop_toy(request: Request, payload: StopToyBody) -> dict[str, Any]:
        scheduler: ControlScheduler = request.app.state.scheduler
        try:
            return await scheduler.stop_toy(payload.toy_id)
        except LovenseError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @fastapi_app.post("/command/stop/feature")
    async def stop_feature(request: Request, payload: StopFeatureBody) -> dict[str, Any]:
        scheduler: ControlScheduler = request.app.state.scheduler
        try:
            return await scheduler.stop_feature(payload.toy_id, payload.feature)
        except LovenseError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @fastapi_app.post("/command/stop/toys/batch")
    async def stop_toys_batch(request: Request, payload: StopToysBatchBody) -> dict[str, Any]:
        scheduler: ControlScheduler = request.app.state.scheduler
        results: list[dict[str, Any]] = []
        for tid in payload.toy_ids:
            try:
                results.append(
                    {"toy_id": tid, "ok": True, "response": await scheduler.stop_toy(tid)}
                )
            except LovenseError as exc:
                results.append({"toy_id": tid, "ok": False, "error": str(exc)})
        return {"results": results}

    @fastapi_app.post("/command/stop/features/batch")
    async def stop_features_batch(
        request: Request, payload: StopFeaturesBatchBody
    ) -> dict[str, Any]:
        scheduler: ControlScheduler = request.app.state.scheduler
        results: list[dict[str, Any]] = []
        for item in payload.items:
            try:
                results.append(
                    {
                        "toy_id": item.toy_id,
                        "feature": str(item.feature),
                        "ok": True,
                        "response": await scheduler.stop_feature(item.toy_id, item.feature),
                    }
                )
            except LovenseError as exc:
                results.append(
                    {
                        "toy_id": item.toy_id,
                        "feature": str(item.feature),
                        "ok": False,
                        "error": str(exc),
                    }
                )
        return {"results": results}

    if cfg.enable_socket:

        @fastapi_app.get("/socket/status")
        async def socket_status(request: Request) -> dict[str, Any]:
            sb: SocketControlBackend = request.app.state.socket_backend
            return sb.status_info()

        @fastapi_app.get("/socket/qr")
        async def socket_qr(request: Request) -> dict[str, Any]:
            sb: SocketControlBackend = request.app.state.socket_backend
            return sb.qr_info

        @fastapi_app.post("/socket/qr/request")
        async def socket_qr_request(request: Request) -> dict[str, Any]:
            sb: SocketControlBackend = request.app.state.socket_backend
            sb.request_qr()
            return {"type": "OK"}

    if cfg.enable_ble:

        @fastapi_app.post(
            "/ble/scan",
            summary="Discover BLE peripherals",
            description=(
                "Runs an on-demand BLE scan. The response lists matching devices; the same rows "
                "are merged into **`GET /ble/advertisements`** (by address)."
            ),
        )
        async def ble_scan(
            request: Request,
            timeout: float | None = Query(default=None, ge=0.5, le=120.0),
        ) -> dict[str, Any]:
            cfg_b: ServiceConfig = request.app.state.service_cfg
            use_timeout = timeout if timeout is not None else cfg_b.ble_scan_timeout
            try:
                rows = await scan_lovense_ble_advertisements(
                    timeout=use_timeout,
                    name_prefix=cfg_b.ble_scan_prefix_or_none(),
                )
            except LovenseError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            merge_ble_advertisement_rows(request.app.state.last_ble_advertisements, rows)
            return {
                "devices": [{"address": r.address, "name": r.name, "rssi": r.rssi} for r in rows]
            }

        @fastapi_app.post(
            "/ble/branding/resolve",
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

        @fastapi_app.get(
            "/ble/advertisements",
            summary="Cached BLE advertisements (scan + optional monitor)",
            description=(
                "Returns the in-memory map: keys are BLE addresses, values are "
                "`address`, `name`, `rssi`. It is updated by **`POST /ble/scan`** (each scan "
                "merges its results) and by the background monitor in **ble** mode "
                "(on by default when the service loads config from the environment; interval "
                "in **`GET /meta`** → `ble_advertisement_monitor_interval_sec`). Disable with "
                "**`LOVENSE_BLE_ADVERT_MONITOR=0`**. Older entries remain until overwritten "
                "by a newer advertisement for the same address."
            ),
        )
        async def ble_advertisements(request: Request) -> dict[str, Any]:
            m = getattr(request.app.state, "last_ble_advertisements", {})
            return {"advertisements": dict(m)}

        @fastapi_app.post("/ble/connect")
        async def ble_connect(request: Request, ble: BleConnectBody) -> dict[str, Any]:
            hub = request.app.state.ble_hub
            if hub is None:
                raise HTTPException(status_code=500, detail="BLE hub not initialized.")
            cfg_b: ServiceConfig = request.app.state.service_cfg
            adv_cache = dict(getattr(request.app.state, "last_ble_advertisements", {}) or {})
            resolved_gap = gap_name_from_ble_advertisement_cache(adv_cache, ble.address, ble.name)
            gap_for_id = resolved_gap or ble.name
            tid = ble.toy_id or make_ble_toy_id(ble.address, gap_for_id, 0)
            slug = ble.toy_type
            if slug is None and resolved_gap:
                slug = _slug_from_adv_name(resolved_gap)
            display = (resolved_gap or ble.name or "").strip() or tid
            try:
                hub.add_toy(
                    tid,
                    ble.address,
                    toy_type=slug,
                    name=display,
                    replace=ble.replace,
                    **cfg_b.ble_connect_client_kwargs(),
                )
                await hub.connect(tid)
                tid = await hub.enrich_toy_from_uart(
                    tid, adv_name=(resolved_gap or ble.name or None)
                )
            except LovenseError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            await _refresh_openapi_toy_ids(request.app, request.app.state.backend, cfg_b)
            out: dict[str, Any] = {"toy_id": tid, "type": "OK"}
            if resolved_gap:
                out["advertised_name_from_scan"] = resolved_gap
            return out

        @fastapi_app.post("/ble/disconnect/{toy_id}")
        async def ble_disconnect(toy_id: str, request: Request) -> dict[str, Any]:
            hub = request.app.state.ble_hub
            if hub is None:
                raise HTTPException(status_code=500, detail="BLE hub not initialized.")
            try:
                await hub.disconnect(toy_id)
            except LovenseError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            cfg_b: ServiceConfig = request.app.state.service_cfg
            await _refresh_openapi_toy_ids(request.app, request.app.state.backend, cfg_b)
            return {"toy_id": toy_id, "type": "OK"}

        @fastapi_app.delete("/ble/toys/{toy_id}")
        async def ble_remove_toy(toy_id: str, request: Request) -> dict[str, Any]:
            hub = request.app.state.ble_hub
            if hub is None:
                raise HTTPException(status_code=500, detail="BLE hub not initialized.")
            try:
                await hub.remove_toy(toy_id)
            except LovenseError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            cfg_b: ServiceConfig = request.app.state.service_cfg
            await _refresh_openapi_toy_ids(request.app, request.app.state.backend, cfg_b)
            return {"toy_id": toy_id, "type": "OK"}

    return fastapi_app


def _config_error_app(detail: str) -> FastAPI:
    app_err = FastAPI(
        title="LovensePy Service API",
        description="Configuration error.",
        version=__version__,
        # Keep the docs accessible at `/` even when running in "health-only" mode.
        # (We expose the config explanation at `/config-error` instead.)
        docs_url="/",
        redoc_url=None,
    )

    @app_err.get("/config-error")
    def config_error_json() -> dict[str, Any]:
        return {
            "status": "error",
            "configured": False,
            "detail": detail,
            "hint": (
                "Service started without transports. Configure LOVENSE_* env vars "
                "to enable LAN/BLE/Socket control."
            ),
        }

    @app_err.get("/health")
    def health_error() -> dict[str, str]:
        # Keep server UX "ready": without env we still want a running HTTP server.
        return {"status": "ok", "configured": "false"}

    @app_err.get("/meta")
    def meta_error() -> dict[str, Any]:
        # Best-effort: we don't have a validated ServiceConfig here, but we can surface
        # the error and show transports as disabled.
        mode = os.environ.get("LOVENSE_SERVICE_MODE", "lan").strip().lower() or "lan"
        return {
            "mode": mode,
            "transports": {"lan": False, "ble": False, "socket": False},
            "configured": False,
            "detail": detail,
        }

    @app_err.api_route("/{_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def fail_all(_path: str) -> None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Service is running in health-only mode. Configure LOVENSE_* env vars "
                "to enable control."
            ),
        )

    return app_err


try:
    _svc_cfg = ServiceConfig.from_env()
    app = create_app(_svc_cfg)
except ValueError as _config_exc:
    _config_error_detail = str(_config_exc)
    app = _config_error_app(_config_error_detail)
