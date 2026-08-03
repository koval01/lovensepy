"""Background BLE keeper: reconnects registered toys and refreshes cached battery.

BLE links drop constantly in real use (range, phone in a pocket, radio contention, a
toy going to sleep). The control panel should not ask the user to press "connect"
again, so the service keeps every registered toy connected by itself with per-toy
exponential backoff, and pauses a toy only when the user disconnects it on purpose.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from lovensepy.ble_direct.hub import BleDirectHub

from .config import ServiceConfig

_logger = logging.getLogger(__name__)

_BACKOFF_BASE_SEC = 3.0
_BACKOFF_FACTOR = 1.8
_BACKOFF_MAX_SEC = 60.0
_JITTER = 0.2


def _jittered(delay: float) -> float:
    # secrets.randbelow keeps linters happy about randomness; jitter is not security relevant.
    spread = delay * _JITTER
    return max(0.5, delay - spread + (secrets.randbelow(1000) / 1000.0) * 2 * spread)


@dataclass
class _ToyState:
    attempts: int = 0
    reconnects: int = 0
    paused: bool = False
    last_error: str | None = None
    last_attempt_mono: float | None = None
    next_attempt_mono: float = 0.0
    connected_since_mono: float | None = None
    battery_checked_mono: float = 0.0
    history: list[str] = field(default_factory=list)

    def note(self, message: str) -> None:
        self.history.append(message)
        del self.history[:-5]


class BleSupervisor:
    """Keeps GATT links for registered toys up while the service runs."""

    def __init__(
        self,
        *,
        hub_provider: Callable[[], BleDirectHub | None],
        config_provider: Callable[[], ServiceConfig],
        lock: asyncio.Lock,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self._hub_provider = hub_provider
        self._config_provider = config_provider
        self._lock = lock
        self._on_change = on_change
        self._states: dict[str, _ToyState] = {}
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._rounds = 0
        self._last_round_mono: float | None = None

    # --- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._loop(), name="lovensepy:ble_supervisor")

    async def stop(self) -> None:
        self._stop.set()
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    # --- user intent ---------------------------------------------------------

    def _state(self, toy_id: str) -> _ToyState:
        return self._states.setdefault(toy_id, _ToyState())

    def note_connected(self, toy_id: str) -> None:
        """User (or a successful reconnect) brought a toy online: clear backoff + pause."""
        st = self._state(toy_id)
        st.paused = False
        st.attempts = 0
        st.last_error = None
        st.next_attempt_mono = 0.0
        st.connected_since_mono = time.monotonic()
        st.note("connected")
        self._changed()

    def pause(self, toy_id: str) -> None:
        """User disconnected on purpose: stop trying until they ask again."""
        st = self._state(toy_id)
        st.paused = True
        st.connected_since_mono = None
        st.note("paused (manual disconnect)")
        self._changed()

    def resume(self, toy_id: str) -> None:
        st = self._state(toy_id)
        st.paused = False
        st.attempts = 0
        st.next_attempt_mono = 0.0
        st.note("resumed")
        self._changed()

    def forget(self, toy_id: str) -> None:
        self._states.pop(toy_id, None)
        self._changed()

    def _changed(self) -> None:
        if self._on_change is not None:
            with contextlib.suppress(Exception):
                self._on_change()

    # --- status --------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        cfg = self._config_provider()
        now = time.monotonic()
        toys: dict[str, Any] = {}
        for toy_id, st in sorted(self._states.items()):
            toys[toy_id] = {
                "paused": st.paused,
                "attempts": st.attempts,
                "reconnects": st.reconnects,
                "last_error": st.last_error,
                "retry_in_sec": (
                    max(0.0, round(st.next_attempt_mono - now, 1))
                    if st.next_attempt_mono > now
                    else 0.0
                ),
                "connected_for_sec": (
                    round(now - st.connected_since_mono, 1)
                    if st.connected_since_mono is not None
                    else None
                ),
                "recent": list(st.history),
            }
        return {
            "enabled": bool(cfg.ble_auto_reconnect),
            "running": self.running,
            "interval_sec": cfg.ble_auto_reconnect_interval_sec,
            "battery_refresh_sec": cfg.ble_battery_refresh_sec,
            "rounds": self._rounds,
            "last_round_age_sec": (
                round(now - self._last_round_mono, 1) if self._last_round_mono is not None else None
            ),
            "toys": toys,
        }

    # --- worker --------------------------------------------------------------

    async def run_once(self) -> None:
        """Run a single supervision round (also used by tests)."""
        await self._round(self._config_provider())

    async def _loop(self) -> None:
        while not self._stop.is_set():
            cfg = self._config_provider()
            try:
                await self._round(cfg)
            except asyncio.CancelledError:
                raise
            except Exception:
                _logger.debug("BLE supervisor round failed", exc_info=True)
            self._rounds += 1
            self._last_round_mono = time.monotonic()
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=max(1.0, cfg.ble_auto_reconnect_interval_sec)
                )
            except TimeoutError:
                continue

    async def _round(self, cfg: ServiceConfig) -> None:
        hub = self._hub_provider()
        if hub is None:
            return
        rows = hub.registry_rows()
        known = {str(row["toy_id"]) for row in rows}
        for stale in set(self._states) - known:
            self._states.pop(stale, None)

        now = time.monotonic()
        for row in rows:
            toy_id = str(row["toy_id"])
            st = self._state(toy_id)
            if row.get("connected"):
                if st.connected_since_mono is None:
                    st.connected_since_mono = now
                    st.attempts = 0
                    st.last_error = None
                await self._maybe_refresh_battery(hub, cfg, toy_id, st, row)
                continue

            st.connected_since_mono = None
            if st.paused or not cfg.ble_auto_reconnect:
                continue
            if st.next_attempt_mono > now:
                continue
            await self._try_reconnect(hub, toy_id, st)

    async def _try_reconnect(self, hub: BleDirectHub, toy_id: str, st: _ToyState) -> None:
        st.attempts += 1
        st.last_attempt_mono = time.monotonic()
        try:
            async with self._lock:
                await hub.connect(toy_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            st.last_error = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
            delay = min(
                _BACKOFF_MAX_SEC, _BACKOFF_BASE_SEC * (_BACKOFF_FACTOR ** (st.attempts - 1))
            )
            st.next_attempt_mono = time.monotonic() + _jittered(delay)
            st.note(f"attempt {st.attempts} failed: {st.last_error}")
            self._changed()
            return

        st.reconnects += 1
        st.attempts = 0
        st.last_error = None
        st.next_attempt_mono = 0.0
        st.connected_since_mono = time.monotonic()
        st.note("reconnected")
        with contextlib.suppress(Exception):
            async with self._lock:
                await hub.refresh_battery(toy_id)
        st.battery_checked_mono = time.monotonic()
        self._changed()

    async def _maybe_refresh_battery(
        self,
        hub: BleDirectHub,
        cfg: ServiceConfig,
        toy_id: str,
        st: _ToyState,
        row: dict[str, Any],
    ) -> None:
        due = (time.monotonic() - st.battery_checked_mono) >= cfg.ble_battery_refresh_sec
        if not due and row.get("battery") is not None:
            return
        st.battery_checked_mono = time.monotonic()
        with contextlib.suppress(Exception):
            async with self._lock:
                await hub.refresh_battery(toy_id)
        self._changed()
