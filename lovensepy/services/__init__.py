"""Higher-level service adapters shipped with LovensePy (HTTP, …).

The FastAPI LAN/BLE server lives in :mod:`lovensepy.services.fastapi`.
Install optional extra: ``pip install 'lovensepy[service]'``.
"""

from __future__ import annotations

import importlib

__all__ = [
    "ControlScheduler",
    "LovenseControlBackend",
    "ServiceConfig",
    "create_app",
    "fastapi",
    "http_api",
]

_LAZY_FROM_HTTP_API = frozenset(
    {
        "create_app",
        "ControlScheduler",
        "LovenseControlBackend",
        "ServiceConfig",
    }
)


def __getattr__(name: str):
    # No eager imports: loading `http_api` pulls `fastapi` (PyPI); eager
    # `from .http_api import …` here caused circular imports in Nuitka .app.
    # Use importlib (not `from . import http_api`) to avoid RecursionError when
    # the fastapi shim does `from lovensepy.services import http_api`.
    if name in _LAZY_FROM_HTTP_API or name in ("fastapi", "http_api"):
        # Literal module name (not f"{__name__}.http_api") — satisfies static/security audits.
        http_api = importlib.import_module("lovensepy.services.http_api")
        if name in ("fastapi", "http_api"):
            return http_api
        return getattr(http_api, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
