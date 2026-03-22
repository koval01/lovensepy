"""Higher-level service adapters shipped with LovensePy (HTTP, …).

The FastAPI LAN/BLE server lives in :mod:`lovensepy.services.fastapi`.
Install optional extra: ``pip install 'lovensepy[service]'``.
"""

from __future__ import annotations

from . import fastapi
from .fastapi import (
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
