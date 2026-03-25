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
- macOS `.app` (no terminal): when stdin is not a TTY, a minimal Cocoa menu is used so
  you can quit with ⌘Q or Dock → Quit (closing the browser tab does not stop the server).
  Set `LOVENSE_MACOS_GUI_MENU=0` to force the plain blocking server loop instead.
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
from typing import Any, Final

import uvicorn

_PORT_MIN: Final[int] = 10000
_PORT_MAX: Final[int] = 50000

# Populated only while the macOS AppKit quit path is active (see `_macos_quit_state`).
_macos_quit_state: dict[str, Any] = {}


def _use_macos_quit_menu() -> bool:
    """Finder-launched `.app` has no TTY — offer Quit via Dock / ⌘Q instead of only kill -9."""
    if sys.platform != "darwin":
        return False
    raw = (os.environ.get("LOVENSE_MACOS_GUI_MENU") or "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    return not sys.stdin.isatty()


def _run_uvicorn_with_macos_quit_menu(
    app: object,
    *,
    host: str,
    port: int,
    log_level: str,
) -> None:
    """Run uvicorn in a worker thread; main thread is NSApplication (Quit stops the server)."""
    try:
        from AppKit import (  # type: ignore[import-untyped]
            NSApplication,
            NSApplicationActivationPolicyRegular,
            NSMenu,
            NSMenuItem,
            NSTerminateNow,
        )
        from Foundation import NSObject  # type: ignore[import-untyped]
        from PyObjCTools import AppHelper  # type: ignore[import-untyped]
    except ImportError:
        uvicorn.run(
            app,
            host=host,
            port=port,
            log_level=log_level,
            workers=1,
            reload=False,
        )
        return

    class _AppDelegate(NSObject):
        def applicationShouldTerminate_(self, sender: object) -> int:  # noqa: N802
            srv = _macos_quit_state.get("server")
            worker = _macos_quit_state.get("worker")
            if srv is not None:
                srv.should_exit = True
            if worker is not None and worker.is_alive():
                worker.join(timeout=45.0)
            return NSTerminateNow

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=log_level,
        workers=1,
        reload=False,
    )
    server = uvicorn.Server(config)
    worker = threading.Thread(target=server.run, name="uvicorn", daemon=False)

    ns_app = NSApplication.sharedApplication()
    delegate = _AppDelegate.alloc().init()
    ns_app.setDelegate_(delegate)

    menubar = NSMenu.alloc().init()
    app_menu_item = NSMenuItem.alloc().init()
    menubar.addItem_(app_menu_item)
    app_menu = NSMenu.alloc().initWithTitle_("LovensePy Service")
    quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Quit LovensePy Service",
        "terminate:",
        "q",
    )
    app_menu.addItem_(quit_item)
    app_menu_item.setSubmenu_(app_menu)
    ns_app.setMainMenu_(menubar)

    ns_app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    ns_app.activateIgnoringOtherApps_(True)

    _macos_quit_state.clear()
    _macos_quit_state["server"] = server
    _macos_quit_state["worker"] = worker
    worker.start()

    print(
        "LovensePy Service is running. Closing the browser does not stop the server.\n"
        "Quit: press ⌘Q, or right-click the Dock icon → Quit."
    )

    try:
        AppHelper.runEventLoop()
    finally:
        _macos_quit_state.clear()


def _run_uvicorn_blocking(
    app: object,
    *,
    host: str,
    port: int,
    log_level: str,
) -> None:
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=log_level,
        workers=1,
        reload=False,
    )


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

    from lovensepy.services.http_api._ensure_pypi_fastapi import ensure_pypi_fastapi

    ensure_pypi_fastapi()

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
    if sys.stdin.isatty():
        print("Press Ctrl+C in this terminal to stop the server.")

    if _use_macos_quit_menu():
        _run_uvicorn_with_macos_quit_menu(app, host=host, port=port, log_level=log_level)
    else:
        _run_uvicorn_blocking(app, host=host, port=port, log_level=log_level)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        _report_launch_failure(exc)
        raise SystemExit(1) from exc
