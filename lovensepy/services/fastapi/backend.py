"""Async control surface shared by LAN and BLE transports (FastAPI service).

Method shapes match :class:`~lovensepy.standard.async_base.LovenseAsyncControlClient`
for the subset used by :class:`~lovensepy.services.fastapi.scheduler.ControlScheduler`
and route handlers (swap ``AsyncLANClient``, ``AsyncServerClient``, or ``BleDirectHub``).
"""

from __future__ import annotations

from typing import Protocol

from lovensepy._constants import Actions, Presets
from lovensepy._models import CommandResponse, GetToysResponse


class LovenseControlBackend(Protocol):
    async def get_toys(
        self,
        timeout: float | None = None,
        *,
        query_battery: bool = True,
    ) -> GetToysResponse: ...

    async def function_request(
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
    ) -> CommandResponse: ...

    async def stop(
        self, toy_id: str | list[str] | None = None, timeout: float | None = None
    ) -> CommandResponse: ...

    async def pattern_request(
        self,
        pattern: list[int],
        actions: list[str | Actions] | None = None,
        interval: int = 100,
        time: float = 0,
        toy_id: str | list[str] | None = None,
        timeout: float | None = None,
        *,
        wait_for_completion: bool = True,
    ) -> CommandResponse: ...

    async def preset_request(
        self,
        name: str | Presets,
        time: float = 0,
        toy_id: str | list[str] | None = None,
        timeout: float | None = None,
        *,
        open_ended: bool = False,
        wait_for_completion: bool = True,
    ) -> CommandResponse: ...
