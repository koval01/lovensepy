"""Host / remote presence and browser↔browser echo relay."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi")

from lovensepy._models import CommandResponse, GetToysResponse
from lovensepy.services.http_api.app import create_app
from lovensepy.services.http_api.config import ServiceConfig
from lovensepy.services.http_api.presence import (
    PresenceClient,
    PresenceHub,
    activity_for_path,
    browser_label,
    device_label,
)


def _scope(*, host: str, client: str = "127.0.0.1", extra: dict[str, str] | None = None):
    headers = [(b"host", host.encode())]
    for key, value in (extra or {}).items():
        headers.append((key.lower().encode(), value.encode()))
    return {"type": "http", "path": "/", "headers": headers, "client": (client, 12345)}


def test_device_and_browser_labels() -> None:
    assert device_label("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)") == "iPhone"
    assert (
        browser_label(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
        )
        == "Safari"
    )
    assert activity_for_path("/command/function", "POST") == "Adjusting intensity"


def test_role_follows_external_request_rules() -> None:
    assert PresenceHub.role_for_scope(_scope(host="127.0.0.1:8123")) == "host"
    assert PresenceHub.role_for_scope(_scope(host="demo.trycloudflare.com")) == "remote"


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
    )
    return TestClient(create_app(cfg))


def test_state_includes_presence_for_localhost(lan_backend: MagicMock) -> None:
    with _client() as client:
        body = client.get("/state", headers={"X-LovensePy-Client": "host-a"}).json()
        assert body["presence"]["self"]["role"] == "host"
        assert body["presence"]["remotes"] == []


def test_host_sees_remote_ws_client_and_echo_rtt(lan_backend: MagicMock) -> None:
    from tests._ws_proto import recv_server, send_echo, send_refresh

    with _client() as client:
        with client.websocket_connect("/ws?client_id=host-1") as host_ws:
            hello = recv_server(host_ws)
            assert hello["type"] == "hello"
            assert hello["data"]["role"] == "host"
            recv_server(host_ws)  # initial state

            with client.websocket_connect(
                "/ws?client_id=remote-1",
                headers={
                    "Host": "demo.trycloudflare.com",
                    "CF-Connecting-IP": "203.0.113.9",
                    "CF-IPCountry": "DE",
                    "User-Agent": (
                        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
                        "Mobile/15E148 Safari/604.1"
                    ),
                },
            ) as remote_ws:
                remote_hello = recv_server(remote_ws)
                assert remote_hello["data"]["role"] == "remote"
                recv_server(remote_ws)  # remote state (no remotes list)

                host_update = recv_server(host_ws)
                assert host_update["type"] == "state"
                remotes = host_update["data"]["presence"]["remotes"]
                assert len(remotes) == 1
                assert remotes[0]["client_id"] == "remote-1"
                assert remotes[0]["ip"] == "203.0.113.9"
                assert remotes[0]["country"] == "DE"
                assert remotes[0]["device"] == "iPhone"

                send_refresh(remote_ws)
                remote_state = recv_server(remote_ws)
                assert remote_state["data"]["presence"]["remotes"] == []

                send_echo(host_ws, echo_id="e1", t0=12.5, to_id="remote-1")
                echo = recv_server(remote_ws)
                assert echo["type"] == "echo"
                assert echo["id"] == "e1"
                assert echo["from"] == "host-1"

                send_echo(
                    remote_ws,
                    echo_id="e1",
                    t0=12.5,
                    t1=40.0,
                    to_id="host-1",
                    reply=True,
                )
                reply = recv_server(host_ws)
                assert reply["type"] == "echo_reply"
                assert reply["from"] == "remote-1"
                assert reply["t0"] == 12.5


def test_presence_snapshot_hides_remotes_from_remote_viewer() -> None:
    import time

    hub = PresenceHub()
    now = time.monotonic()
    host = PresenceClient(
        client_id="h",
        role="host",
        connected_at=now,
        last_seen_mono=now,
        device="Mac",
        browser="Safari",
    )
    remote = PresenceClient(
        client_id="r",
        role="remote",
        connected_at=now,
        last_seen_mono=now,
        device="iPhone",
        browser="Safari",
        ip="1.2.3.4",
        country="US",
    )
    hub._clients[remote.client_id] = remote
    assert len(hub.snapshot_for(host)["remotes"]) == 1
    assert hub.snapshot_for(remote)["remotes"] == []
