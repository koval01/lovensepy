"""FastAPI HTTP service: LAN (Game Mode) or direct BLE.

Part of :mod:`lovensepy.services`. Install optional extra: ``pip install 'lovensepy[service]'``.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "create_app",
    "ControlScheduler",
    "LovenseAsyncControlClient",
    "LovenseControlBackend",
    "ServiceConfig",
]


def create_app(*args: Any, **kwargs: Any) -> Any:
    """Build the HTTP service app; body imports ``.app`` only when called.

    A real module attribute (not :pep:`562` ``__getattr__``) avoids Nuitka/frozen
    cases where PyPI FastAPI's ``from fastapi import …`` wrongly resolves to this
    package: accessing ``create_app`` must not import ``http_api.app`` while that
    module is still loading.
    """
    from .app import create_app as _create_app

    return _create_app(*args, **kwargs)


def __getattr__(name: str):
    if name == "LovenseControlBackend":
        from .backend import LovenseControlBackend

        return LovenseControlBackend
    if name == "ServiceConfig":
        from .config import ServiceConfig

        return ServiceConfig
    if name == "ControlScheduler":
        from .scheduler import ControlScheduler

        return ControlScheduler
    if name == "LovenseAsyncControlClient":
        from lovensepy.standard.async_base import LovenseAsyncControlClient

        return LovenseAsyncControlClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
