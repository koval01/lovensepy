"""FastAPI application: React control panel at ``/``, OpenAPI docs at ``/docs``.

Layout:

- ``/`` — bundled web UI (:mod:`lovensepy.services.http_api.webui`); set
  ``LOVENSE_WEBUI=0`` for an API-only service.
- ``/docs``, ``/redoc``, ``/openapi.json`` — API documentation.
- everything else — the REST/WebSocket API in :mod:`lovensepy.services.http_api.routes`.
"""

# ensure_pypi_fastapi() must run before any `from fastapi...` (Nuitka).
# pylint: disable=wrong-import-order,wrong-import-position

import os
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from ._ensure_pypi_fastapi import ensure_pypi_fastapi

ensure_pypi_fastapi()

from fastapi.applications import FastAPI
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from lovensepy import __version__
from lovensepy.ble_direct.client import LovenseBleAdvertisement

from .access_gate import install_access_gate, is_external_request
from .config import ServiceConfig
from .presence import install_presence_activity
from .routes import register_routes
from .runtime import ServiceRuntime
from .webui import mount_webui

_LOCALHOST_ORIGIN_RE = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"

_DESCRIPTION = """
Control Lovense toys over LAN (Game Mode), direct BLE and the Socket API with
per-motor scheduling.

* **Control panel:** [`/`](/) — no setup required, works from a phone on the same Wi-Fi.
* **Live state:** `GET /state` (one aggregated snapshot) and `WS /ws` (push updates).
* **BLE:** `POST /ble/connect/auto` scans and connects everything; the service keeps
  links alive and reconnects on its own.

Endpoints for a disabled transport answer **409** — enable one at runtime with
`POST /config/lan-ip`, `POST /config/socket` or `POST /config/transports`.
"""


def _install_cors(fastapi_app: FastAPI, cfg: ServiceConfig) -> None:
    """Same-origin UI needs no CORS; this only opens the API to explicit extra origins.

    A permissive default would let any visited web page drive a stranger's toys, so
    ``*`` stays opt-in and only local development origins are allowed out of the box.
    """
    allow_all = "*" in cfg.cors_origins
    origins = [origin for origin in cfg.cors_origins if origin != "*"]
    fastapi_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if allow_all else origins,
        allow_origin_regex=None
        if allow_all
        else (_LOCALHOST_ORIGIN_RE if cfg.cors_allow_localhost else None),
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
        max_age=600,
    )


def create_app(
    config: ServiceConfig | None = None,
    *,
    on_ble_advertisement: Callable[[LovenseBleAdvertisement], None] | None = None,
    on_ble_advertisement_async: Callable[[LovenseBleAdvertisement], Awaitable[None]] | None = None,
) -> FastAPI:
    """Build the service app.

    Transports with missing prerequisites are disabled instead of raising, so the app
    always starts and the web UI can finish the setup (LAN IP, Socket credentials).
    """
    runtime = ServiceRuntime(
        config or ServiceConfig.from_env(),
        on_advertisement=on_ble_advertisement,
        on_advertisement_async=on_ble_advertisement_async,
    )

    @asynccontextmanager
    async def lifespan(fastapi_app: FastAPI):
        runtime.attach(fastapi_app)
        await runtime.start()
        try:
            yield
        finally:
            await runtime.aclose()

    fastapi_app = FastAPI(
        title="LovensePy Service API",
        description=_DESCRIPTION,
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    # Attach before startup so `create_app(...)` users can inspect state without a lifespan.
    runtime.attach(fastapi_app)

    _install_cors(fastapi_app, runtime.cfg)
    install_presence_activity(fastapi_app, runtime)
    _install_host_only_docs(fastapi_app)
    # Gate is outermost (added last): external visitors see /auth before any route.
    install_access_gate(fastapi_app, runtime.gate)
    register_routes(fastapi_app)
    mount_webui(fastapi_app, enabled=runtime.cfg.webui_enabled)
    return fastapi_app


_HOST_DOCS_PATHS = frozenset({"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"})


def _install_host_only_docs(fastapi_app: FastAPI) -> None:
    """OpenAPI / Swagger stay on the LAN — tunnel visitors only get the control panel."""

    @fastapi_app.middleware("http")
    async def _host_only_docs(request, call_next):  # noqa: ANN001
        path = request.url.path.rstrip("/") or "/"
        if path in _HOST_DOCS_PATHS or path.startswith("/docs"):
            if is_external_request(request.scope, request.headers):
                from fastapi.responses import JSONResponse

                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": (
                            "API documentation is only available from the local network."
                        )
                    },
                )
        return await call_next(request)


_CONFIG_ERROR_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LovensePy Service — configuration error</title>
<style>
  :root {{ color-scheme: dark light; }}
  body {{ margin:0; min-height:100vh; display:grid; place-items:center; padding:24px;
         font:16px/1.6 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
         background:#0b0b0f; color:#e8e8ef; }}
  main {{ max-width:40rem; }}
  h1 {{ font-size:1.4rem; }}
  pre {{ background:#14141c; padding:1rem; border-radius:.75rem; white-space:pre-wrap; }}
  a {{ color:#f472b6; }}
</style></head>
<body><main>
  <h1>Configuration error</h1>
  <pre>{detail}</pre>
  <p>Fix the <code>LOVENSE_*</code> environment variables and restart.
     <a href="/docs">API docs</a> · <a href="/config-error">details as JSON</a></p>
</main></body></html>
"""


def _config_error_app(detail: str) -> FastAPI:
    """Health-only app: the server still starts so the error is visible in a browser."""
    app_err = FastAPI(
        title="LovensePy Service API",
        description="Configuration error.",
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    @app_err.get("/", include_in_schema=False)
    def config_error_page() -> HTMLResponse:
        return HTMLResponse(
            _CONFIG_ERROR_HTML.format(detail=detail),
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )

    @app_err.get("/config-error")
    def config_error_json() -> dict[str, Any]:
        return {
            "status": "error",
            "configured": False,
            "detail": detail,
            "hint": (
                "Service started without transports. Configure LOVENSE_* env vars "
                "to enable LAN/BLE/Socket control."
            ),
        }

    @app_err.get("/health")
    def health_error() -> dict[str, str]:
        return {"status": "ok", "configured": "false"}

    @app_err.get("/meta")
    def meta_error() -> dict[str, Any]:
        mode = os.environ.get("LOVENSE_SERVICE_MODE", "lan").strip().lower() or "lan"
        return {
            "mode": mode,
            "transports": {"lan": False, "ble": False, "socket": False},
            "configured": False,
            "detail": detail,
        }

    @app_err.api_route("/{_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def fail_all(_path: str) -> None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Service is running in health-only mode. Configure LOVENSE_* env vars "
                "to enable control."
            ),
        )

    return app_err


try:
    _svc_cfg = ServiceConfig.from_env()
    app = create_app(_svc_cfg)
except ValueError as _config_exc:
    _config_error_detail = str(_config_exc)
    app = _config_error_app(_config_error_detail)
