"""HTTP routers for the LovensePy service.

Every router is always registered so the OpenAPI schema is stable and the web UI can
enable a transport at runtime; handlers for a disabled transport answer HTTP 409.
"""

from __future__ import annotations

from fastapi.applications import FastAPI

from . import ble, commands, events, settings, socket_api, system, toys


def register_routes(app: FastAPI) -> None:
    """Attach every API router. Call before mounting the SPA (a catch-all)."""
    app.include_router(system.router)
    app.include_router(settings.router)
    app.include_router(toys.router)
    app.include_router(commands.router)
    app.include_router(ble.router)
    app.include_router(socket_api.router)
    app.include_router(events.router)


__all__ = [
    "ble",
    "commands",
    "events",
    "register_routes",
    "settings",
    "socket_api",
    "system",
    "toys",
]
