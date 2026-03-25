"""
Executable entrypoint for the bundled LovensePy service.

Intended usage (development):
    python -m lovensepy.services.launcher

With Windows exe build (PyInstaller):
    lovensepy-service.exe

Configuration:
- FastAPI service mode + transports come from
  :class:`lovensepy.services.http_api.config.ServiceConfig` environment variables
  (e.g. `LOVENSE_SERVICE_MODE`, `LOVENSE_LAN_IP`, `LOVENSE_DEV_TOKEN`, ...).
- Uvicorn runtime is controlled by:
  - `LOVENSE_HOST` (default `0.0.0.0`)
  - `LOVENSE_PORT` (default `8000`)
  - `LOVENSE_LOG_LEVEL` (default `info`)
"""

from __future__ import annotations

import contextlib
import os
import secrets
import socket
import sys
import threading
import traceback
import webbrowser
from pathlib import Path
from typing import Final

import uvicorn

_PORT_MIN: Final[int] = 10000
_PORT_MAX: Final[int] = 50000


def _is_port_free(port: int, host: str) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _report_launch_failure(exc: Exception) -> None:
    """When the GUI .app exits immediately, stderr is invisible — log and alert (macOS)."""
    lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
    text = "".join(lines)
    log_path = Path.home() / "Library" / "Logs" / "LovensePy-Service.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(text)
            if not text.endswith("\n"):
                f.write("\n")
    except OSError:
        pass
    if sys.platform == "darwin":
        import subprocess  # nosec B404

        msg = f"LovensePy Service quit with an error. See log file: {log_path}"
        esc = msg.replace("\\", "\\\\").replace('"', '\\"')
        # Fixed argv: AppleScript alert; path from Path.home() only, escaped for osascript.
        subprocess.run(  # nosec B603
            [
                "/usr/bin/osascript",
                "-e",
                f'display alert "LovensePy Service" message "{esc}"',
            ],
            check=False,
        )


def _choose_free_port(host: str, *, pmin: int = _PORT_MIN, pmax: int = _PORT_MAX) -> int:
    # Choose a random start offset and probe forward with wrap-around.
    start = secrets.randbelow(pmax - pmin + 1) + pmin
    for i in range(pmin, pmax + 1):
        port = pmin + ((start - pmin + i) % (pmax - pmin + 1))
        if _is_port_free(port, host):
            return port
    # Should be extremely unlikely unless the range is fully occupied.
    raise RuntimeError(f"No free TCP ports found in range {pmin}..{pmax}")


def main() -> None:
    # For the "download and run without env" UX:
    # default to `hybrid` so the service exposes BLE/HTTP controls out of the box.
    # Missing Socket credentials and missing LAN_IP are handled by the FastAPI app
    # in a relaxed way (LAN can be configured later via handler).
    os.environ.setdefault("LOVENSE_SERVICE_MODE", "hybrid")

    from lovensepy.services.http_api.app import app as fastapi_app

    host = (
        os.environ.get("LOVENSE_HOST", "0.0.0.0").strip() or "0.0.0.0"  # nosec B104
    )
    forced_port_raw = (os.environ.get("LOVENSE_PORT") or "").strip()
    if forced_port_raw:
        port = int(forced_port_raw)
    else:
        port = _choose_free_port(host="127.0.0.1")

    log_level = os.environ.get("LOVENSE_LOG_LEVEL", "info").strip() or "info"

    # Important: do not call create_app() here.
    # In the "no env provided" case create_app(ServiceConfig.from_env()) would fail and crash.
    # The module-level `app` already falls back to a config-error FastAPI app.
    app = fastapi_app

    # Open browser to the docs root immediately after the server starts.
    open_browser = os.environ.get("LOVENSE_OPEN_BROWSER", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    if open_browser:
        url = f"http://127.0.0.1:{port}/"

        def _open() -> None:
            with contextlib.suppress(Exception):
                webbrowser.open(url, new=0, autoraise=True)

        threading.Timer(1.0, _open).start()

    print(f"Open http://127.0.0.1:{port}/ in your browser.")
    print("LovensePy service is starting...")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=log_level,
        # Workers/reload are intentionally disabled for bundled exe.
        workers=1,
        reload=False,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        _report_launch_failure(exc)
        raise SystemExit(1) from exc
