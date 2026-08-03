"""Mutable runtime state of the service (transports, scheduler, caches, workers).

Routes read everything through :class:`ServiceRuntime` instead of poking at
``app.state`` attributes, so transports can be rebuilt at runtime (LAN IP entered in
the web UI, Socket credentials pasted, BLE toggled) without restarting the process.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from lovensepy.ble_direct.client import LovenseBleAdvertisement
from lovensepy.ble_direct.hub import BleDirectHub

from .access_gate import AccessGate
from .backend import LovenseControlBackend
from .ble_supervisor import BleSupervisor
from .config import ServiceConfig
from .openapi import patch_openapi_toy_ids
from .presence import PresenceHub
from .scheduler import ControlScheduler
from .socket_backend import SocketControlBackend
from .toy_cache import ToyCache
from .transports import build_transports, effective_config
from .tunnel import CloudflaredTunnel, resolve_cloudflared_binary
from .util import extract_toy_ids

if TYPE_CHECKING:
    from fastapi.applications import FastAPI

_logger = logging.getLogger(__name__)

_SOCKET_FIELDS = (
    "socket_developer_token",
    "socket_uid",
    "socket_platform",
    "socket_uname",
    "socket_use_local_commands",
    "socket_auto_request_qr",
    "socket_qr_ack_id",
)

_MONITOR_FIELDS = (
    "enable_ble",
    "ble_advertisement_monitor",
    "ble_monitor_interval_sec",
    "ble_scan_timeout",
    "ble_scan_name_prefix",
)


class ServiceRuntime:
    """Owns transports, the scheduler and background workers for one app instance."""

    def __init__(
        self,
        cfg: ServiceConfig,
        *,
        on_advertisement: Callable[[LovenseBleAdvertisement], None] | None = None,
        on_advertisement_async: (
            Callable[[LovenseBleAdvertisement], Awaitable[None]] | None
        ) = None,
    ) -> None:
        self.on_advertisement = on_advertisement
        self.on_advertisement_async = on_advertisement_async
        self.cfg = effective_config(cfg)
        transports = build_transports(self.cfg)
        self.backend: LovenseControlBackend = transports.backend
        self.ble_hub: BleDirectHub | None = transports.ble_hub
        self.socket_backend: SocketControlBackend | None = transports.socket_backend
        self.scheduler: ControlScheduler | None = None
        self.advertisements: dict[str, dict[str, Any]] = {}
        self.toys = ToyCache(self.backend, ttl=self.cfg.state_cache_ttl_sec)
        self.ble_lock = asyncio.Lock()
        self.started_mono = time.monotonic()
        self.rev = 0
        self._wakeup = asyncio.Event()
        self._app: FastAPI | None = None
        self._monitor_stop: asyncio.Event | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self.supervisor = BleSupervisor(
            hub_provider=lambda: self.ble_hub,
            config_provider=lambda: self.cfg,
            lock=self.ble_lock,
            on_change=self.bump,
        )
        self.tunnel = CloudflaredTunnel(
            local_url_provider=self.tunnel_local_url,
            binary_provider=lambda: resolve_cloudflared_binary(self.cfg.tunnel_binary),
            on_change=self.bump,
        )
        self.gate = AccessGate(enabled=bool(self.cfg.external_gate), _on_change=self.bump)
        self.presence = PresenceHub(on_change=self.bump)

    # --- change notification -------------------------------------------------

    def bump(self) -> None:
        """Mark state as changed and wake every ``/ws`` watcher immediately."""
        self.rev += 1
        previous, self._wakeup = self._wakeup, asyncio.Event()
        previous.set()

    async def wait_for_change(self, timeout: float) -> bool:
        """Wait until :meth:`bump` or ``timeout``. Returns True when woken by a change."""
        waiter = self._wakeup
        try:
            await asyncio.wait_for(waiter.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False

    # --- app wiring ----------------------------------------------------------

    def attach(self, app: FastAPI) -> None:
        self._app = app
        app.state.runtime = self
        self._sync_legacy_state()

    def _sync_legacy_state(self) -> None:
        """Mirror runtime onto ``app.state`` for code (and users) written against it."""
        app = self._app
        if app is None:
            return
        app.state.service_cfg = self.cfg
        app.state.backend = self.backend
        app.state.ble_hub = self.ble_hub
        app.state.socket_backend = self.socket_backend
        app.state.scheduler = self.scheduler
        app.state.last_ble_advertisements = self.advertisements

    def tunnel_local_url(self) -> str:
        """Upstream URL cloudflared should dial (always loopback)."""
        port = self.cfg.listen_port
        if port is None:
            return ""
        host = (self.cfg.listen_host or "127.0.0.1").strip() or "127.0.0.1"
        return f"http://{host}:{int(port)}"

    def set_listen_port(self, port: int) -> None:
        """Remember the port uvicorn is bound to (launcher / tunnel start)."""
        if self.cfg.listen_port == port:
            return
        self.cfg = self.cfg.model_copy(update={"listen_port": int(port)})
        self._sync_legacy_state()

    async def start(self) -> None:
        """Lifespan startup: scheduler, Socket API session, BLE workers, OpenAPI enums."""
        self.scheduler = ControlScheduler(self.backend, session_max_sec=self.cfg.session_max_sec)
        self._sync_legacy_state()

        if self.socket_backend is not None:
            with contextlib.suppress(Exception):
                await self.socket_backend.connect()

        await self.refresh_openapi_toy_ids(best_effort=True)
        self._start_ble_workers()
        if self.cfg.tunnel_enabled and self.cfg.listen_port is not None:
            # Best-effort and non-blocking: missing cloudflared / slow trycloudflare
            # minting must not delay uvicorn readiness.
            try:
                await self.tunnel.start(wait_for_url=False)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                _logger.warning("Could not start Cloudflare tunnel: %s", exc)
        self.bump()

    async def aclose(self) -> None:
        """Lifespan shutdown: stop workers, cancel sessions, drop links."""
        await self.tunnel.aclose()
        await self._stop_ble_workers()
        if self.scheduler is not None:
            await self.scheduler.shutdown()
        backend = self.backend
        if hasattr(backend, "aclose"):
            with contextlib.suppress(Exception):
                await backend.aclose()  # type: ignore[attr-defined]
        else:
            if self.ble_hub is not None:
                with contextlib.suppress(Exception):
                    await self.ble_hub.aclose()
            if self.socket_backend is not None:
                with contextlib.suppress(Exception):
                    await self.socket_backend.aclose()
        self.scheduler = None
        self._sync_legacy_state()

    # --- background workers --------------------------------------------------

    def _start_ble_workers(self) -> None:
        if not self.cfg.enable_ble:
            return
        if self.cfg.ble_advertisement_monitor and self._monitor_task is None:
            # Imported lazily: monitor pulls in bleak scanning helpers.
            from .monitor import start_ble_advertisement_monitor

            self._monitor_stop, self._monitor_task = start_ble_advertisement_monitor(
                cfg=self.cfg,
                advertisements=self.advertisements,
                on_sync=self._on_advertisement_sync,
                on_async=self._on_advertisement_async,
                on_round=self.bump,
            )
        if self.cfg.ble_auto_reconnect:
            self.supervisor.start()

    async def _stop_ble_workers(self) -> None:
        await self.supervisor.stop()
        if self._monitor_stop is not None:
            self._monitor_stop.set()
        task, self._monitor_task = self._monitor_task, None
        self._monitor_stop = None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    def _on_advertisement_sync(self, row: LovenseBleAdvertisement) -> None:
        if self.on_advertisement is not None:
            self.on_advertisement(row)

    async def _on_advertisement_async(self, row: LovenseBleAdvertisement) -> None:
        if self.on_advertisement_async is not None:
            await self.on_advertisement_async(row)

    # --- reconfiguration -----------------------------------------------------

    async def refresh_openapi_toy_ids(self, *, best_effort: bool = False) -> None:
        """Re-inject discovered toy ids into the OpenAPI ``toy_id`` enums."""
        app = self._app
        if app is None:
            return
        try:
            ids = await asyncio.wait_for(extract_toy_ids(self.backend), timeout=3.0)
        except Exception:
            if not best_effort:
                raise
            ids = []
        patch_openapi_toy_ids(app, sorted({*self.cfg.allowed_toy_ids, *ids}))

    async def apply_config(self, update: dict[str, Any]) -> ServiceConfig:
        """Rebuild transports for a changed configuration, keeping live links alive.

        The BLE hub and an already authenticated Socket session are reused unless their
        settings actually changed, so editing the LAN IP never interrupts BLE playback.
        """
        old_cfg = self.cfg
        new_cfg = effective_config(old_cfg.model_copy(update=update))

        socket_changed = any(
            getattr(old_cfg, field) != getattr(new_cfg, field) for field in _SOCKET_FIELDS
        )
        old_socket = self.socket_backend
        if socket_changed and old_socket is not None:
            with contextlib.suppress(Exception):
                await old_socket.aclose()
            old_socket = None

        old_hub = self.ble_hub
        if not new_cfg.enable_ble and old_hub is not None:
            with contextlib.suppress(Exception):
                await old_hub.aclose()
            old_hub = None

        monitor_changed = any(
            getattr(old_cfg, field) != getattr(new_cfg, field) for field in _MONITOR_FIELDS
        )
        if monitor_changed or not new_cfg.enable_ble or not new_cfg.ble_auto_reconnect:
            await self._stop_ble_workers()

        transports = build_transports(new_cfg, ble_hub=old_hub, socket_backend=old_socket)

        previous_scheduler = self.scheduler
        self.cfg = new_cfg
        self.backend = transports.backend
        self.ble_hub = transports.ble_hub
        self.socket_backend = transports.socket_backend
        self.toys = ToyCache(self.backend, ttl=new_cfg.state_cache_ttl_sec)
        self.scheduler = ControlScheduler(self.backend, session_max_sec=new_cfg.session_max_sec)
        self._sync_legacy_state()

        if previous_scheduler is not None:
            await previous_scheduler.shutdown()

        if self.socket_backend is not None and (socket_changed or old_socket is None):
            # Surfaces credential problems to the caller (HTTP 400/502).
            await self.socket_backend.connect()

        self._start_ble_workers()
        await self.refresh_openapi_toy_ids(best_effort=True)
        self.bump()
        return new_cfg
