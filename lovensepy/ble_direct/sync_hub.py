"""
Synchronous :class:`BleDirectHub` facade for scripts (LANClient-like ergonomics).

BLE I/O stays async internally (``bleak`` on a **single** dedicated asyncio loop
in a background thread). Repeated :class:`asyncio.run` would destroy the loop
between calls and break bleak’s loop-bound clients — so blocking methods schedule
work with :func:`asyncio.run_coroutine_threadsafe` instead. Do **not** use this
from inside ``async def`` when a loop is already running — use
:class:`BleDirectHub` and ``await`` instead.
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Coroutine
from typing import Any

from pydantic import BaseModel

from lovensepy._constants import Actions, Presets
from lovensepy._models import CommandResponse, GetToyNameResponse, GetToysResponse
from lovensepy.exceptions import LovenseError

from .client import BleDirectClient, ensure_bleak_installed
from .hub import BleDirectHub

__all__ = ["BleDirectHubSync", "ble_sync_default_timeout", "run_ble_coroutine"]

_background_loop: asyncio.AbstractEventLoop | None = None
_background_thread: threading.Thread | None = None
_loop_ready = threading.Event()
_loop_start_lock = threading.Lock()


def ble_sync_default_timeout() -> float | None:
    """Seconds for :func:`run_ble_coroutine` when ``timeout`` is omitted.

    Reads ``LOVENSEPY_BLE_SYNC_TIMEOUT``: empty, ``0``, ``none``, or ``inf`` →
    unbounded wait; otherwise a positive float (default ``300``).
    """
    raw = os.environ.get("LOVENSEPY_BLE_SYNC_TIMEOUT", "300")
    s = raw.strip().lower()
    if s in ("", "0", "none", "inf"):
        return None
    return float(s)


def _ensure_background_loop() -> asyncio.AbstractEventLoop:
    """Lazily start one daemon thread running ``loop.run_forever()`` for bleak I/O."""
    global _background_loop, _background_thread
    if _background_loop is not None:
        return _background_loop
    with _loop_start_lock:
        if _background_loop is not None:
            return _background_loop
        _loop_ready.clear()

        def _runner() -> None:
            global _background_loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            _background_loop = loop
            _loop_ready.set()
            loop.run_forever()

        _background_thread = threading.Thread(
            target=_runner,
            name="lovensepy-ble-asyncio",
            daemon=True,
        )
        _background_thread.start()
        _loop_ready.wait(timeout=60.0)
        if _background_loop is None:
            raise RuntimeError("Failed to start background asyncio loop for BleDirectHubSync")
        return _background_loop


def run_ble_coroutine[T](coro: Coroutine[Any, Any, T], *, timeout: float | None = None) -> T:
    """Run ``coro`` to completion on the shared BLE thread loop (or raise if a loop runs here).

    ``timeout`` is passed to ``concurrent.futures.Future.result`` (seconds). If omitted,
    uses :func:`ble_sync_default_timeout` (env ``LOVENSEPY_BLE_SYNC_TIMEOUT``, default 300s).
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = _ensure_background_loop()
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        t = ble_sync_default_timeout() if timeout is None else timeout
        return fut.result(timeout=t)
    raise RuntimeError(
        "BleDirectHubSync / run_ble_coroutine cannot be used while an asyncio event loop "
        "is already running. Use BleDirectHub and await the same operation instead."
    )


