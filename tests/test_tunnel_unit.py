"""Unit tests for the managed Cloudflare quick tunnel."""

from __future__ import annotations

import stat
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi")

from lovensepy._models import CommandResponse, GetToysResponse
from lovensepy.services.http_api.app import create_app
from lovensepy.services.http_api.config import ServiceConfig
from lovensepy.services.http_api.tunnel import CloudflaredTunnel, resolve_cloudflared_binary


def _fake_cloudflared(
    tmp_path: Path, *, url: str = "https://demo-tunnel.trycloudflare.com"
) -> Path:
    script = tmp_path / "fake-cloudflared"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys, time\n"
        "sys.stdout.write('INF Requesting new quick Tunnel\\n')\n"
        "sys.stdout.write('|  Your quick Tunnel has been created! Visit it at:  |\\n')\n"
        f"sys.stdout.write('|  {url}                                   |\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


@pytest.fixture
def lan_backend(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    backend = MagicMock()
    backend.get_toys = AsyncMock(
        return_value=GetToysResponse.model_validate(
            {"data": {"toys": {"t1": {"id": "t1", "name": "x", "status": "1"}}}}
        )
    )
    ok = CommandResponse(code=200, type="OK", result=True)
    backend.function_request = AsyncMock(return_value=ok)
    backend.preset_request = AsyncMock(return_value=ok)
    backend.pattern_request = AsyncMock(return_value=ok)
    backend.stop = AsyncMock(return_value=ok)
    backend.aclose = AsyncMock()
    monkeypatch.setattr(
        "lovensepy.services.http_api.transports.AsyncLANClient",
        lambda *args, **kwargs: backend,
    )
    return backend


async def test_start_parses_trycloudflare_url(tmp_path: Path) -> None:
    binary = _fake_cloudflared(tmp_path)
    changes: list[int] = []
    tunnel = CloudflaredTunnel(
        local_url_provider=lambda: "http://127.0.0.1:8123",
        binary_provider=lambda: str(binary),
        on_change=lambda: changes.append(1),
        auto_restart=False,
    )

    status = await tunnel.start()
    try:
        assert status["url"] == "https://demo-tunnel.trycloudflare.com"
        assert status["running"] is True
        assert status["desired"] is True
        assert status["local_url"] == "http://127.0.0.1:8123"
        assert changes, "URL discovery must notify /ws watchers"
    finally:
        await tunnel.stop()

    stopped = tunnel.status()
    assert stopped["running"] is False
    assert stopped["desired"] is False
    assert stopped["url"] is None


async def test_missing_binary_is_a_clear_error() -> None:
    tunnel = CloudflaredTunnel(
        local_url_provider=lambda: "http://127.0.0.1:8123",
        binary_provider=lambda: None,
    )
    with pytest.raises(FileNotFoundError, match="cloudflared"):
        await tunnel.start()


def test_resolve_prefers_explicit_path(tmp_path: Path) -> None:
    binary = _fake_cloudflared(tmp_path)
    assert resolve_cloudflared_binary(str(binary)) == str(binary.resolve())


def test_resolve_ignores_missing_explicit_path(tmp_path: Path) -> None:
    missing = tmp_path / "definitely-missing-binary"
    # May still find a system cloudflared via PATH — just never returns the missing path.
    resolved = resolve_cloudflared_binary(str(missing))
    assert resolved != str(missing)


def test_api_start_and_stop_tunnel(
    lan_backend: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = _fake_cloudflared(tmp_path)
    monkeypatch.setenv("LOVENSE_CLOUDFLARED_BIN", str(binary))
    cfg = ServiceConfig(
        mode="lan",
        lan_ip="127.0.0.1",
        listen_port=8123,
        tunnel_binary=str(binary),
    )
    with TestClient(create_app(cfg)) as client:
        started = client.post("/system/tunnel", json={"enabled": True})
        assert started.status_code == 200, started.text
        body = started.json()
        assert body["tunnel"]["url"] == "https://demo-tunnel.trycloudflare.com"

        network = client.get("/system/network").json()
        assert network["tunnel_url"] == "https://demo-tunnel.trycloudflare.com"
        assert network["primary_url"] == network["tunnel_url"]
        assert network["secure_context"] is True

        state = client.get("/state").json()
        assert state["tunnel"]["url"] == "https://demo-tunnel.trycloudflare.com"
        assert state["config"]["tunnel"]["enabled"] is True

        stopped = client.post("/system/tunnel", json={"enabled": False})
        assert stopped.status_code == 200
        assert stopped.json()["tunnel"]["running"] is False
        assert stopped.json()["tunnel"]["url"] is None


def test_api_reports_missing_cloudflared(
    lan_backend: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "lovensepy.services.http_api.tunnel.resolve_cloudflared_binary",
        lambda explicit=None: None,
    )
    cfg = ServiceConfig(mode="lan", lan_ip="127.0.0.1", listen_port=8123, tunnel_binary=None)
    # Force the runtime binary provider to miss even when PATH has a real cloudflared.
    app = create_app(cfg)
    app.state.runtime.tunnel._binary_provider = lambda: None  # noqa: SLF001
    with TestClient(app) as client:
        response = client.post("/system/tunnel", json={"enabled": True})
        assert response.status_code == 503
        assert "cloudflared" in response.json()["detail"].lower()
