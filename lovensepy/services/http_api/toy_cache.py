"""Short-lived toy-list cache for status polling (``GET /state``, ``/ws``)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from .backend import LovenseControlBackend
from .util import as_dict


class ToyCache:
    """Single-flight, TTL cached ``get_toys()`` snapshot.

    The control panel polls status about once per second and several clients (desktop
    plus phone) can watch at the same time. Hitting LAN HTTP or BLE UART that often is
    wasteful and, on BLE, actively harmful. This cache collapses concurrent readers
    into one backend call and reuses the result for ``ttl`` seconds.
    """

    def __init__(self, backend: LovenseControlBackend, *, ttl: float = 2.0) -> None:
        self._backend = backend
        self._ttl = max(0.0, float(ttl))
        self._lock = asyncio.Lock()
        self._value: dict[str, Any] | None = None
        self._fetched_mono: float = 0.0
        self._error: str | None = None

    @property
    def last_error(self) -> str | None:
        return self._error

    def set_backend(self, backend: LovenseControlBackend) -> None:
        self._backend = backend
        self.invalidate()

    def invalidate(self) -> None:
        self._value = None
        self._fetched_mono = 0.0

    def _fresh(self) -> bool:
        if self._value is None:
            return False
        return (time.monotonic() - self._fetched_mono) <= self._ttl

    async def get(self, *, force: bool = False, timeout: float = 4.0) -> dict[str, Any]:
        """Return a ``GetToys``-shaped dict, cached for ``ttl`` seconds.

        Backend failures are swallowed: the last good snapshot (or an empty toy list)
        is returned and the reason is exposed through :attr:`last_error` so status
        endpoints stay responsive when a transport is down.
        """
        if not force and self._fresh():
            return dict(self._value or {})

        async with self._lock:
            if not force and self._fresh():
                return dict(self._value or {})
            try:
                response = await asyncio.wait_for(
                    self._backend.get_toys(query_battery=False), timeout=timeout
                )
                self._value = as_dict(response)
                self._error = None
            except Exception as exc:
                self._error = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
                if self._value is None:
                    self._value = {"code": 200, "type": "OK", "data": {"toys": []}}
            self._fetched_mono = time.monotonic()
            return dict(self._value or {})


def toy_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract the ``data.toys`` rows from a ``GetToys``-shaped dict."""
    data = snapshot.get("data")
    if not isinstance(data, dict):
        return []
    toys = data.get("toys")
    if not isinstance(toys, list):
        return []
    return [row for row in toys if isinstance(row, dict)]
