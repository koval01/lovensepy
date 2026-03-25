"""FastAPI HTTP service: LAN (Game Mode) or direct BLE.

Part of :mod:`lovensepy.services`. Install optional extra: ``pip install 'lovensepy[service]'``.
"""

from __future__ import annotations

# Define before importing .app (pulls third-party `fastapi`) so the module is never
# "partially initialized" without __all__ during frozen/Nuitka import resolution.
__all__ = [
    "create_app",
    "ControlScheduler",
    "LovenseAsyncControlClient",
    "LovenseControlBackend",
    "ServiceConfig",
]

from lovensepy.standard.async_base import LovenseAsyncControlClient

from .app import create_app
from .backend import LovenseControlBackend
from .config import ServiceConfig
from .scheduler import ControlScheduler
