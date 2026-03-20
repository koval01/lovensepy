"""Unit tests for Home Assistant MQTT bridge (no broker required)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

from lovensepy.integrations.mqtt.discovery import (
    build_discovery_payloads,
    default_availability_topic,
)
from lovensepy.integrations.mqtt.ha_bridge import (
    HAMqttBridge,
    _battery_from_payload,
    _clamp_feature,
    _parse_toy_list_data,
    _strength_from_payload,
)
from lovensepy.integrations.mqtt.state import StateDeduper
from lovensepy.integrations.mqtt.topics import (
    mqtt_safe_toy_id,
    subscribe_wildcard,
    topic_segment_to_action_name,
)


def test_mqtt_safe_toy_id_sanitizes():
    assert mqtt_safe_toy_id("ab/cd#+") == "ab_cd"


def test_subscribe_wildcard():
    assert subscribe_wildcard("lovensepy") == "lovensepy/+/+/set"


def test_topic_segment_to_action_name():
    assert topic_segment_to_action_name("vibrate") == "Vibrate"
    assert topic_segment_to_action_name("VIBRATE1") == "Vibrate1"
    assert topic_segment_to_action_name("nope") is None


def test_state_deduper():
    d = StateDeduper()
    assert d.should_publish("k", "1") is True
    assert d.should_publish("k", "1") is False
    assert d.should_publish("k", "2") is True


def test_parse_toy_list_data():
    toys = _parse_toy_list_data({"toys": {"a": {"name": "X"}, "b": {"id": "bid"}}})
    ids = {t["id"] for t in toys}
    assert ids == {"a", "bid"}


def test_clamp_feature_stroke():
    assert _clamp_feature("Stroke", 150) == 100
    assert _clamp_feature("Pump", 9) == 3


def test_battery_from_payload():
    assert _battery_from_payload({"battery": 42}) == 42
    assert _battery_from_payload({"data": {"level": 5}}) == 5
    assert _battery_from_payload({"value": 100}) == 100
    assert _battery_from_payload({"batteryLevel": "67"}) == 67
    assert _battery_from_payload(None) is None


def test_parse_toy_list_toy_list_and_battery():
    raw = {
        "type": "toy-list",
        "toyList": [
            {"id": "a1", "name": "Gush", "type": "gush", "battery": 88},
        ],
    }
    toys = _parse_toy_list_data(raw)
    assert len(toys) == 1
    assert toys[0]["id"] == "a1"
    assert toys[0]["toyType"] == "gush"
    assert _battery_from_payload(toys[0]) == 88


def test_strength_from_payload():
    out = _strength_from_payload(
        {"id": "t1", "strength": {"vibrate": 12}},
        "t1",
    )
    assert out == {"Vibrate": 12}


def test_build_discovery_payloads_contains_components():
    toy = {"id": "toy1", "name": "Lush", "toyType": "lush"}
    av = default_availability_topic("lovensepy")
    rows = build_discovery_payloads(topic_prefix="lovensepy", toy_dict=toy, availability_topic=av)
    topics = [r[0] for r in rows]
    assert any(t.startswith("homeassistant/number/") for t in topics)
    assert any(t.startswith("homeassistant/button/") for t in topics)
    assert any(t.startswith("homeassistant/select/") for t in topics)
    assert any(t.startswith("homeassistant/sensor/") for t in topics)
    for _, payload in rows:
        cfg = json.loads(payload)
        assert cfg["availability_topic"] == av
        assert "device" in cfg


def test_hamqttbridge_lazy_export_from_root():
    import lovensepy as lp
    from lovensepy.integrations.mqtt import HAMqttBridge

    assert getattr(lp, "HAMqttBridge") is HAMqttBridge


def _make_partial_bridge():
    b = HAMqttBridge("127.0.0.1", lan_ip="127.0.0.1", use_toy_events=False)
    b._topic_prefix = "lovensepy"
    b._toys = {
        "t1": {"id": "real1", "name": "Test", "toyType": "lush"},
    }
    published: list[tuple[str, str]] = []

    class _Mqtt:
        def publish(
            self,
            topic: str,
            payload: str | None = None,
            qos: int = 0,
            retain: bool = False,
            properties: object | None = None,
        ) -> None:
            published.append((topic, str(payload) if payload is not None else ""))

    b._mqtt = _Mqtt()
    lan = AsyncMock()
    b._lan = lan
    b._deduper = StateDeduper()
    return b, lan, published


def test_handle_command_function_request():
    async def _run():
        b, lan, _pub = _make_partial_bridge()
        await b._handle_command_topic("lovensepy/t1/vibrate/set", b"7")
        lan.function_request.assert_awaited_once()
        args, kwargs = lan.function_request.await_args
        assert args[0]["Vibrate"] == 7
        assert kwargs["toy_id"] == "real1"

    asyncio.run(_run())


def test_handle_command_stop():
    async def _run():
        b, lan, _pub = _make_partial_bridge()
        await b._handle_command_topic("lovensepy/t1/stop/set", b"PRESS")
        lan.stop.assert_awaited_once_with(toy_id="real1")

    asyncio.run(_run())


def test_handle_command_preset():
    async def _run():
        b, lan, _pub = _make_partial_bridge()
        await b._handle_command_topic("lovensepy/t1/preset/set", b"pulse")
        lan.preset_request.assert_awaited_once()
        args, kwargs = lan.preset_request.await_args
        assert args[0] == "pulse"
        assert kwargs.get("toy_id") == "real1"

    asyncio.run(_run())


def test_handle_toy_event_battery_changed_merged_payload():
    """Simulates ToyEventsClient callback after merging root toyId into data."""

    async def _run():
        b, _lan, pub = _make_partial_bridge()
        b._toys = {"toy1": {"id": "toy1", "toyType": "gush", "name": "Gush"}}
        await b._handle_toy_event("battery-changed", {"toyId": "toy1", "value": 73})
        bat_topic = None
        for topic, payload in pub:
            if topic.endswith("/battery/state"):
                bat_topic = (topic, payload)
        assert bat_topic is not None
        assert bat_topic[1] == "73"

    asyncio.run(_run())


def test_handle_command_clamps_vibrate():
    async def _run():
        b, lan, _pub = _make_partial_bridge()
        await b._handle_command_topic("lovensepy/t1/vibrate/set", b"99")
        args, kwargs = lan.function_request.await_args
        assert args[0]["Vibrate"] == 20

    asyncio.run(_run())


def test_handle_command_keeps_other_vector_levels():
    async def _run():
        b, lan, _pub = _make_partial_bridge()
        b._toys = {
            "t1": {"id": "real1", "name": "Test", "toyType": "dolce"},
        }
        b._feature_levels["t1"] = {"Vibrate1": 9, "Vibrate2": 4}
        await b._handle_command_topic("lovensepy/t1/vibrate1/set", b"11")
        args, _kwargs = lan.function_request.await_args
        assert args[0] == {"Vibrate1": 11, "Vibrate2": 4}

    asyncio.run(_run())
