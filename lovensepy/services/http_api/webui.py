"""Serve the bundled React control panel at ``/`` (OpenAPI docs live at ``/docs``)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi.applications import FastAPI
from fastapi.responses import HTMLResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

#: Built assets (``frontend/`` → ``npm run build``), shipped inside the wheel.
#: Not named ``webui`` so the directory cannot shadow this module on import.
WEBUI_DIRNAME = "webui_dist"

_IMMUTABLE_DIRS = ("assets/",)
_HTML_NO_STORE = "no-store, max-age=0"
_ASSET_CACHE = "public, max-age=31536000, immutable"


def webui_dir() -> Path:
    """Locate the built UI, including inside PyInstaller/Nuitka bundles."""
    here = Path(__file__).resolve().parent
    candidates = [here / WEBUI_DIRNAME]
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        candidates.append(Path(bundle_root) / "lovensepy" / "services" / "http_api" / WEBUI_DIRNAME)
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return candidates[0]


def webui_available() -> bool:
    return (webui_dir() / "index.html").is_file()


def _wants_html(scope: Scope) -> bool:
    for key, value in scope.get("headers") or ():
        if key == b"accept":
            return b"text/html" in value or b"*/*" in value
    return False


class SinglePageStaticFiles(StaticFiles):
    """Static files with SPA fallback and cache headers tuned for a local service.

    Hashed bundles under ``assets/`` are immutable, while ``index.html`` must never be
    cached: users update the service executable in place and a stale shell would keep
    loading asset URLs that no longer exist.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or not _wants_html(scope):
                raise
            response = await super().get_response("index.html", scope)
        if response.status_code == 404 and _wants_html(scope):
            response = await super().get_response("index.html", scope)
        normalized = path.lstrip("/")
        if any(normalized.startswith(prefix) for prefix in _IMMUTABLE_DIRS):
            response.headers["Cache-Control"] = _ASSET_CACHE
        elif normalized in ("", ".", "index.html") or normalized.endswith(".html"):
            response.headers["Cache-Control"] = _HTML_NO_STORE
        return response


_MISSING_UI_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LovensePy Service</title>
<style>
  :root { color-scheme: dark light; }
  body { margin: 0; min-height: 100vh; display: grid; place-items: center;
         font: 16px/1.6 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
         background: #0b0b0f; color: #e8e8ef; padding: 24px; }
  main { max-width: 40rem; }
  h1 { font-size: 1.5rem; margin-bottom: .25rem; }
  code { background: #1b1b24; padding: .15em .4em; border-radius: .35em; }
  a { color: #f472b6; }
  pre { background: #14141c; padding: 1rem; border-radius: .75rem; overflow-x: auto; }
</style>
</head>
<body>
<main>
  <h1>LovensePy service is running</h1>
  <p>The web control panel is not bundled in this installation.</p>
  <p>Build it from a source checkout:</p>
  <pre>cd frontend
npm install
npm run build</pre>
  <p>Meanwhile the API is fully usable:
     <a href="/docs">interactive docs</a> ·
     <a href="/redoc">ReDoc</a> ·
     <a href="/openapi.json">OpenAPI</a> ·
     <a href="/state">state</a>
  </p>
</main>
</body>
</html>
"""


def mount_webui(app: FastAPI, *, enabled: bool = True) -> bool:
    """Mount the SPA at ``/``. Returns True when built assets were found.

    Must be called after every API route is registered: the mount is a catch-all.
    """
    if not enabled:
        return False

    if not webui_available():

        @app.get("/", include_in_schema=False)
        async def _webui_missing() -> HTMLResponse:
            return HTMLResponse(_MISSING_UI_HTML, headers={"Cache-Control": _HTML_NO_STORE})

        return False

    app.mount(
        "/",
        SinglePageStaticFiles(directory=str(webui_dir()), html=True),
        name="webui",
    )
    return True


def webui_info() -> dict[str, Any]:
    directory = webui_dir()
    return {
        "available": (directory / "index.html").is_file(),
        "directory": str(directory),
    }
