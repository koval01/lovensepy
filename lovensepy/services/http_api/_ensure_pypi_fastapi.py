"""Ensure ``sys.modules['fastapi']`` is PyPI FastAPI, not ``lovensepy.services.http_api``.

Bundlers can alias the top-level ``fastapi`` name to our HTTP API package. PyPI
FastAPI then executes ``from fastapi import …`` during its ``__init__``, which
invokes ``lovensepy.services.http_api.__getattr__('create_app')`` while
``http_api.app`` is still loading (circular import).
"""

from __future__ import annotations

import importlib
import sys


def ensure_pypi_fastapi() -> None:
    m: object | None = sys.modules.get("fastapi")
    need_reload = False
    if m is not None:
        name = getattr(m, "__name__", "")
        http_api = sys.modules.get("lovensepy.services.http_api")
        if http_api is not None and m is http_api:
            need_reload = True
        elif name != "fastapi":
            need_reload = True
        else:
            origin = str(getattr(m, "__file__", "") or "").replace("\\", "/")
            if origin and "lovensepy" in origin:
                need_reload = True
    if need_reload:
        for k in list(sys.modules):
            if k == "fastapi" or k.startswith("fastapi."):
                del sys.modules[k]
    importlib.import_module("fastapi")
