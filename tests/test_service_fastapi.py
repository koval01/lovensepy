"""Tests for :mod:`lovensepy.services.fastapi` with mocked LAN backend."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi")

from lovensepy._models import CommandResponse, GetToysResponse
from lovensepy.ble_direct.client import LovenseBleAdvertisement
from lovensepy.services.fastapi.app import create_app
from lovensepy.services.fastapi.config import ServiceConfig


@pytest.fixture
def mock_lan(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    backend = MagicMock()
    backend.get_toys = AsyncMock(
        return_value=GetToysResponse.model_validate({"data": {"toys": []}})
    )
    ok = CommandResponse(code=200, type="OK", result=True)
    backend.function_request = AsyncMock(return_value=ok)
    backend.preset_request = AsyncMock(return_value=ok)
    backend.pattern_request = AsyncMock(return_value=ok)
    backend.stop = AsyncMock(return_value=ok)
    backend.aclose = AsyncMock()
    monkeypatch.setattr(
        "lovensepy.services.http_api.app.AsyncLANClient",
        lambda *args, **kwargs: backend,
    )
    return backend


def test_service_lan_health_and_meta(mock_lan: MagicMock) -> None:
    cfg = ServiceConfig(mode="lan", lan_ip="127.0.0.1", app_name="test")
    app = create_app(cfg)
    with TestClient(app) as client:
        h = client.get("/health")
        assert h.status_code == 200
        assert h.json() == {"status": "ok"}
        m = client.get("/meta")
        assert m.status_code == 200
        body = m.json()
        assert body["mode"] == "lan"
        assert body["toy_ids"] == []


def test_service_lan_tasks_empty(mock_lan: MagicMock) -> None:
    cfg = ServiceConfig(mode="lan", lan_ip="127.0.0.1")
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.get("/tasks")
        assert r.status_code == 200
        assert r.json() == {"tasks": []}


def test_service_function_loop_appears_in_tasks(mock_lan: MagicMock) -> None:
    cfg = ServiceConfig(mode="lan", lan_ip="127.0.0.1")
    app = create_app(cfg)
    with TestClient(app) as client:
        body = {
            "toy_id": "t1",
            "actions": {"Vibrate1": 5},
            "time": 12.0,
            "loop_on_time": 2.0,
            "loop_off_time": 3.0,
            "stop_previous": False,
        }
        p = client.post("/command/function", json=body)
        assert p.status_code == 200
        data = p.json()
        assert "scheduler_task_id" in data
        r = client.get("/tasks")
        assert r.status_code == 200
        tasks = r.json()["tasks"]
        assert len(tasks) == 1
        row = tasks[0]
        assert row["kind"] == "function_loop"
        assert row["toy_id"] == "t1"
        assert row["actions"] == {"Vibrate1": 5.0}
        assert row["loop_on_time"] == 2.0
        assert row["loop_off_time"] == 3.0


def test_service_config_ble_connect_client_kwargs_default_preset() -> None:
    cfg = ServiceConfig(mode="ble")
    assert cfg.ble_preset_uart_keyword == "Preset"
    assert cfg.ble_connect_client_kwargs() == {"ble_preset_uart_keyword": "Preset"}


def test_service_config_ble_connect_client_kwargs_explicit_pat() -> None:
    cfg = ServiceConfig(mode="ble", ble_preset_uart_keyword="Pat")
    assert cfg.ble_connect_client_kwargs()["ble_preset_uart_keyword"] == "Pat"


def test_ble_branding_resolve_lush_firmware_generation() -> None:
    cfg = ServiceConfig(mode="ble")
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.post(
            "/ble/branding/resolve",
            json={
                "advertised_name": "LVS-Lush",
                "toy_type_slug": "lush",
                "device_type_letter": "S",
                "firmware": "145",
            },
        )
        assert r.status_code == 200
        assert r.json() == {"nickName": "Lush 3", "source": "toy_config_firmware"}


def test_ble_branding_resolve_gush_flat_map_without_firmware() -> None:
    cfg = ServiceConfig(mode="ble")
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.post(
            "/ble/branding/resolve",
            json={
                "advertised_name": "LVS-Gush",
                "toy_type_slug": "gush",
                "device_type_letter": "ED",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["nickName"] == "Gush 2"
        assert body["source"] == "toy_config_flat_map"


def test_ble_scan_merges_into_advertisements_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_scan(*args: object, **kwargs: object) -> list[LovenseBleAdvertisement]:
        return [
            LovenseBleAdvertisement(
                address="AA:BB:CC:DD:EE:01",
                name="LVS-Test",
                rssi=-42,
            ),
        ]

    monkeypatch.setattr(
        "lovensepy.services.http_api.app.scan_lovense_ble_advertisements",
        fake_scan,
    )
    cfg = ServiceConfig(mode="ble")
    app = create_app(cfg)
    with TestClient(app) as client:
        scan_r = client.post("/ble/scan", params={"timeout": 1.0})
        assert scan_r.status_code == 200
        assert len(scan_r.json()["devices"]) == 1
        adv = client.get("/ble/advertisements").json()["advertisements"]
        assert adv["AA:BB:CC:DD:EE:01"] == {
            "address": "AA:BB:CC:DD:EE:01",
            "name": "LVS-Test",
            "rssi": -42,
        }


def test_services_package_reexports_create_app(mock_lan: MagicMock) -> None:
    from lovensepy.services import ServiceConfig, create_app

    app = create_app(ServiceConfig(mode="lan", lan_ip="127.0.0.1"))
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
