#!/usr/bin/env python3
"""
Compatibility shim for the LovensePy FastAPI service.

The implementation lives in :mod:`lovensepy.services.fastapi`. This module re-exports
``app`` and ``create_app`` so older ``uvicorn examples.fastapi_lan_api:app``
commands keep working.

Prefer:

    uvicorn lovensepy.services.fastapi.app:app --host 0.0.0.0 --port 8000

Install: ``pip install 'lovensepy[service]'`` (and ``'lovensepy[ble]'`` for BLE mode).

Environment (LAN, default):

- ``LOVENSE_LAN_IP`` — Game Mode host
- ``LOVENSE_SERVICE_MODE=lan`` (default)
- Optional: ``LOVENSE_LAN_PORT``, ``LOVENSE_APP_NAME``, ``LOVENSE_SESSION_MAX_SEC``, ``LOVENSE_TOY_IDS``

BLE mode:

- ``LOVENSE_SERVICE_MODE=ble``
- Optional: ``LOVENSE_BLE_SCAN_TIMEOUT``, ``LOVENSE_BLE_SCAN_PREFIX`` (empty = all names),
  ``LOVENSE_BLE_ADVERT_MONITOR``, ``LOVENSE_BLE_ADVERT_MONITOR_INTERVAL``
"""

from __future__ import annotations

import warnings

warnings.warn(
    "examples.fastapi_lan_api is a shim; use lovensepy.services.fastapi "
    "(e.g. uvicorn lovensepy.services.fastapi.app:app).",
    DeprecationWarning,
    stacklevel=2,
)

from lovensepy.services.fastapi.app import app, create_app
from lovensepy.services.fastapi.config import ServiceConfig

# Historical name from the old example module.
APIConfig = ServiceConfig

__all__ = ["APIConfig", "ServiceConfig", "app", "create_app"]
