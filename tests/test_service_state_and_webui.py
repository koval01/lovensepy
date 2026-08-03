"""Aggregated ``/state``, live ``/ws`` events, runtime config and SPA serving."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi")

from lovensepy._models import CommandResponse, GetToysResponse
from lovensepy.services.http_api import webui as webui_module
from lovensepy.services.http_api.app import create_app
from lovensepy.services.http_api.config import ServiceConfig

_TOYS = {
    "t1": {
        "id": "t1",
        "name": "lush",
        "nickName": "Lush 3",
        "status": "1",
        "battery": 77,
        "toyType": "lush",
        "fullFunctionNames": ["Vibrate"],
    },
    "t2": {
        "id": "t2",
        "name": "nora",
        "nickName": "Nora",
        "status": "0",
        "battery": 12,
        "toyType": "nora",
        "fullFunctionNames": ["Vibrate", "Rotate"],
    },
}


@pytest.fixture
def lan_backend(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    backend = MagicMock()
    backend.get_toys = AsyncMock(
        return_value=GetToysResponse.model_validate({"data": {"toys": _TOYS}})
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


def _lan_client(**overrides: Any) -> TestClient:
    cfg = ServiceConfig(mode="lan", lan_ip="127.0.0.1", app_name="test", **overrides)
    return TestClient(create_app(cfg))


def test_state_merges_toys_capabilities_and_transports(lan_backend: MagicMock) -> None:
    with _lan_client() as client:
        body = client.get("/state").json()

    assert body["transports"] == {"lan": True, "ble": False, "socket": False}
    assert body["configured"] is True
    assert body["ble"] is None and body["socket"] is None
    assert body["toys_error"] is None
    assert body["tunnel"]["desired"] is False
    assert body["tunnel"]["url"] is None

    # Online toys first; offline ones are still listed so the UI can offer a reconnect.
    assert [toy["id"] for toy in body["toys"]] == ["t1", "t2"]
    lush = body["toys"][0]
    assert lush["nick_name"] == "Lush 3"
    assert lush["online"] is True
    assert lush["battery"] == 77
    assert lush["features"] == ["Vibrate"]
    assert lush["transport"] == "app"
    assert body["toys"][1]["online"] is False

    caps = body["capabilities"]
    assert "Vibrate" in caps["controllable_actions"]
    assert "All" not in caps["controllable_actions"]
    assert caps["function_ranges"]["Vibrate"] == [0, 20]
    assert caps["pattern_limits"]["max_steps"] == 50
    assert caps["presets"]

    assert body["config"]["lan"] == {"ip": "127.0.0.1", "port": 20011, "enabled": True}


def test_state_caches_toys_until_fresh_is_requested(lan_backend: MagicMock) -> None:
    with _lan_client(state_cache_ttl_sec=30.0) as client:
        client.get("/state")
        after_first = lan_backend.get_toys.await_count
        client.get("/state")
        client.get("/state")
        after_repeats = lan_backend.get_toys.await_count
        client.get("/state", params={"fresh": "true"})
        after_fresh = lan_backend.get_toys.await_count

    assert after_repeats == after_first, "repeat polls must be served from the cache"
    assert after_fresh == after_first + 1, "fresh=true must bypass the cache"


def test_state_reports_backend_failure_without_failing_the_request(
    lan_backend: MagicMock,
) -> None:
    lan_backend.get_toys = AsyncMock(side_effect=RuntimeError("app is closed"))
    with _lan_client() as client:
        response = client.get("/state")

    assert response.status_code == 200
    body = response.json()
    assert body["toys"] == []
    assert "app is closed" in (body["toys_error"] or "")


def test_state_lists_running_sessions(lan_backend: MagicMock) -> None:
    with _lan_client() as client:
        client.post("/command/function", json={"toy_id": "t1", "actions": {"Vibrate": 8}})
        body = client.get("/state").json()

    tasks = body["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["kind"] == "function"
    assert tasks[0]["feature"] == "Vibrate"
    assert tasks[0]["level"] == 8.0


def test_system_network_lists_urls_for_phones(lan_backend: MagicMock) -> None:
    with _lan_client() as client:
        body = client.get("/system/network").json()

    assert body["scheme"] == "http"
    assert body["local_url"].startswith("http://127.0.0.1")
    assert isinstance(body["lan_addresses"], list)
    assert body["primary_url"].startswith("http://")
    assert all(url.startswith("http://") for url in body["lan_urls"])
    assert body["tunnel_url"] is None
    assert body["tunnel"]["desired"] is False


def test_ws_streams_state_and_answers_refresh(lan_backend: MagicMock) -> None:
    from tests._ws_proto import recv_server, send_ping, send_refresh

    with _lan_client() as client, client.websocket_connect("/ws") as socket:
        hello = recv_server(socket)
        assert hello["type"] == "hello"
        assert hello["data"]["heartbeat_sec"] > 0

        first = recv_server(socket)
        assert first["type"] == "state"
        assert [toy["id"] for toy in first["data"]["toys"]] == ["t1", "t2"]

        send_ping(socket)
        assert recv_server(socket)["type"] == "pong"

        send_refresh(socket)
        again = recv_server(socket)
        assert again["type"] == "state"


def test_ws_pushes_after_a_command_changes_state(lan_backend: MagicMock) -> None:
    from tests._ws_proto import recv_server

    with _lan_client() as client, client.websocket_connect("/ws") as socket:
        recv_server(socket)  # hello
        before = recv_server(socket)["data"]
        assert before["tasks"] == []

        client.post("/command/function", json={"toy_id": "t1", "actions": {"Vibrate": 4}})

        after = recv_server(socket)
        assert after["type"] == "state"
        assert after["data"]["rev"] > before["rev"]
        assert after["data"]["tasks"][0]["toy_id"] == "t1"


def test_config_can_enable_and_disable_transports(lan_backend: MagicMock) -> None:
    with _lan_client() as client:
        assert client.get("/config").json()["transports"]["lan"] is True

        off = client.post("/config/transports", json={"lan": False})
        assert off.status_code == 200
        assert off.json()["transports"]["lan"] is False

        on = client.post("/config/lan-ip", json={"lan_ip": "10.0.0.5", "lan_port": 34567})
        assert on.status_code == 200
        assert on.json()["lan"] == {"ip": "10.0.0.5", "port": 34567}


def test_config_rejects_unknown_preset_dialect(lan_backend: MagicMock) -> None:
    with _lan_client() as client:
        response = client.post("/config/ble", json={"preset_uart_keyword": "nope"})
    assert response.status_code == 422


def test_disabled_transports_answer_409(lan_backend: MagicMock) -> None:
    with _lan_client() as client:
        assert client.post("/ble/scan").status_code == 409
        assert client.get("/socket/status").status_code == 409
        assert client.get("/socket/qr").status_code == 409


def test_ble_registry_and_supervisor_are_exposed_in_state() -> None:
    cfg = ServiceConfig(mode="ble")
    with TestClient(create_app(cfg)) as client:
        state = client.get("/state").json()
        registry = client.get("/ble/toys").json()

    assert state["transports"]["ble"] is True
    assert state["ble"]["registry"] == []
    assert state["ble"]["supervisor"]["enabled"] is True
    assert registry["toys"] == []
    assert registry["supervisor"]["toys"] == {}


def _build_fake_webui(root: Path) -> Path:
    directory = root / "webui"
    (directory / "assets").mkdir(parents=True)
    (directory / "index.html").write_text("<!doctype html><title>panel</title>", encoding="utf-8")
    (directory / "assets" / "app-abc123.js").write_text("export default 1;", encoding="utf-8")
    return directory


def test_spa_is_served_at_root_with_docs_still_available(
    lan_backend: MagicMock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    directory = _build_fake_webui(tmp_path)
    monkeypatch.setattr(webui_module, "webui_dir", lambda: directory)

    with _lan_client() as client:
        root = client.get("/")
        assert root.status_code == 200
        assert "panel" in root.text
        assert root.headers["cache-control"] == "no-store, max-age=0"

        asset = client.get("/assets/app-abc123.js")
        assert asset.status_code == 200
        assert "immutable" in asset.headers["cache-control"]

        # Deep links must reach the SPA shell, not a 404.
        deep = client.get("/settings", headers={"Accept": "text/html"})
        assert deep.status_code == 200
        assert "panel" in deep.text

        assert client.get("/docs").status_code == 200
        assert client.get("/redoc").status_code == 200
        assert client.get("/openapi.json").json()["info"]["title"]
        # API routes keep priority over the catch-all mount.
        assert client.get("/health").json() == {"status": "ok"}


def test_missing_webui_falls_back_to_a_placeholder_page(
    lan_backend: MagicMock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(webui_module, "webui_dir", lambda: tmp_path / "absent")

    with _lan_client() as client:
        root = client.get("/")
        assert root.status_code == 200
        assert "/docs" in root.text
        assert client.get("/meta").json()["webui"] is False


def test_webui_can_be_disabled(
    lan_backend: MagicMock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    directory = _build_fake_webui(tmp_path)
    monkeypatch.setattr(webui_module, "webui_dir", lambda: directory)

    with _lan_client(webui_enabled=False) as client:
        assert client.get("/").status_code == 404
        assert client.get("/health").status_code == 200
