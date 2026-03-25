"""Higher-level service adapters shipped with LovensePy (HTTP, …).

The FastAPI LAN/BLE server lives in :mod:`lovensepy.services.fastapi`.
Install optional extra: ``pip install 'lovensepy[service]'``.
"""

from __future__ import annotations

from .http_api import (
    ControlScheduler,
    LovenseControlBackend,
    ServiceConfig,
    create_app,
)

__all__ = [
    "ControlScheduler",
    "LovenseControlBackend",
    "ServiceConfig",
    "create_app",
    "fastapi",
]


def __getattr__(name: str):
    # Lazy alias: eager `import http_api as fastapi` interacted badly with the real
    # `fastapi` package during Nuitka onefile/app startup (partial init / __all__).
    if name == "fastapi":
        from . import http_api

        return http_api
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
