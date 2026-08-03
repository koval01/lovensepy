"""Shared HTTP error mapping for the service routes."""

from __future__ import annotations

from typing import NoReturn

from fastapi.exceptions import HTTPException

from lovensepy import LovenseError

from .scheduler import ControlScheduler

SHUTTING_DOWN = "Server is shutting down."


def ensure_scheduler_open(scheduler: ControlScheduler | None) -> ControlScheduler:
    """Return a usable scheduler or fail with 503 during shutdown."""
    if scheduler is None or scheduler.closed:
        raise HTTPException(status_code=503, detail=SHUTTING_DOWN)
    return scheduler


def raise_api_error(exc: Exception, *, value_error_status: int = 400) -> NoReturn:
    """Map library exceptions to HTTP status codes (502 device, 400 input, 503 shutdown)."""
    if isinstance(exc, LovenseError):
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=value_error_status, detail=str(exc)) from exc
    if isinstance(exc, RuntimeError) and str(exc) == "scheduler_closed":
        raise HTTPException(status_code=503, detail=SHUTTING_DOWN) from exc
    raise exc
