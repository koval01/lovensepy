"""Gate for visitors outside the local network.

LAN / loopback traffic is unrestricted. A request that arrives through a public
host (Cloudflare quick tunnel, port-forward, …) needs someone on the host
machine to confirm — either by tapping Allow in the local panel, or by sharing
the 6-digit console code. Remotes wait on an authorization screen until one of
those succeeds.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import quote

from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocket

_logger = logging.getLogger(__name__)

COOKIE_NAME = "lovensepy_gate"
CODE_TTL_SEC = 10 * 60
APPROVAL_TTL_SEC = 5 * 60
SESSION_TTL_SEC = 7 * 24 * 3600
MAX_VERIFY_FAILURES = 8
ApprovalStatus = Literal["pending", "approved", "denied", "expired"]
_PUBLIC_HOST_SUFFIXES = (
    ".trycloudflare.com",
    ".cfargotunnel.com",
    ".ngrok-free.app",
    ".ngrok.io",
    ".loca.lt",
)
_OPEN_PATHS = frozenset(
    {
        "/health",
        "/auth",
        "/auth/",
        "/auth/status",
        "/auth/verify",
        "/auth/challenge",
        "/auth/request",
    }
)


def _is_private_ip(value: str) -> bool:
    try:
        addr = ipaddress.ip_address(value.strip())
    except ValueError:
        return False
    return bool(
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_unspecified
    )


def _host_without_port(host_header: str | None) -> str:
    raw = (host_header or "").strip().lower()
    if not raw:
        return ""
    if raw.startswith("["):
        # [IPv6]:port
        end = raw.find("]")
        return raw[1:end] if end != -1 else raw.strip("[]")
    if raw.count(":") == 1:
        return raw.split(":", 1)[0]
    return raw


def client_ip(scope: Scope, headers: Headers) -> str | None:
    """Best-effort visitor address (Cloudflare / proxy headers, then the peer)."""
    # Prefer reverse-proxy headers: cloudflared / nginx always terminate locally.
    for name in ("cf-connecting-ip", "x-real-ip"):
        value = headers.get(name)
        if value:
            return value.split(",")[0].strip()
    forwarded = headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = scope.get("client")
    if client and client[0]:
        return str(client[0])
    return None


# Back-compat for internal callers / tests that imported the private name.
_client_ip = client_ip


def _is_ip_literal(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def is_external_request(scope: Scope, headers: Headers | None = None) -> bool:
    """True when the visitor is not on this machine / LAN.

    Phones on the same Wi-Fi hit ``http://192.168.x.x`` (private Host) and pass.
    Cloudflare quick tunnels hit ``https://*.trycloudflare.com`` and are gated —
    even though cloudflared itself dials loopback. Bare names like ``testserver``
    or ``my-mac.local`` stay local.
    """
    hdrs = headers if headers is not None else Headers(scope=scope)
    host = _host_without_port(hdrs.get("host"))
    if any(host.endswith(suffix) for suffix in _PUBLIC_HOST_SUFFIXES):
        return True
    if host and _is_ip_literal(host) and not _is_private_ip(host):
        return True
    if host and "." in host and not host.endswith(".local") and not _is_ip_literal(host):
        # Public DNS name (duckdns, ddns, …) — not a LAN share.
        return True

    client_ip = _client_ip(scope, hdrs)
    # Only real public IP literals count. TestClient uses a hostname like
    # "testclient" which is not an address and must not trip the gate.
    if client_ip and _is_ip_literal(client_ip) and not _is_private_ip(client_ip):
        return True
    return False


def _wants_html(headers: Headers) -> bool:
    accept = headers.get("accept") or ""
    return "text/html" in accept or "*/*" in accept


@dataclass
class _PendingCode:
    code: str
    expires_mono: float
    failures: int = 0
    printed: bool = False


@dataclass
class _PendingApproval:
    id: str
    fingerprint: str
    created_mono: float
    expires_mono: float
    ip: str | None
    country: str | None
    user_agent: str | None
    device: str
    browser: str
    status: ApprovalStatus = "pending"
    session_token: str | None = None
    decided_mono: float | None = None


@dataclass
class AccessGate:
    """In-memory codes, host-approval requests, and sessions for one process."""

    enabled: bool = True
    code_ttl_sec: float = CODE_TTL_SEC
    approval_ttl_sec: float = APPROVAL_TTL_SEC
    session_ttl_sec: float = SESSION_TTL_SEC
    _secret: bytes = field(default_factory=lambda: secrets.token_bytes(32))
    _pending: _PendingCode | None = None
    _approvals: dict[str, _PendingApproval] = field(default_factory=dict)
    _sessions: dict[str, float] = field(default_factory=dict)
    _print: Callable[[str], None] = print
    _on_change: Callable[[], None] | None = None

    def status(self) -> dict[str, Any]:
        """Public-safe gate status (no codes, no visitor identities)."""
        pending = self._pending
        now = time.monotonic()
        self._purge_sessions(now)
        self._purge_approvals(now)
        return {
            "enabled": self.enabled,
            "code_pending": bool(pending and pending.expires_mono > now),
            "code_expires_in_sec": (
                max(0.0, round(pending.expires_mono - now, 1))
                if pending and pending.expires_mono > now
                else None
            ),
            "active_sessions": len(self._sessions),
            "pending_approval_count": sum(
                1 for item in self._approvals.values() if item.status == "pending"
            ),
        }

    def pending_approvals(self) -> list[dict[str, Any]]:
        """Host-only: visitors waiting for Allow / Deny."""
        now = time.monotonic()
        self._purge_approvals(now)
        rows: list[dict[str, Any]] = []
        for item in sorted(self._approvals.values(), key=lambda row: row.created_mono):
            if item.status != "pending":
                continue
            rows.append(
                {
                    "id": item.id,
                    "ip": item.ip,
                    "country": item.country,
                    "device": item.device,
                    "browser": item.browser,
                    "user_agent": item.user_agent,
                    "created_ago_sec": max(0.0, round(now - item.created_mono, 1)),
                    "expires_in_sec": max(0.0, round(item.expires_mono - now, 1)),
                }
            )
        return rows

    def peek_code(self) -> dict[str, Any] | None:
        """Return the live challenge digits for the host UI only (never for remotes)."""
        pending = self._pending
        now = time.monotonic()
        if pending is None or pending.expires_mono <= now:
            return None
        code = pending.code
        return {
            "code": code,
            "display": f"{code[:3]} {code[3:]}",
            "expires_in_sec": max(0.0, round(pending.expires_mono - now, 1)),
        }

    def ensure_host_code(self, *, rotate: bool = False) -> dict[str, Any]:
        """Mint (or rotate) a challenge so the host can read it in the phone dialog."""
        if not self.enabled:
            return {"status": "disabled", "code": None, "display": None, "expires_in_sec": None}
        self.issue_challenge(force_new=rotate)
        peeked = self.peek_code() or {}
        return {
            "status": "ok",
            "code": peeked.get("code"),
            "display": peeked.get("display"),
            "expires_in_sec": peeked.get("expires_in_sec"),
        }

    def issue_challenge(self, *, force_new: bool = False) -> dict[str, Any]:
        """Ensure a live code exists and (re)print it to the host console."""
        now = time.monotonic()
        pending = self._pending
        if (
            force_new
            or pending is None
            or pending.expires_mono <= now
            or pending.failures >= MAX_VERIFY_FAILURES
        ):
            code = f"{secrets.randbelow(1_000_000):06d}"
            self._pending = _PendingCode(
                code=code, expires_mono=now + self.code_ttl_sec, printed=False
            )
            pending = self._pending
        assert pending is not None
        if not pending.printed or force_new:
            self._announce(pending.code)
            pending.printed = True
        return {
            "status": "challenge",
            "expires_in_sec": max(0.0, round(pending.expires_mono - now, 1)),
            "hint": (
                "A 6-digit code was printed in the LovensePy service console "
                "on the host machine. Enter it here to continue."
            ),
        }

    def verify(self, raw_code: str) -> str | None:
        """Validate the code. Returns a new session token, or ``None`` on failure."""
        now = time.monotonic()
        pending = self._pending
        if pending is None or pending.expires_mono <= now:
            return None
        digits = re.sub(r"\D", "", raw_code or "")
        if len(digits) != 6 or not hmac.compare_digest(digits, pending.code):
            pending.failures += 1
            if pending.failures >= MAX_VERIFY_FAILURES:
                self._pending = None
                self._print(
                    "\nLovensePy: too many wrong access codes — challenge cancelled.\n"
                    "The next visitor will get a fresh code.\n"
                )
            return None
        self._pending = None
        # Code entry also clears waiting approvals for this visitor wave.
        self._clear_pending_approvals()
        token = self._mint_session(now)
        self._print("\nLovensePy: external access approved (code).\n")
        self._notify()
        return token

    def create_approval(
        self,
        *,
        ip: str | None,
        country: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Register (or reuse) a host-approval request for a tunnel visitor."""
        from .presence import browser_label, device_label

        now = time.monotonic()
        self._purge_approvals(now)
        fingerprint = hashlib.sha256(
            f"{ip or ''}\n{(user_agent or '')[:240]}".encode()
        ).hexdigest()[:24]
        device = device_label(user_agent)
        browser = browser_label(user_agent)

        if request_id and request_id in self._approvals:
            existing = self._approvals[request_id]
            if existing.status == "pending" and existing.expires_mono > now:
                return self._approval_public(existing, now)

        for item in self._approvals.values():
            if (
                item.status == "pending"
                and item.expires_mono > now
                and item.fingerprint == fingerprint
            ):
                return self._approval_public(item, now)

        # Keep the console code available as a fallback while they wait.
        self.issue_challenge(force_new=False)

        approval_id = secrets.token_urlsafe(12)
        row = _PendingApproval(
            id=approval_id,
            fingerprint=fingerprint,
            created_mono=now,
            expires_mono=now + self.approval_ttl_sec,
            ip=ip,
            country=country,
            user_agent=(user_agent or "")[:300] or None,
            device=device,
            browser=browser,
        )
        self._approvals[approval_id] = row
        where = " · ".join(part for part in (ip, country, f"{device} {browser}") if part)
        self._print(
            "\n"
            "============================================================\n"
            "  LovensePy: allow remote access?\n"
            f"\n"
            f"  {where or 'Unknown visitor'} is waiting on the tunnel.\n"
            "  Approve in the local LovensePy panel, or share the 6-digit\n"
            "  access code shown there / in this console.\n"
            f"  Request expires in {int(self.approval_ttl_sec // 60)} minutes.\n"
            "============================================================\n"
        )
        _logger.info("External access approval pending id=%s ip=%s", approval_id, ip)
        self._notify()
        return self._approval_public(row, now)

    def approval_status(self, request_id: str) -> dict[str, Any]:
        now = time.monotonic()
        self._purge_approvals(now)
        row = self._approvals.get(request_id)
        if row is None:
            return {
                "status": "expired",
                "request_id": request_id,
                "authorized": False,
            }
        if row.status == "pending" and row.expires_mono <= now:
            row.status = "expired"
            return {
                "status": "expired",
                "request_id": request_id,
                "authorized": False,
            }
        return self._approval_public(row, now)

    def claim_approval(self, request_id: str) -> str | None:
        """If the host already approved, return a one-shot session token."""
        now = time.monotonic()
        row = self._approvals.get(request_id)
        if row is None or row.status != "approved" or not row.session_token:
            return None
        token = row.session_token
        # One claim — drop the row so the token cannot be harvested again.
        self._approvals.pop(request_id, None)
        self._sessions[token] = now + self.session_ttl_sec
        self._notify()
        return token

    def approve(self, request_id: str) -> dict[str, Any] | None:
        now = time.monotonic()
        self._purge_approvals(now)
        row = self._approvals.get(request_id)
        if row is None or row.status != "pending" or row.expires_mono <= now:
            return None
        row.status = "approved"
        row.decided_mono = now
        row.session_token = secrets.token_urlsafe(32)
        # Keep the grant claimable a bit past the original wait window.
        row.expires_mono = now + min(120.0, self.approval_ttl_sec)
        self._print(f"\nLovensePy: approved remote access for {row.ip or row.device}.\n")
        self._notify()
        return self._approval_public(row, now)

    def deny(self, request_id: str) -> dict[str, Any] | None:
        now = time.monotonic()
        self._purge_approvals(now)
        row = self._approvals.get(request_id)
        if row is None or row.status != "pending":
            return None
        row.status = "denied"
        row.decided_mono = now
        row.session_token = None
        row.expires_mono = now + 60.0
        self._print(f"\nLovensePy: denied remote access for {row.ip or row.device}.\n")
        self._notify()
        return self._approval_public(row, now)

    def session_valid(self, token: str | None) -> bool:
        if not token:
            return False
        now = time.monotonic()
        self._purge_sessions(now)
        expires = self._sessions.get(token)
        return expires is not None and expires > now

    def revoke(self, token: str | None) -> None:
        if token:
            self._sessions.pop(token, None)

    def sign_cookie_value(self, token: str) -> str:
        digest = hmac.new(self._secret, token.encode(), hashlib.sha256).hexdigest()[:16]
        return f"{token}.{digest}"

    def read_cookie_value(self, raw: str | None) -> str | None:
        if not raw or "." not in raw:
            return None
        token, digest = raw.rsplit(".", 1)
        expected = hmac.new(self._secret, token.encode(), hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(digest, expected):
            return None
        return token

    def _mint_session(self, now: float) -> str:
        token = secrets.token_urlsafe(32)
        self._sessions[token] = now + self.session_ttl_sec
        return token

    def _approval_public(self, row: _PendingApproval, now: float) -> dict[str, Any]:
        return {
            "status": row.status,
            "request_id": row.id,
            "authorized": row.status == "approved",
            "expires_in_sec": max(0.0, round(row.expires_mono - now, 1)),
            "device": row.device,
            "browser": row.browser,
        }

    def _clear_pending_approvals(self) -> None:
        dead = [key for key, row in self._approvals.items() if row.status == "pending"]
        for key in dead:
            self._approvals.pop(key, None)

    def _purge_approvals(self, now: float) -> None:
        dead: list[str] = []
        for key, row in self._approvals.items():
            if row.status == "pending" and row.expires_mono <= now:
                row.status = "expired"
            # Drop finished rows a minute after decision / expiry.
            keep_until = (
                row.expires_mono
                if row.status == "pending"
                else ((row.decided_mono or row.expires_mono) + 60.0)
            )
            if row.status != "pending" and keep_until <= now:
                dead.append(key)
            elif row.status == "expired" and row.expires_mono + 60.0 <= now:
                dead.append(key)
        for key in dead:
            self._approvals.pop(key, None)

    def _purge_sessions(self, now: float) -> None:
        dead = [key for key, expires in self._sessions.items() if expires <= now]
        for key in dead:
            self._sessions.pop(key, None)

    def _notify(self) -> None:
        if self._on_change is not None:
            try:
                self._on_change()
            except Exception:  # pylint: disable=broad-exception-caught
                _logger.debug("Access gate on_change failed", exc_info=True)

    def _announce(self, code: str) -> None:
        pretty = f"{code[:3]} {code[3:]}"
        banner = (
            "\n"
            "============================================================\n"
            "  LovensePy access code\n"
            f"\n"
            f"      {pretty}\n"
            "\n"
            "  Someone outside your local network is opening the panel.\n"
            "  Approve them in the local app, or enter this code on their\n"
            "  device. Expires in "
            f"{int(self.code_ttl_sec // 60)} minutes.\n"
            "============================================================\n"
        )
        self._print(banner)
        _logger.info("External access challenge issued (code printed to console)")


_AUTH_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="dark light">
<meta name="robots" content="noindex, nofollow">
<title>LovensePy · Waiting for authorization</title>
<style>
  :root {
    color-scheme: dark light;
    --bg: #000000;
    --card: #16181c;
    --fg: #e7e9ea;
    --muted: #71767b;
    --accent: #e7e9ea;
    --accent-fg: #0f1419;
    --border: rgba(255,255,255,.12);
    --danger: #f4212e;
    --ease: cubic-bezier(0.22, 1, 0.36, 1);
  }
  @media (prefers-color-scheme: light) {
    :root {
      --bg: #ffffff;
      --card: #ffffff;
      --fg: #0f1419;
      --muted: #536471;
      --accent: #0f1419;
      --accent-fg: #ffffff;
      --border: #eff3f4;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100dvh; display: grid; place-items: center;
    padding: max(24px, env(safe-area-inset-top)) 20px max(24px, env(safe-area-inset-bottom));
    font: 16px/1.5 -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", system-ui, sans-serif;
    background: var(--bg); color: var(--fg);
    -webkit-font-smoothing: antialiased;
    letter-spacing: -0.011em;
  }
  main {
    width: min(100%, 22rem); background: var(--card); border: 1px solid var(--border);
    border-radius: 1.35rem; padding: 1.5rem;
    box-shadow: 0 1px 0 var(--border);
    animation: rise .42s var(--ease) both;
  }
  @keyframes rise {
    from { opacity: 0; transform: translate3d(0, 10px, 0); }
    to { opacity: 1; transform: translate3d(0, 0, 0); }
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  @media (prefers-reduced-motion: reduce) {
    main { animation: none; }
    .spinner { animation: none !important; }
    button, input { transition: none !important; }
  }
  h1 { font-size: 1.25rem; margin: 0 0 .35rem; letter-spacing: -.02em; font-weight: 650; }
  p { margin: 0 0 1rem; color: var(--muted); font-size: .92rem; }
  .wait {
    display: flex; flex-direction: column; align-items: center; gap: .85rem;
    padding: .5rem 0 1rem; text-align: center;
  }
  .spinner {
    width: 2rem; height: 2rem; border-radius: 999px;
    border: 2px solid var(--border); border-top-color: var(--fg);
    animation: spin .8s linear infinite;
  }
  .status { font-size: .92rem; color: var(--fg); margin: 0; }
  details { margin-top: .25rem; border-top: 1px solid var(--border); padding-top: 1rem; }
  summary {
    cursor: pointer; font-size: .85rem; font-weight: 600; color: var(--muted);
    list-style: none;
  }
  summary::-webkit-details-marker { display: none; }
  label { display: block; font-size: .8rem; font-weight: 600; margin: .85rem 0 .4rem; }
  input {
    width: 100%; font: inherit; font-size: 1.6rem; letter-spacing: .35em; text-align: center;
    padding: .7rem .5rem; border-radius: .9rem; border: 1px solid var(--border);
    background: transparent; color: var(--fg); outline: none;
    transition: border-color .28s var(--ease), box-shadow .28s var(--ease);
  }
  input:focus { border-color: var(--fg); box-shadow: 0 0 0 3px color-mix(in srgb, var(--fg) 18%, transparent); }
  button {
    width: 100%; margin-top: 1rem; border: 0; border-radius: .9rem; padding: .85rem 1rem;
    font: inherit; font-weight: 600; color: var(--accent-fg); background: var(--accent); cursor: pointer;
    transition: transform .2s var(--ease), opacity .28s var(--ease);
  }
  button.secondary {
    margin-top: .65rem; background: transparent; color: var(--fg);
    border: 1px solid var(--border);
  }
  button:active { transform: scale(0.98); }
  button:disabled { opacity: .55; cursor: wait; }
  .err { color: var(--danger); font-size: .85rem; min-height: 1.2em; margin-top: .75rem; }
  .meta { margin-top: 1rem; font-size: .75rem; color: var(--muted); }
  .hidden { display: none !important; }
</style>
</head>
<body>
<main>
  <div id="waitPane">
    <h1>Waiting for authorization</h1>
    <p>Ask the person at the host machine to allow this connection in LovensePy. You do not need an access code if they tap Allow.</p>
    <div class="wait">
      <div class="spinner" aria-hidden="true"></div>
      <p class="status" id="waitStatus">Waiting for authorization confirmation…</p>
    </div>
    <button type="button" class="secondary hidden" id="retryBtn">Request again</button>
    <div class="err" id="waitErr" role="alert"></div>
  </div>
  <details id="codeDetails">
    <summary>Use a 6-digit code instead</summary>
    <form id="form" autocomplete="one-time-code">
      <label for="code">Access code</label>
      <input id="code" name="code" inputmode="numeric" pattern="[0-9 ]*" maxlength="7"
             autocomplete="one-time-code" placeholder="••• •••">
      <button type="submit" id="go">Allow access</button>
      <div class="err" id="err" role="alert"></div>
    </form>
    <p class="meta">The host can also share the code shown in their LovensePy panel or console.</p>
  </details>
</main>
<script>
const form = document.getElementById("form");
const input = document.getElementById("code");
const err = document.getElementById("err");
const go = document.getElementById("go");
const waitStatus = document.getElementById("waitStatus");
const waitErr = document.getElementById("waitErr");
const retryBtn = document.getElementById("retryBtn");
const STORAGE_KEY = "lovensepy_auth_request";
let requestId = sessionStorage.getItem(STORAGE_KEY) || "";
let pollTimer = null;

function nextUrl() {
  const next = new URLSearchParams(location.search).get("next") || "/";
  return next.startsWith("/") ? next : "/";
}

function finish() {
  location.replace(nextUrl());
}

async function createRequest() {
  waitErr.textContent = "";
  retryBtn.classList.add("hidden");
  waitStatus.textContent = "Waiting for authorization confirmation…";
  const res = await fetch("/auth/request", {
    method: "POST",
    headers: { "Content-Type": "application/json", "Accept": "application/json" },
    body: JSON.stringify({ request_id: requestId || null }),
    credentials: "same-origin",
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    waitErr.textContent = body.detail || "Could not start authorization.";
    retryBtn.classList.remove("hidden");
    return;
  }
  requestId = body.request_id || "";
  if (requestId) sessionStorage.setItem(STORAGE_KEY, requestId);
  if (body.status === "approved") {
    await claimApproved();
    return;
  }
  startPolling();
}

async function claimApproved() {
  if (!requestId) return;
  const res = await fetch("/auth/request/" + encodeURIComponent(requestId), {
    method: "GET",
    headers: { "Accept": "application/json" },
    credentials: "same-origin",
  });
  const body = await res.json().catch(() => ({}));
  if (res.ok && (body.status === "approved" || body.authorized)) {
    sessionStorage.removeItem(STORAGE_KEY);
    finish();
    return;
  }
  waitErr.textContent = body.detail || "Approved, but the session could not be claimed.";
  retryBtn.classList.remove("hidden");
}

async function pollOnce() {
  if (!requestId) return;
  const res = await fetch("/auth/request/" + encodeURIComponent(requestId), {
    method: "GET",
    headers: { "Accept": "application/json" },
    credentials: "same-origin",
  });
  const body = await res.json().catch(() => ({}));
  if (res.ok && (body.status === "approved" || body.authorized)) {
    clearInterval(pollTimer);
    pollTimer = null;
    sessionStorage.removeItem(STORAGE_KEY);
    waitStatus.textContent = "Authorized — opening panel…";
    finish();
    return;
  }
  if (body.status === "denied") {
    clearInterval(pollTimer);
    pollTimer = null;
    waitStatus.textContent = "Access denied";
    waitErr.textContent = "The host declined this connection.";
    retryBtn.classList.remove("hidden");
    sessionStorage.removeItem(STORAGE_KEY);
    return;
  }
  if (body.status === "expired") {
    clearInterval(pollTimer);
    pollTimer = null;
    waitStatus.textContent = "Request expired";
    waitErr.textContent = "Ask the host again, or use a 6-digit code.";
    retryBtn.classList.remove("hidden");
    sessionStorage.removeItem(STORAGE_KEY);
  }
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(() => { pollOnce().catch(() => {}); }, 1500);
  pollOnce().catch(() => {});
}

retryBtn.addEventListener("click", () => {
  requestId = "";
  sessionStorage.removeItem(STORAGE_KEY);
  createRequest().catch(() => {
    waitErr.textContent = "Could not reach the service.";
    retryBtn.classList.remove("hidden");
  });
});

createRequest().catch(() => {
  waitErr.textContent = "Could not reach the service.";
  retryBtn.classList.remove("hidden");
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  err.textContent = "";
  go.disabled = true;
  try {
    const res = await fetch("/auth/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify({ code: input.value }),
      credentials: "same-origin",
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      err.textContent = body.detail || "Wrong or expired code.";
      input.select();
      return;
    }
    sessionStorage.removeItem(STORAGE_KEY);
    finish();
  } catch (e) {
    err.textContent = "Could not reach the service.";
  } finally {
    go.disabled = false;
  }
});
</script>
</body>
</html>
"""


class AccessGateMiddleware:
    """ASGI middleware that enforces :class:`AccessGate` for external visitors."""

    def __init__(self, app: ASGIApp, gate: AccessGate) -> None:
        self.app = app
        self.gate = gate

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or not self.gate.enabled:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        path = scope.get("path") or "/"
        if path in _OPEN_PATHS or path.startswith("/auth/"):
            await self.app(scope, receive, send)
            return

        if not is_external_request(scope, headers):
            await self.app(scope, receive, send)
            return

        token = self.gate.read_cookie_value(_cookie(headers, COOKIE_NAME))
        if self.gate.session_valid(token):
            await self.app(scope, receive, send)
            return

        # First contact from outside → mint + print a code (idempotent while valid).
        self.gate.issue_challenge()

        if scope["type"] == "websocket":
            websocket = WebSocket(scope, receive=receive, send=send)
            await websocket.accept()
            await websocket.close(code=4401)
            return

        if _wants_html(headers) and scope.get("method") in ("GET", "HEAD"):
            # Keep deep-links working after the visitor enters the code.
            target = path
            query = scope.get("query_string") or b""
            if query:
                target = f"{path}?{query.decode('latin-1')}"
            if target not in ("/", ""):
                location = f"/auth?next={quote(target, safe='/:?=&%')}"
                response: Response = RedirectResponse(location, status_code=302)
            else:
                response = HTMLResponse(_AUTH_PAGE, headers={"Cache-Control": "no-store"})
            await response(scope, receive, send)
            return

        response = JSONResponse(
            {
                "detail": (
                    "External access requires authorization. Open this URL in a browser "
                    "and wait for the host to Allow the connection (or enter the 6-digit "
                    "code from the host panel), then retry."
                ),
                "auth": "/auth",
            },
            status_code=401,
            headers={"Cache-Control": "no-store"},
        )
        await response(scope, receive, send)


def _cookie(headers: Headers, name: str) -> str | None:
    raw = headers.get("cookie")
    if not raw:
        return None
    for part in raw.split(";"):
        piece = part.strip()
        if piece.startswith(name + "="):
            return piece[len(name) + 1 :]
    return None


def _set_session_cookie(response: Response, gate: AccessGate, request: Request, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=gate.sign_cookie_value(token),
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https"
        or (request.headers.get("x-forwarded-proto") or "").startswith("https"),
        max_age=int(gate.session_ttl_sec),
        path="/",
    )


def _country_from_headers(headers: Headers) -> str | None:
    raw = (headers.get("cf-ipcountry") or headers.get("x-country-code") or "").strip().upper()
    if not raw or raw in {"XX", "T1", "ZZ"}:
        return None
    if re.fullmatch(r"[A-Z]{2}", raw):
        return raw
    return None


def install_access_gate(app: Any, gate: AccessGate) -> None:
    """Register ``/auth`` routes and the ASGI middleware on a FastAPI app."""

    @app.get("/auth", include_in_schema=False)
    async def auth_page() -> HTMLResponse:
        if gate.enabled:
            # Code stays available as a fallback; approval is the primary path.
            gate.issue_challenge()
        return HTMLResponse(_AUTH_PAGE, headers={"Cache-Control": "no-store"})

    @app.get("/auth/status", tags=["auth"], summary="Access-gate status (no secrets)")
    async def auth_status(request: Request) -> dict[str, Any]:
        external = is_external_request(request.scope, request.headers)
        token = gate.read_cookie_value(request.cookies.get(COOKIE_NAME))
        return {
            **gate.status(),
            "external": external,
            "authorized": (not external) or gate.session_valid(token),
        }

    @app.post(
        "/auth/challenge",
        tags=["auth"],
        summary="Ensure a console code is printed for the current challenge",
    )
    async def auth_challenge() -> dict[str, Any]:
        if not gate.enabled:
            return {"status": "disabled"}
        return gate.issue_challenge()

    @app.post(
        "/auth/request",
        tags=["auth"],
        summary="Ask the host to allow this tunnel visitor",
    )
    async def auth_request(request: Request) -> dict[str, Any]:
        if not gate.enabled:
            return {"status": "disabled", "authorized": True, "request_id": None}
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        prior = payload.get("request_id")
        prior_id = str(prior).strip() if prior else None
        return gate.create_approval(
            ip=client_ip(request.scope, request.headers),
            country=_country_from_headers(request.headers),
            user_agent=request.headers.get("user-agent"),
            request_id=prior_id,
        )

    @app.get(
        "/auth/request/{request_id}",
        tags=["auth"],
        summary="Poll a host-approval request (sets session cookie when approved)",
    )
    async def auth_request_status(request_id: str, request: Request) -> Response:
        if not gate.enabled:
            return JSONResponse({"status": "disabled", "authorized": True})
        status = gate.approval_status(request_id)
        if status.get("status") == "approved":
            token = gate.claim_approval(request_id)
            if token is None:
                # Already claimed by a concurrent poll — treat as success if cookie exists.
                existing = gate.read_cookie_value(request.cookies.get(COOKIE_NAME))
                if gate.session_valid(existing):
                    return JSONResponse({"status": "approved", "authorized": True})
                return JSONResponse(
                    {"detail": "Approval expired before it could be claimed.", "status": "expired"},
                    status_code=410,
                )
            response = JSONResponse({"status": "approved", "authorized": True})
            _set_session_cookie(response, gate, request, token)
            return response
        return JSONResponse(status)

    @app.post("/auth/verify", tags=["auth"], summary="Exchange the console code for a session")
    async def auth_verify(request: Request) -> Response:
        if not gate.enabled:
            return JSONResponse({"status": "ok", "authorized": True})
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            # Also accept form posts from very old browsers.
            form = await request.form()
            payload = {"code": form.get("code")}
        code = str(payload.get("code") or "")
        token = gate.verify(code)
        if token is None:
            return JSONResponse(
                {
                    "detail": (
                        "Wrong or expired code. Ask the host to Allow in LovensePy, "
                        "or check the code and try again."
                    )
                },
                status_code=401,
            )
        response = JSONResponse({"status": "ok", "authorized": True})
        _set_session_cookie(response, gate, request, token)
        return response

    app.add_middleware(AccessGateMiddleware, gate=gate)
