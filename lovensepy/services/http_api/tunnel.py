"""Managed Cloudflare quick tunnel (``cloudflared tunnel --url …``).

Quick tunnels give a random ``https://*.trycloudflare.com`` URL without an account.
That is convenient for opening the control panel from a phone that is *not* on the
same Wi-Fi, but the URL is public for as long as the tunnel runs — treat it as a
temporary share link, not a permanent remote-control endpoint.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import shutil
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

# cloudflared prints the URL inside a box; also accept a bare URL on its own line.
_TUNNEL_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.IGNORECASE)

_BACKOFF_BASE_SEC = 2.0
_BACKOFF_FACTOR = 1.7
_BACKOFF_MAX_SEC = 60.0


def resolve_cloudflared_binary(explicit: str | None = None) -> str | None:
    """Return an absolute path to ``cloudflared``, or ``None`` if it is not installed."""
    candidates: list[str] = []
    if explicit and explicit.strip():
        candidates.append(explicit.strip())
    env = (os.environ.get("LOVENSE_CLOUDFLARED_BIN") or "").strip()
    if env:
        candidates.append(env)
    which = shutil.which("cloudflared")
    if which:
        candidates.append(which)
    # Common Homebrew / package locations when PATH is thin (GUI .app launches).
    candidates.extend(
        (
            "/opt/homebrew/bin/cloudflared",
            "/usr/local/bin/cloudflared",
            str(Path.home() / ".local" / "bin" / "cloudflared"),
        )
    )
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        path = Path(candidate).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path.resolve())
    return None


@dataclass
class _TunnelState:
    desired: bool = False
    url: str | None = None
    local_url: str | None = None
    pid: int | None = None
    last_error: str | None = None
    started_mono: float | None = None
    restarts: int = 0
    history: list[str] = field(default_factory=list)

    def note(self, message: str) -> None:
        self.history.append(message)
        del self.history[:-8]


class CloudflaredTunnel:
    """Owns one ``cloudflared`` child process and keeps it alive while desired."""

    def __init__(
        self,
        *,
        local_url_provider: Callable[[], str],
        binary_provider: Callable[[], str | None] | None = None,
        on_change: Callable[[], None] | None = None,
        auto_restart: bool = True,
    ) -> None:
        self._local_url_provider = local_url_provider
        self._binary_provider = binary_provider or resolve_cloudflared_binary
        self._on_change = on_change
        self._auto_restart = auto_restart
        self._state = _TunnelState()
        self._task: asyncio.Task[None] | None = None
        self._proc: asyncio.subprocess.Process | None = None
        self._stop = asyncio.Event()
        self._url_ready = asyncio.Event()

    # --- lifecycle -----------------------------------------------------------

    @property
    def running(self) -> bool:
        proc = self._proc
        return proc is not None and proc.returncode is None

    @property
    def url(self) -> str | None:
        return self._state.url

    def status(self) -> dict[str, Any]:
        binary = self._binary_provider()
        st = self._state
        return {
            "available": binary is not None,
            "binary": binary,
            "desired": st.desired,
            "running": self.running,
            "url": st.url,
            "local_url": st.local_url,
            "pid": st.pid if self.running else None,
            "last_error": st.last_error,
            "restarts": st.restarts,
            "uptime_sec": (
                round(time.monotonic() - st.started_mono, 1)
                if st.started_mono is not None and self.running
                else None
            ),
            "recent": list(st.history),
        }

    async def start(self, *, wait_for_url: bool = True) -> dict[str, Any]:
        """Ensure the tunnel is up. Idempotent when already running with a URL.

        ``wait_for_url=False`` is for service startup: spawn cloudflared in the
        background so uvicorn becomes ready immediately; the UI polls for the URL.
        """
        binary = self._binary_provider()
        if binary is None:
            raise FileNotFoundError(
                "cloudflared is not installed (or not on PATH). "
                "Install it from https://developers.cloudflare.com/cloudflare-one/"
                "connections/connect-networks/downloads/ then retry."
            )
        local_url = self._local_url_provider().rstrip("/")
        if not local_url:
            raise ValueError("Cannot start a tunnel: local service URL is unknown.")

        self._state.desired = True
        self._state.local_url = local_url
        self._state.last_error = None
        self._state.note(f"start requested → {local_url}")
        self._changed()

        if self._task is None or self._task.done():
            self._stop = asyncio.Event()
            self._url_ready = asyncio.Event()
            self._task = asyncio.create_task(self._loop(), name="lovensepy:cloudflared")

        if wait_for_url:
            # UI / API callers want a QR code immediately.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._url_ready.wait(), timeout=25.0)
            status = self.status()
            if status["url"] is None and status["last_error"]:
                raise RuntimeError(status["last_error"])
            return status
        return self.status()

    async def stop(self) -> dict[str, Any]:
        self._state.desired = False
        self._state.note("stop requested")
        self._stop.set()
        await self._kill_proc()
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._state.url = None
        self._state.pid = None
        self._state.started_mono = None
        self._changed()
        return self.status()

    async def aclose(self) -> None:
        await self.stop()

    # --- worker --------------------------------------------------------------

    async def _loop(self) -> None:
        attempt = 0
        while self._state.desired and not self._stop.is_set():
            try:
                await self._run_once()
                attempt = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._state.last_error = (
                    f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
                )
                self._state.note(f"failed: {self._state.last_error}")
                self._changed()
                _logger.warning("cloudflared tunnel failed: %s", self._state.last_error)

            if not self._state.desired or self._stop.is_set() or not self._auto_restart:
                break

            attempt += 1
            self._state.restarts += 1
            delay = min(_BACKOFF_MAX_SEC, _BACKOFF_BASE_SEC * (_BACKOFF_FACTOR ** (attempt - 1)))
            self._state.note(f"restarting in {delay:.1f}s")
            self._changed()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
                break
            except TimeoutError:
                continue

    async def _run_once(self) -> None:
        binary = self._binary_provider()
        if binary is None:
            raise FileNotFoundError("cloudflared binary disappeared")
        local_url = self._local_url_provider().rstrip("/")
        self._state.local_url = local_url
        self._state.url = None
        # Do not replace ``_url_ready`` here — ``start()`` may already be waiting on it.

        proc = await asyncio.create_subprocess_exec(
            binary,
            "tunnel",
            "--url",
            local_url,
            "--no-autoupdate",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        self._proc = proc
        self._state.pid = proc.pid
        self._state.started_mono = time.monotonic()
        self._state.note(f"spawned pid={proc.pid} → {local_url}")
        self._changed()

        if proc.stdout is None:
            raise RuntimeError("cloudflared stdout pipe missing")
        try:
            while True:
                line_b = await proc.stdout.readline()
                if not line_b:
                    break
                line = line_b.decode("utf-8", errors="replace").rstrip()
                if not line:
                    continue
                _logger.debug("cloudflared: %s", line)
                match = _TUNNEL_URL_RE.search(line)
                if match and self._state.url != match.group(0):
                    self._state.url = match.group(0).rstrip("/")
                    self._state.last_error = None
                    self._state.note(f"url {self._state.url}")
                    self._url_ready.set()
                    self._changed()
                    _logger.info("Cloudflare tunnel ready: %s", self._state.url)
        finally:
            await self._kill_proc()
            code = proc.returncode
            self._state.pid = None
            self._state.started_mono = None
            if self._state.desired and not self._stop.is_set():
                # Process exited while we still want a tunnel.
                if self._state.url is not None:
                    self._state.url = None
                    self._changed()
                raise RuntimeError(f"cloudflared exited with code {code}")

    async def _kill_proc(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None or proc.returncode is not None:
            return
        pid = proc.pid

        def _signal(sig: signal.Signals) -> None:
            # start_new_session=True → child is a session leader; kill the group so
            # nested helpers (cloudflared's own children) die with it. Windows has
            # no process groups here — fall back to terminate/kill on the process.
            if hasattr(os, "killpg"):
                with contextlib.suppress(ProcessLookupError, OSError):
                    os.killpg(pid, sig)
                    return
            with contextlib.suppress(ProcessLookupError, OSError):
                if sig == signal.SIGKILL:
                    proc.kill()
                else:
                    proc.terminate()

        _signal(signal.SIGTERM)
        try:
            await asyncio.wait_for(proc.wait(), timeout=3.0)
            return
        except TimeoutError:
            pass
        _signal(signal.SIGKILL)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(proc.wait(), timeout=2.0)

    def _changed(self) -> None:
        if self._on_change is not None:
            with contextlib.suppress(Exception):
                self._on_change()
