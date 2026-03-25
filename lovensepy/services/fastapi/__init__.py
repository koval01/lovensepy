"""Backward-compatibility shim.

The service implementation was moved to :mod:`lovensepy.services.http_api` to avoid
name collisions with the external `fastapi` package in standalone build tools.
"""

from __future__ import annotations

from lovensepy.services import http_api
from lovensepy.services.http_api import *  # noqa: F403 pylint: disable=wildcard-import,unused-wildcard-import
from lovensepy.services.http_api.app import app

__all__ = [*http_api.__all__, "app"]
