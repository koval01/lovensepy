"""Local network gets full admin; Cloudflare / external visitors are control-only."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi")

from lovensepy._models import CommandResponse, GetToysResponse
from lovensepy.services.http_api.app import create_app
from lovensepy.services.http_api.config import ServiceConfig
from lovensepy.services.http_api.snapshot import redact_state_for_remote


@pytest.fixture
def lan_backend(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    backend = MagicMock()
    backend.get_toys = AsyncMock(
        return_value=GetToysResponse.model_validate(
            {"data": {"toys": {"t1": {"id": "t1", "name": "x", "status": "1", "battery": 50}}}}
        )
    )
    ok = CommandResponse(code=200, type="OK", result=True)
    backend.function_request = AsyncMock(return_value=ok)
    backend.stop = AsyncMock(return_value=ok)
    backend.aclose = AsyncMock()
    monkeypatch.setattr(
        "lovensepy.services.http_api.transports.AsyncLANClient",
        lambda *args, **kwargs: backend,
    )
    return backend


def _client() -> TestClient:
    cfg = ServiceConfig(
        mode="lan",
        lan_ip="127.0.0.1",
        app_name="test",
        webui_enabled=False,
        external_gate=False,
        enable_ble=False,
        enable_socket=False,
    )
    return TestClient(create_app(cfg))


_REMOTE_HEADERS = {
    "Host": "demo.trycloudflare.com",
    "CF-Connecting-IP": "203.0.113.40",
}


def test_localhost_can_read_config_and_tunnel(lan_backend: MagicMock) -> None:
    with _client() as client:
        assert client.get("/config").status_code == 200
        assert client.get("/system/tunnel").status_code == 200
        assert client.get("/system/network").status_code == 200
        assert client.get("/docs").status_code == 200


def test_remote_cannot_access_admin_or_setup(lan_backend: MagicMock) -> None:
    with _client() as client:
        assert client.get("/config", headers=_REMOTE_HEADERS).status_code == 403
        assert (
            client.post(
                "/config/transports",
                headers=_REMOTE_HEADERS,
                json={"lan": False},
            ).status_code
            == 403
        )
        assert client.get("/system/tunnel", headers=_REMOTE_HEADERS).status_code == 403
        assert (
            client.post(
                "/system/tunnel",
                headers=_REMOTE_HEADERS,
                json={"enabled": True},
            ).status_code
            == 403
        )
        assert client.get("/system/network", headers=_REMOTE_HEADERS).status_code == 403
        assert client.post("/ble/scan", headers=_REMOTE_HEADERS).status_code == 403
        assert client.get("/docs", headers=_REMOTE_HEADERS).status_code == 403


def test_remote_can_read_state_and_send_commands(lan_backend: MagicMock) -> None:
    with _client() as client:
        state = client.get("/state", headers=_REMOTE_HEADERS)
        assert state.status_code == 200
        body = state.json()
        assert body["access"]["role"] == "remote"
        assert body["access"]["capabilities"] == ["control"]
        assert body["tunnel"]["url"] is None
        assert body["ble"] is None
        assert body["config"]["lan"]["ip"] is None
        assert body["toys"][0]["battery"] == 50

        cmd = client.post(
            "/command/function",
            headers=_REMOTE_HEADERS,
            json={"toy_id": "t1", "actions": {"Vibrate": 5}, "time": 0},
        )
        assert cmd.status_code == 200

        stop = client.post("/command/stop/all", headers=_REMOTE_HEADERS)
        assert stop.status_code == 200


def test_redact_state_for_remote_strips_admin_fields() -> None:
    redacted = redact_state_for_remote(
        {
            "config": {"mode": "hybrid", "lan": {"ip": "10.0.0.1"}, "app_name": "x"},
            "transports": {"lan": True, "ble": True, "socket": False},
            "ble": {"registry": [{"toy_id": "a"}], "advertisements": [{"address": "aa"}]},
            "socket": {"status": {}, "qr": {"qrcodeUrl": "https://secret"}},
            "tunnel": {
                "desired": True,
                "running": True,
                "url": "https://x.trycloudflare.com",
                "binary": "/opt/cloudflared",
            },
            "gate": {
                "enabled": True,
                "code_pending": True,
                "code_expires_in_sec": 60,
                "active_sessions": 2,
                "code": "123456",
                "display": "123 456",
                "pending_approvals": [{"id": "x", "ip": "1.2.3.4"}],
            },
            "toys": [{"id": "t1", "battery": 12}],
        }
    )
    assert redacted["tunnel"]["url"] is None
    assert redacted["ble"] is None
    assert redacted["socket"] is None
    assert redacted["config"]["lan"]["ip"] is None
    assert redacted["gate"]["code_pending"] is False
    assert redacted["gate"]["code"] is None
    assert redacted["gate"]["display"] is None
    assert redacted["gate"]["pending_approvals"] == []
    assert redacted["toys"][0]["battery"] == 12


def _gated_client() -> TestClient:
    cfg = ServiceConfig(
        mode="lan",
        lan_ip="127.0.0.1",
        app_name="test",
        webui_enabled=False,
        external_gate=True,
        enable_ble=False,
        enable_socket=False,
    )
    return TestClient(create_app(cfg))


def test_host_can_read_and_rotate_access_code(lan_backend: MagicMock) -> None:
    with _gated_client() as client:
        first = client.get("/system/access-code")
        assert first.status_code == 200
        body = first.json()
        assert body["status"] == "ok"
        assert body["code"] is not None and len(body["code"]) == 6
        assert body["display"] == f"{body['code'][:3]} {body['code'][3:]}"

        state = client.get("/state").json()
        assert state["gate"]["code"] == body["code"]
        assert state["gate"]["display"] == body["display"]

        rotated = client.post("/system/access-code")
        assert rotated.status_code == 200
        assert rotated.json()["code"] != body["code"]


def test_remote_cannot_read_access_code(lan_backend: MagicMock) -> None:
    with _gated_client() as client:
        assert client.get("/system/access-code").status_code == 200
        # Gate middleware blocks unauthorized remotes before HostOnly (401 JSON).
        # Prefer application/json so TestClient does not follow an HTML redirect to /auth.
        api_remote = {**_REMOTE_HEADERS, "Accept": "application/json"}
        blocked = client.get("/system/access-code", headers=api_remote)
        assert blocked.status_code == 401
        assert blocked.json().get("code") is None
        assert client.post("/system/access-code", headers=api_remote).status_code == 401
