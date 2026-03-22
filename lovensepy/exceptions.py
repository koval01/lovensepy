"""
Exception hierarchy for Lovense API failures.

The library previously returned ``None`` on transport/HTTP failures; the modern
API raises typed exceptions instead.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "LovenseError",
    "LovenseNetworkError",
    "LovenseAuthError",
    "LovenseDeviceOfflineError",
    "LovenseTimeoutError",
    "LovenseResponseParseError",
    "LovenseBLEError",
]


class LovenseError(Exception):
    """Base class for all Lovensepy errors."""


class LovenseNetworkError(LovenseError):
    """Raised when a network-level operation fails."""

    def __init__(self, message: str, *, endpoint: str | None = None, payload: Any = None) -> None:
        super().__init__(message)
        self.endpoint = endpoint
        self.payload = payload


class LovenseAuthError(LovenseNetworkError):
    """Raised on authentication/authorization failures (or trusted-session mismatch)."""


class LovenseDeviceOfflineError(LovenseNetworkError):
    """Raised when the local app/toy (or the network peer) is unreachable."""


class LovenseTimeoutError(LovenseDeviceOfflineError):
    """Raised when a network request times out."""


class LovenseResponseParseError(LovenseNetworkError):
    """Raised when the server response cannot be parsed as expected JSON."""


class LovenseBLEError(LovenseDeviceOfflineError):
    """Direct BLE failure, missing ``bleak``, unknown GATT TX UUID, or not connected."""