class BleDirectHubSync:
    """LANClient-shaped synchronous API over :class:`BleDirectHub`.

    Same ``actions``, ``presets``, ``error_codes``, and method names as
    :class:`~lovensepy.standard.lan.LANClient` where BLE supports them. The
    underlying async hub is :attr:`async_hub`.
    """

    def __init__(self) -> None:
        ensure_bleak_installed()
        self._hub = BleDirectHub()

    @property
    def async_hub(self) -> BleDirectHub:
        """The wrapped :class:`BleDirectHub` (for ``await``-based code)."""
        return self._hub

    @property
    def actions(self) -> type[Actions]:
        return self._hub.actions

    @property
    def presets(self) -> type[Presets]:
        return self._hub.presets

    @property
    def error_codes(self) -> dict[int, str]:
        return self._hub.error_codes

    @property
    def last_command(self) -> dict[str, Any] | None:
        return self._hub.last_command

    def __len__(self) -> int:
        return len(self._hub)

    @property
    def toy_ids(self) -> tuple[str, ...]:
        return self._hub.toy_ids

    def add_toy(
        self,
        toy_id: str,
        address: str,
        *,
        toy_type: str | None = None,
        name: str | None = None,
        replace: bool = False,
        **client_kwargs: Any,
    ) -> None:
        self._hub.add_toy(
            toy_id,
            address,
            toy_type=toy_type,
            name=name,
            replace=replace,
            **client_kwargs,
        )

    def get_client(self, toy_id: str) -> BleDirectClient:
        return self._hub.get_client(toy_id)

    def connect(self, toy_id: str) -> None:
        run_ble_coroutine(self._hub.connect(toy_id))

    def connect_all(self) -> None:
        run_ble_coroutine(self._hub.connect_all())

    def disconnect(self, toy_id: str) -> None:
        run_ble_coroutine(self._hub.disconnect(toy_id))

    def disconnect_all(self) -> None:
        run_ble_coroutine(self._hub.disconnect_all())

    def remove_toy(self, toy_id: str) -> None:
        run_ble_coroutine(self._hub.remove_toy(toy_id))

    def discover_and_connect(
        self,
        *,
        timeout: float = 10.0,
        name_prefix: str | None = "LVS-",
        clear: bool = True,
        enrich_uart: bool = True,
        **client_kwargs: Any,
    ) -> list[str]:
        return run_ble_coroutine(
            self._hub.discover_and_connect(
                timeout=timeout,
                name_prefix=name_prefix,
                clear=clear,
                enrich_uart=enrich_uart,
                **client_kwargs,
            )
        )

    def close(self) -> None:
        run_ble_coroutine(self._hub.aclose())

    def __enter__(self) -> BleDirectHubSync:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        self.close()
        return False

    def function_request(
        self,
        actions: dict[str | Actions, int | float],
        time: float = 0,
        loop_on_time: float | None = None,
        loop_off_time: float | None = None,
        toy_id: str | list[str] | None = None,
        stop_previous: bool | None = None,
        timeout: float | None = None,
        *,
        wait_for_completion: bool = True,
    ) -> CommandResponse:
        return run_ble_coroutine(
            self._hub.function_request(
                actions,
                time=time,
                loop_on_time=loop_on_time,
                loop_off_time=loop_off_time,
                toy_id=toy_id,
                stop_previous=stop_previous,
                timeout=timeout,
                wait_for_completion=wait_for_completion,
            )
        )

    def stop(
        self,
        toy_id: str | list[str] | None = None,
        timeout: float | None = None,
    ) -> CommandResponse:
        return run_ble_coroutine(self._hub.stop(toy_id, timeout=timeout))

    def pattern_request_raw(
        self,
        strength: str,
        rule: str = "V:1;F:;S:100#",
        time: float = 0,
        toy_id: str | list[str] | None = None,
        timeout: float | None = None,
        *,
        wait_for_completion: bool = True,
    ) -> CommandResponse:
        return run_ble_coroutine(
            self._hub.pattern_request_raw(
                strength, rule, time, toy_id, timeout, wait_for_completion=wait_for_completion
            )
        )

    def pattern_request(
        self,
        pattern: list[int],
        actions: list[str | Actions] | None = None,
        interval: int = 100,
        time: float = 0,
        toy_id: str | list[str] | None = None,
        timeout: float | None = None,
        *,
        wait_for_completion: bool = True,
    ) -> CommandResponse:
        return run_ble_coroutine(
            self._hub.pattern_request(
                pattern,
                actions,
                interval,
                time,
                toy_id,
                timeout,
                wait_for_completion=wait_for_completion,
            )
        )

    def preset_request(
        self,
        name: str | Presets,
        time: float = 0,
        toy_id: str | list[str] | None = None,
        timeout: float | None = None,
        *,
        open_ended: bool = False,
        wait_for_completion: bool = True,
    ) -> CommandResponse:
        return run_ble_coroutine(
            self._hub.preset_request(
                name,
                time,
                toy_id,
                timeout,
                open_ended=open_ended,
                wait_for_completion=wait_for_completion,
            )
        )

    def position_request(
        self,
        value: int,
        toy_id: str | list[str] | None = None,
        timeout: float | None = None,
    ) -> CommandResponse:
        return run_ble_coroutine(self._hub.position_request(value, toy_id, timeout))

    def pattern_v2_setup(
        self,
        actions: list[dict[str, int]],
        timeout: float | None = None,
    ) -> CommandResponse:
        return run_ble_coroutine(self._hub.pattern_v2_setup(actions, timeout=timeout))

    def pattern_v2_play(
        self,
        toy_id: str | list[str] | None = None,
        start_time: int | None = None,
        offset_time: int | None = None,
        time_ms: float | None = None,
        timeout: float | None = None,
    ) -> CommandResponse:
        return run_ble_coroutine(
            self._hub.pattern_v2_play(
                toy_id,
                start_time=start_time,
                offset_time=offset_time,
                time_ms=time_ms,
                timeout=timeout,
            )
        )

    def pattern_v2_init_play(
        self,
        actions: list[dict[str, int]],
        toy_id: str | list[str] | None = None,
        start_time: int | None = None,
        offset_time: int | None = None,
        stop_previous: int = 0,
        timeout: float | None = None,
    ) -> CommandResponse:
        return run_ble_coroutine(
            self._hub.pattern_v2_init_play(
                actions,
                toy_id=toy_id,
                start_time=start_time,
                offset_time=offset_time,
                stop_previous=stop_previous,
                timeout=timeout,
            )
        )

    def pattern_v2_stop(
        self,
        toy_id: str | list[str] | None = None,
        timeout: float | None = None,
    ) -> CommandResponse:
        return run_ble_coroutine(self._hub.pattern_v2_stop(toy_id, timeout=timeout))

    def pattern_v2_sync_time(self, timeout: float | None = None) -> CommandResponse:
        return run_ble_coroutine(self._hub.pattern_v2_sync_time(timeout=timeout))

    def get_toys(self, *, query_battery: bool = True) -> GetToysResponse:
        """Like LAN ``GetToys``; ``query_battery`` is BLE-only (UART read)."""
        return run_ble_coroutine(self._hub.get_toys(query_battery=query_battery))

    def get_toys_name(self) -> GetToyNameResponse:
        return run_ble_coroutine(self._hub.get_toys_name())

    def send_command(
        self,
        command_data: dict[str, Any],
        timeout: float | None = None,
    ) -> dict[str, Any]:
        return run_ble_coroutine(self._hub.send_command(command_data, timeout=timeout))

    def decode_response(self, response: dict[str, Any] | BaseModel | None) -> str:
        return self._hub.decode_response(response)

    class _PlayContextManager:
        def __init__(
            self,
            hub: BleDirectHubSync,
            actions: dict[str | Actions, int | float],
            *,
            time: float,
            loop_on_time: float | None,
            loop_off_time: float | None,
            toy_id: str | list[str] | None,
            stop_previous: bool | None,
            timeout: float | None,
        ) -> None:
            self._hub = hub
            self._actions = actions
            self._time = time
            self._loop_on_time = loop_on_time
            self._loop_off_time = loop_off_time
            self._toy_id = toy_id
            self._stop_previous = stop_previous
            self._timeout = timeout
            self._response: CommandResponse | None = None

        def __enter__(self) -> CommandResponse:
            self._response = self._hub.function_request(
                self._actions,
                time=self._time,
                loop_on_time=self._loop_on_time,
                loop_off_time=self._loop_off_time,
                toy_id=self._toy_id,
                stop_previous=self._stop_previous,
                timeout=self._timeout,
            )
            return self._response

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            try:
                self._hub.stop(self._toy_id, timeout=self._timeout)
            except LovenseError:
                if exc_type is None:
                    raise
            return False

    def play(
        self,
        actions: dict[str | Actions, int | float],
        *,
        time: float = 0,
        loop_on_time: float | None = None,
        loop_off_time: float | None = None,
        toy_id: str | list[str] | None = None,
        stop_previous: bool | None = None,
        timeout: float | None = None,
    ) -> BleDirectHubSync._PlayContextManager:
        """Like :meth:`LANClient.play` — start on enter, :meth:`stop` on exit."""
        return BleDirectHubSync._PlayContextManager(
            self,
            actions,
            time=time,
            loop_on_time=loop_on_time,
            loop_off_time=loop_off_time,
            toy_id=toy_id,
            stop_previous=stop_previous,
            timeout=timeout,
        )
