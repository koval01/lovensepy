"""
Abstract base for async Lovense control clients.

Subclasses share the same high-level API as :class:`~lovensepy.standard.async_lan.AsyncLANClient`
so application code can swap ``AsyncServerClient``, ``AsyncLANClient``,
:class:`~lovensepy.ble_direct.client.BleDirectClient`, or
:class:`~lovensepy.ble_direct.hub.BleDirectHub` by changing construction only. Sync
:class:`~lovensepy.standard.server.ServerClient` /
:class:`~lovensepy.standard.lan.LANClient` remain separate for blocking scripts.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from .._constants import Actions, Presets
from .._models import CommandResponse, GetToyNameResponse, GetToysResponse

__all__ = ["LovenseAsyncControlClient"]


class LovenseAsyncControlClient(ABC):
    """Async control surface shared by Standard API (cloud), LAN, and direct BLE."""

    @abstractmethod
    async def aclose(self) -> None:
        """Release transports (HTTP session, BLE links, etc.)."""

    @abstractmethod
    async def send_command(
        self,
        command_data: dict[str, Any],
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Send a raw LAN-shaped command dict (``command`` key, payload fields)."""

    @abstractmethod
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
    ) -> CommandResponse:
        """Motor ``Function`` command (levels, optional timed hold / loop)."""

    @abstractmethod
    async def stop(
        self,
        toy_id: str | list[str] | None = None,
        timeout: float | None = None,
    ) -> CommandResponse:
        """Stop motors / pattern for the given toy(s)."""

    @abstractmethod
    async def pattern_request_raw(
        self,
        strength: str,
        rule: str = "V:1;F:;S:100#",
        time: float = 0,
        toy_id: str | list[str] | None = None,
        timeout: float | None = None,
        *,
        wait_for_completion: bool = True,
    ) -> CommandResponse:
        """``Pattern`` with raw ``strength`` and ``rule`` strings."""

    @abstractmethod
    async def pattern_request(
        self,
        pattern: list[int] | str,
        actions: list[str | Actions] | str | None = None,
        interval: int = 100,
        time: float = 0,
        toy_id: str | list[str] | None = None,
        timeout: float | None = None,
        *,
        wait_for_completion: bool = True,
    ) -> CommandResponse:
        """Pattern from a level list, or raw ``rule`` + ``strength`` strings (server only)."""

    @abstractmethod
    async def preset_request(
        self,
        name: str | Presets,
        time: float = 0,
        toy_id: str | list[str] | None = None,
        timeout: float | None = None,
        *,
        open_ended: bool = False,
        wait_for_completion: bool = True,
    ) -> CommandResponse:
        """Built-in preset / Pat slot."""

    @abstractmethod
    async def position_request(
        self,
        value: int,
        toy_id: str | list[str] | None = None,
        timeout: float | None = None,
    ) -> CommandResponse:
        """Position (0–100) for supported hardware."""

    @abstractmethod
    async def pattern_v2_setup(
        self,
        actions: list[dict[str, int]],
        timeout: float | None = None,
    ) -> CommandResponse:
        """PatternV2 Setup."""

    @abstractmethod
    async def pattern_v2_play(
        self,
        toy_id: str | list[str] | None = None,
        start_time: int | None = None,
        offset_time: int | None = None,
        time_ms: float | None = None,
        timeout: float | None = None,
    ) -> CommandResponse:
        """PatternV2 Play."""

    @abstractmethod
    async def pattern_v2_init_play(
        self,
        actions: list[dict[str, int]],
        toy_id: str | list[str] | None = None,
        start_time: int | None = None,
        offset_time: int | None = None,
        stop_previous: int = 0,
        timeout: float | None = None,
    ) -> CommandResponse:
        """PatternV2 InitPlay."""

    @abstractmethod
    async def pattern_v2_stop(
        self,
        toy_id: str | list[str] | None = None,
        timeout: float | None = None,
    ) -> CommandResponse:
        """PatternV2 Stop."""

    @abstractmethod
    async def pattern_v2_sync_time(self, timeout: float | None = None) -> CommandResponse:
        """PatternV2 SyncTime."""

    @abstractmethod
    async def get_toys(
        self,
        timeout: float | None = None,
        *,
        query_battery: bool = True,
    ) -> GetToysResponse:
        """Connected toys (``query_battery`` is BLE-hub specific; others may ignore)."""

    @abstractmethod
    async def get_toys_name(self, timeout: float | None = None) -> GetToyNameResponse:
        """Display names for connected toys."""

    @abstractmethod
    def decode_response(self, response: dict[str, Any] | BaseModel | None) -> str:
        """Human-readable summary of an API response."""

    @abstractmethod
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
    ) -> Any:
        """Async context manager: run ``function_request`` on enter, ``stop`` on exit."""
