"""External-access gate: console code + session cookie for non-LAN visitors."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi")

from lovensepy._models import CommandResponse, GetToysResponse
from lovensepy.services.http_api.access_gate import AccessGate, is_external_request
from lovensepy.services.http_api.app import create_app
from lovensepy.services.http_api.config import ServiceConfig


def _scope(*, host: str, client: str = "127.0.0.1", extra: dict[str, str] | None = None):
    headers = [(b"host", host.encode())]
    for key, value in (extra or {}).items():
        headers.append((key.lower().encode(), value.encode()))
    return {"type": "http", "path": "/", "headers": headers, "client": (client, 12345)}


def test_lan_and_loopback_are_not_external() -> None:
    assert is_external_request(_scope(host="127.0.0.1:8123")) is False
    assert is_external_request(_scope(host="localhost:8123")) is False
    assert is_external_request(_scope(host="192.168.178.27:8123")) is False
    assert is_external_request(_scope(host="10.0.0.5")) is False
    assert is_external_request(_scope(host="testserver")) is False
    assert is_external_request(_scope(host="my-mac.local")) is False


def test_tunnel_and_public_hosts_are_external() -> None:
    assert is_external_request(_scope(host="demo.trycloudflare.com")) is True
    assert is_external_request(_scope(host="abc.ngrok-free.app")) is True
    assert is_external_request(_scope(host="toys.example.com")) is True
    assert is_external_request(_scope(host="8.8.8.8")) is True
    assert (
        is_external_request(_scope(host="127.0.0.1:8123", extra={"cf-connecting-ip": "1.1.1.1"}))
        is True
    )


def test_gate_prints_code_and_issues_session() -> None:
    printed: list[str] = []
    gate = AccessGate(enabled=True, _print=printed.append)
    challenge = gate.issue_challenge()
    assert challenge["status"] == "challenge"
    assert printed and "LovensePy access code" in printed[0]
    # Pull the digits out of the banner (formatted as "ABC DEF").
    import re

    match = re.search(r"\n\s+(\d{3})\s+(\d{3})\s+\n", printed[0])
    assert match
    code = match.group(1) + match.group(2)
    token = gate.verify(code)
    assert token
    assert gate.session_valid(token)
    assert gate.verify("000000") is None  # consumed


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


def test_local_requests_stay_ungated(lan_backend: MagicMock) -> None:
    app = create_app(ServiceConfig(mode="lan", lan_ip="127.0.0.1", external_gate=True))
    with TestClient(app) as client:
        assert client.get("/state").status_code == 200
        assert client.get("/auth/status").json()["authorized"] is True


def test_external_visitor_must_enter_console_code(lan_backend: MagicMock) -> None:
    printed: list[str] = []
    app = create_app(ServiceConfig(mode="lan", lan_ip="127.0.0.1", external_gate=True))
    app.state.runtime.gate._print = printed.append  # noqa: SLF001

    with TestClient(app) as client:
        blocked = client.get(
            "/state",
            headers={"Host": "demo.trycloudflare.com", "Accept": "application/json"},
        )
        assert blocked.status_code == 401
        assert "/auth" in blocked.json()["auth"]
        assert printed and "access code" in printed[0].lower()

        page = client.get("/", headers={"Host": "demo.trycloudflare.com", "Accept": "text/html"})
        assert page.status_code == 200
        assert "Waiting for authorization" in page.text

        import re

        match = re.search(r"\n\s+(\d{3})\s+(\d{3})\s+\n", printed[0])
        assert match
        code = match.group(1) + match.group(2)

        wrong = client.post(
            "/auth/verify",
            headers={"Host": "demo.trycloudflare.com"},
            json={"code": "000000"},
        )
        assert wrong.status_code == 401

        ok = client.post(
            "/auth/verify",
            headers={"Host": "demo.trycloudflare.com"},
            json={"code": code},
        )
        assert ok.status_code == 200
        assert "lovensepy_gate" in ok.cookies

        allowed = client.get(
            "/state",
            headers={"Host": "demo.trycloudflare.com", "Accept": "application/json"},
        )
        assert allowed.status_code == 200
        body = allowed.json()
        # Remotes get a redacted snapshot: control toys, not admin/session counts.
        assert body["access"]["role"] == "remote"
        assert body["access"]["capabilities"] == ["control"]
        assert body["gate"]["enabled"] is True


def test_gate_can_be_disabled(lan_backend: MagicMock) -> None:
    app = create_app(ServiceConfig(mode="lan", lan_ip="127.0.0.1", external_gate=False))
    with TestClient(app) as client:
        response = client.get(
            "/state",
            headers={"Host": "demo.trycloudflare.com", "Accept": "application/json"},
        )
        assert response.status_code == 200


def test_host_can_allow_waiting_tunnel_visitor(lan_backend: MagicMock) -> None:
    app = create_app(ServiceConfig(mode="lan", lan_ip="127.0.0.1", external_gate=True))
    remote = {
        "Host": "demo.trycloudflare.com",
        "Accept": "application/json",
        "User-Agent": "iPhone",
    }

    with TestClient(app) as client:
        asked = client.post("/auth/request", headers=remote, json={})
        assert asked.status_code == 200
        body = asked.json()
        assert body["status"] == "pending"
        request_id = body["request_id"]
        assert request_id

        host_state = client.get("/state").json()
        pending = host_state["gate"]["pending_approvals"]
        assert any(row["id"] == request_id for row in pending)

        allowed = client.post(f"/system/access-approvals/{request_id}/allow")
        assert allowed.status_code == 200
        assert allowed.json()["status"] == "approved"

        claimed = client.get(f"/auth/request/{request_id}", headers=remote)
        assert claimed.status_code == 200
        assert claimed.json()["authorized"] is True
        assert "lovensepy_gate" in claimed.cookies

        state = client.get("/state", headers=remote)
        assert state.status_code == 200
        assert state.json()["access"]["role"] == "remote"


def test_host_can_deny_waiting_tunnel_visitor(lan_backend: MagicMock) -> None:
    app = create_app(ServiceConfig(mode="lan", lan_ip="127.0.0.1", external_gate=True))
    remote = {"Host": "demo.trycloudflare.com", "Accept": "application/json"}

    with TestClient(app) as client:
        request_id = client.post("/auth/request", headers=remote, json={}).json()["request_id"]
        denied = client.post(f"/system/access-approvals/{request_id}/deny")
        assert denied.status_code == 200
        assert denied.json()["status"] == "denied"

        status = client.get(f"/auth/request/{request_id}", headers=remote)
        assert status.status_code == 200
        assert status.json()["status"] == "denied"
        assert "lovensepy_gate" not in status.cookies
