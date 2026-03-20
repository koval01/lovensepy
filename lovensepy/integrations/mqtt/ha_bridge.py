"""
Home Assistant MQTT bridge: LAN control + Toy Events state -> MQTT Discovery.

Requires optional dependency: ``pip install 'lovensepy[mqtt]'`` (``paho-mqtt``).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..._constants import FUNCTION_RANGES, Presets
from ...standard.async_lan import AsyncLANClient
from ...toy_events.client import ToyEventsClient
from ...toy_utils import features_for_toy
from .discovery import build_discovery_payloads, default_availability_topic
from .state import StateDeduper
from .topics import (
    bridge_status_topic,
    feature_topic_segment,
    mqtt_safe_toy_id,
    state_topic,
    subscribe_wildcard,
    topic_segment_to_action_name,
)

__all__ = ["HAMqttBridge"]

_logger = logging.getLogger(__name__)

try:
    import paho.mqtt.client as mqtt
except ImportError as e:  # pragma: no cover - import guard
    mqtt = None  # type: ignore[assignment, misc]
    _IMPORT_ERROR = e
else:
    _IMPORT_ERROR = None


def _require_mqtt() -> None:
    if mqtt is None or _IMPORT_ERROR is not None:
        raise ImportError(
            "MQTT support requires paho-mqtt. Install with: pip install 'lovensepy[mqtt]'"
        ) from _IMPORT_ERROR


def _normalize_toy_dict_from_event(toy: dict[str, Any]) -> dict[str, Any]:
    """Map Toy Events field names to shapes expected by ``features_for_toy`` / display."""
    d = dict(toy)
    if "toyType" not in d and "type" in d:
        d["toyType"] = d.get("type")
    if "nickName" not in d and "nickname" in d:
        d["nickName"] = d.get("nickname")
    return d


def _parse_toy_list_data(data: Any) -> list[dict[str, Any]]:  # pylint: disable=too-many-return-statements
    """Normalize toy-list / GetToys-like payloads into toy dicts."""
    if data is None:
        return []
    if isinstance(data, list):
        return [t for t in data if isinstance(t, dict)]
    if not isinstance(data, dict):
        return []
    if "toyList" in data:
        raw = data["toyList"]
        if isinstance(raw, list):
            return [_normalize_toy_dict_from_event(dict(t)) for t in raw if isinstance(t, dict)]
    if "toys" in data:
        raw = data["toys"]
        if isinstance(raw, list):
            return [t for t in raw if isinstance(t, dict)]
        if isinstance(raw, dict):
            out: list[dict[str, Any]] = []
            for tid, t in raw.items():
                if isinstance(t, dict):
                    d = dict(t)
                    d.setdefault("id", str(tid))
                    out.append(d)
            return out
    # Flat mapping id -> toy dict
    if data and all(isinstance(v, dict) for v in data.values()):
        out = []
        for tid, t in data.items():
            d = dict(t)
            d.setdefault("id", str(tid))
            out.append(d)
        return out
    return []


def _clamp_feature(action: str, value: float | int) -> int | float:
    if action in FUNCTION_RANGES:
        lo, hi = FUNCTION_RANGES[action]
        v = float(value)
        return int(max(lo, min(hi, round(v)))) if isinstance(lo, int) else max(lo, min(hi, v))
    return value


def _coerce_battery_percent(value: Any) -> int | None:
    """Parse 0–100 % from API values (int, float, numeric string)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return max(0, min(100, value))
    if isinstance(value, float):
        return max(0, min(100, int(value)))
    if isinstance(value, str) and value.strip():
        try:
            return max(0, min(100, int(float(value.strip()))))
        except ValueError:
            return None
    return None


# Lovense Toy Events: battery-changed uses data.value; toy-list uses battery on each toy.
_BATTERY_KEYS: tuple[str, ...] = (
    "battery",
    "batteryLevel",
    "batteryPercent",
    "battery_level",
    "level",
    "value",
    "percent",
)


def _battery_from_payload(payload: Any) -> int | None:
    """Best-effort battery % from a flat or nested mapping (toy event / toy dict)."""
    if isinstance(payload, dict):
        for key in _BATTERY_KEYS:
            if key in payload:
                v = _coerce_battery_percent(payload.get(key))
                if v is not None:
                    return v
        nested = payload.get("data")
        if isinstance(nested, dict):
            return _battery_from_payload(nested)
    return None


def _strength_from_payload(payload: Any, toy_id: str) -> dict[str, int | float] | None:
    """Parse function-strength-changed into {ActionName: level}."""
    if not isinstance(payload, dict):
        return None
    tid = str(payload.get("id") or payload.get("toyId") or "")
    if tid and tid != str(toy_id):
        return None
    out: dict[str, int | float] = {}
    if "strength" in payload:
        s = payload["strength"]
        if isinstance(s, dict):
            for k, v in s.items():
                if isinstance(v, (int, float)):
                    mapped = topic_segment_to_action_name(str(k).lower())
                    an = mapped if mapped is not None else str(k)
                    out[an] = v
        elif isinstance(s, (int, float)):
            out["Vibrate"] = s
    for key in ("feature", "function"):
        if key in payload and "value" in payload:
            seg = str(payload[key]).lower()
            an = topic_segment_to_action_name(seg) or seg.capitalize()
            v = payload["value"]
            if isinstance(v, (int, float)):
                out[an] = v
    return out or None


class HAMqttBridge:
    """
    Publish Home Assistant MQTT Discovery and bridge commands to :class:`AsyncLANClient`.

    Runs ``paho-mqtt`` networking in a background thread; Lovense I/O uses asyncio on the
    caller's loop (the loop active when :meth:`start` is called).
    """

    def __init__(
        self,
        mqtt_host: str,
        mqtt_port: int = 1883,
        *,
        lan_ip: str,
        lan_port: int = 20011,
        toy_events_port: int | None = None,
        app_name: str = "lovensepy_ha",
        topic_prefix: str = "lovensepy",
        mqtt_username: str | None = None,
        mqtt_password: str | None = None,
        mqtt_client_id: str | None = None,
        refresh_interval: float = 45.0,
        use_https: bool = False,
        use_toy_events: bool = True,
    ) -> None:
        _require_mqtt()
        self._mqtt_host = mqtt_host
        self._mqtt_port = int(mqtt_port)
        self._lan_ip = lan_ip
        self._lan_port = int(lan_port)
        self._toy_events_port = (
            int(toy_events_port) if toy_events_port is not None else self._lan_port
        )
        self._app_name = app_name
        self._topic_prefix = topic_prefix.strip("/") or "lovensepy"
        self._mqtt_username = mqtt_username
        self._mqtt_password = mqtt_password
        self._mqtt_client_id = mqtt_client_id or f"{app_name}_bridge"
        self._refresh_interval = max(5.0, float(refresh_interval))
        self._use_https = use_https
        self._use_toy_events = use_toy_events

        self._loop: asyncio.AbstractEventLoop | None = None
        self._running = False
        self._lock = asyncio.Lock()

        self._lan: AsyncLANClient | None = None
        self._mqtt: Any = None
        self._deduper = StateDeduper()

        # safe_toy_id -> toy dict (includes real "id")
        self._toys: dict[str, dict[str, Any]] = {}
        self._published_discovery: set[str] = set()
        self._initialized_toy_states: set[str] = set()

        self._refresh_task: asyncio.Task[None] | None = None
        self._toy_events_task: asyncio.Task[None] | None = None
        self._toy_client: ToyEventsClient | None = None
        self._mqtt_ready: asyncio.Event | None = None

    @property
    def availability_topic(self) -> str:
        """MQTT availability topic used by all published entities."""
        return default_availability_topic(self._topic_prefix)

    def _mqtt_signal_connected(self) -> None:
        loop = self._loop
        ev = self._mqtt_ready
        if loop is not None and ev is not None:
            loop.call_soon_threadsafe(ev.set)

    def _mqtt_signal_disconnected(self) -> None:
        loop = self._loop
        ev = self._mqtt_ready
        if loop is not None and ev is not None:

            def _clear() -> None:
                ev.clear()

            loop.call_soon_threadsafe(_clear)

    def _schedule(self, coro: Any) -> None:
        loop = self._loop
        if loop is None or not self._running:
            return

        def _log_err(fut: asyncio.Future[Any]) -> None:
            try:
                fut.result()
            except asyncio.CancelledError:
                pass
            except Exception:  # pylint: disable=broad-exception-caught
                _logger.exception("HAMqttBridge async task failed")

        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        fut.add_done_callback(_log_err)

    async def start(self) -> None:
        """Connect MQTT and LAN client, publish discovery, start background tasks."""
        if self._running:
            return
        _require_mqtt()
        self._running = True
        self._loop = asyncio.get_running_loop()

        self._lan = AsyncLANClient(
            self._app_name,
            self._lan_ip,
            port=self._lan_port,
            use_https=self._use_https,
        )

        self._mqtt = mqtt.Client(  # type: ignore[union-attr]
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=self._mqtt_client_id,
        )
        if self._mqtt_username is not None:
            self._mqtt.username_pw_set(self._mqtt_username, self._mqtt_password)

        self._mqtt.on_connect = self._on_connect
        self._mqtt.on_message = self._on_message
        self._mqtt.on_disconnect = self._on_disconnect

        self._mqtt_ready = asyncio.Event()
        self._mqtt.connect_async(self._mqtt_host, self._mqtt_port, keepalive=60)
        self._mqtt.loop_start()
        try:
            await asyncio.wait_for(self._mqtt_ready.wait(), timeout=30.0)
        except TimeoutError as e:
            raise TimeoutError("MQTT broker did not connect within 30s") from e

        self._refresh_task = asyncio.create_task(self._refresh_loop())

        if self._use_toy_events:
            self._toy_events_task = asyncio.create_task(self._toy_events_loop())

    async def stop(self) -> None:
        """Stop background tasks, disconnect MQTT, close LAN HTTP client."""
        self._running = False
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
            self._refresh_task = None

        if self._toy_events_task:
            self._toy_events_task.cancel()
            try:
                await self._toy_events_task
            except asyncio.CancelledError:
                pass
            self._toy_events_task = None

        if self._toy_client:
            self._toy_client.disconnect()
            self._toy_client = None

        if self._mqtt is not None:
            try:
                self._mqtt.publish(
                    bridge_status_topic(self._topic_prefix),
                    "offline",
                    qos=0,
                    retain=True,
                )
            except Exception:  # pylint: disable=broad-exception-caught
                _logger.exception("Failed to publish MQTT offline")
            self._mqtt.loop_stop()
            self._mqtt.disconnect()
            self._mqtt = None

        if self._lan is not None:
            await self._lan.aclose()
            self._lan = None

        self._deduper.clear()
        self._mqtt_ready = None
        self._loop = None

    def _on_connect(
        self,
        client: Any,
        _userdata: Any,
        _flags: Any,
        reason_code: Any,
        _properties: Any,
    ) -> None:
        try:
            failed = reason_code.is_failure  # type: ignore[union-attr]
        except AttributeError:
            failed = int(reason_code) != 0  # type: ignore[arg-type]
        if failed:
            _logger.error("MQTT connect failed: %s", reason_code)
            return
        sub = subscribe_wildcard(self._topic_prefix)
        client.subscribe(sub, qos=0)
        _logger.info("MQTT connected, subscribed %s", sub)
        try:
            client.publish(
                bridge_status_topic(self._topic_prefix),
                "online",
                qos=0,
                retain=True,
            )
        except Exception:  # pylint: disable=broad-exception-caught
            _logger.exception("Failed to publish bridge online")
        self._mqtt_signal_connected()
        self._schedule(self._refresh_toys_and_discovery())

    def _on_disconnect(
        self,
        _client: Any,
        _userdata: Any,
        _disconnect_flags: Any,
        reason_code: Any,
        _properties: Any,
    ) -> None:
        _logger.warning("MQTT disconnected: %s", reason_code)
        self._mqtt_signal_disconnected()

    def _on_message(self, _client: Any, _userdata: Any, msg: Any) -> None:
        topic = getattr(msg, "topic", "")
        payload = getattr(msg, "payload", b"") or b""
        self._schedule(self._handle_command_topic(topic, payload))

    async def _refresh_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self._refresh_interval)
            try:
                await self._refresh_toys_and_discovery()
            except asyncio.CancelledError:
                break
            except Exception:  # pylint: disable=broad-exception-caught
                _logger.exception("Periodic toy refresh failed")

    async def _toy_events_loop(self) -> None:
        while self._running:

            async def on_event(event_type: str, data: Any) -> None:
                await self._handle_toy_event(event_type, data)

            self._toy_client = ToyEventsClient(
                self._lan_ip,
                port=self._toy_events_port,
                use_https=self._use_https,
                app_name=self._app_name,
                on_event=on_event,
            )
            try:
                await self._toy_client.connect()
            except asyncio.CancelledError:
                break
            except Exception:  # pylint: disable=broad-exception-caught
                _logger.exception("Toy Events connection ended with error")
            finally:
                if self._toy_client:
                    self._toy_client.disconnect()
                self._toy_client = None
            if self._running:
                await asyncio.sleep(3.0)

    async def _handle_toy_event(self, event_type: str, data: Any) -> None:
        if event_type == "toy-list":
            toys = _parse_toy_list_data(data)
            async with self._lock:
                for t in toys:
                    tid = str(t.get("id") or "")
                    if not tid:
                        continue
                    safe = mqtt_safe_toy_id(tid)
                    self._toys[safe] = t
                await self._publish_discovery_unlocked()
            for t in toys:
                tid = str(t.get("id") or "")
                if not tid:
                    continue
                level = _battery_from_payload(t)
                if level is not None:
                    safe = mqtt_safe_toy_id(tid)
                    await self._publish_state_str(
                        safe, "battery", str(level), force=True, mqtt_retain=True
                    )
        elif event_type == "battery-changed":
            if not isinstance(data, dict):
                return
            tid = str(data.get("id") or data.get("toyId") or "")
            if not tid:
                return
            safe = mqtt_safe_toy_id(tid)
            level = _battery_from_payload(data)
            if level is not None:
                await self._publish_state_str(
                    safe, "battery", str(level), force=True, mqtt_retain=True
                )
        elif event_type == "function-strength-changed":
            if not isinstance(data, dict):
                return
            tid = str(data.get("id") or data.get("toyId") or "")
            if not tid:
                return
            safe = mqtt_safe_toy_id(tid)
            strengths = _strength_from_payload(data, tid)
            if not strengths:
                return
            toy = self._toys.get(safe) or {"id": tid}
            supported = set(features_for_toy(toy))
            for action, raw in strengths.items():
                if action in supported:
                    seg = feature_topic_segment(action)
                    clamped = _clamp_feature(action, float(raw))
                    await self._publish_state_str(safe, seg, str(int(clamped)))

    async def _refresh_toys_and_discovery(self) -> None:
        if self._lan is None or self._mqtt is None:
            return
        async with self._lock:
            try:
                resp = await self._lan.get_toys()
            except Exception:  # pylint: disable=broad-exception-caught
                _logger.exception("GetToys failed")
                return
            data = resp.data
            if data is None:
                return
            toys = data.toys
            for info in toys:
                d = info.model_dump()
                tid = str(d.get("id") or "")
                if not tid:
                    continue
                safe = mqtt_safe_toy_id(tid)
                self._toys[safe] = d
                b_level = info.battery
                if b_level is None:
                    b_level = _battery_from_payload(d)
                if b_level is not None:
                    await self._publish_state_str(
                        safe,
                        "battery",
                        str(int(b_level)),
                        mqtt_retain=True,
                    )
            await self._publish_discovery_unlocked()

    async def _publish_discovery_unlocked(self) -> None:
        if self._mqtt is None:
            return
        av = bridge_status_topic(self._topic_prefix)
        for toy in self._toys.values():
            for disc_topic, payload in build_discovery_payloads(
                topic_prefix=self._topic_prefix,
                toy_dict=toy,
                availability_topic=av,
            ):
                key = disc_topic
                if key in self._published_discovery:
                    continue
                self._published_discovery.add(key)
                self._mqtt.publish(disc_topic, payload, qos=0, retain=True)
            safe = mqtt_safe_toy_id(str(toy.get("id")))
            if safe not in self._initialized_toy_states:
                self._initialized_toy_states.add(safe)
                for action in features_for_toy(toy):
                    seg = feature_topic_segment(action)
                    await self._publish_state_str(safe, seg, "0", force=True)

    async def _publish_state_str(
        self,
        safe_id: str,
        feature_segment: str,
        value: str,
        *,
        force: bool = False,
        mqtt_retain: bool = False,
    ) -> None:
        if self._mqtt is None:
            return
        key = f"{self._topic_prefix}/{safe_id}/{feature_segment}/state"
        if not force and not self._deduper.should_publish(key, value):
            return
        topic = state_topic(self._topic_prefix, safe_id, feature_segment)
        self._mqtt.publish(topic, value, qos=0, retain=mqtt_retain)

    async def _handle_command_topic(self, topic: str, payload: bytes) -> None:
        # pylint: disable=too-many-return-statements
        pfx = self._topic_prefix
        if not topic.startswith(pfx + "/"):
            return
        rest = topic[len(pfx) + 1 :]
        parts = rest.split("/")
        if len(parts) != 3 or parts[2] != "set":
            return
        safe_id, feature_segment, _ = parts
        if self._lan is None:
            return

        toy = self._toys.get(safe_id)
        if toy is None:
            _logger.warning("Unknown toy safe_id=%s (topic=%s)", safe_id, topic)
            return
        toy_id = str(toy.get("id"))

        text = payload.decode("utf-8", errors="replace").strip()

        try:
            if feature_segment == "stop":
                await self._lan.stop(toy_id=toy_id)
                for action in features_for_toy(toy):
                    seg = feature_topic_segment(action)
                    await self._publish_state_str(safe_id, seg, "0", force=True)
                return

            if feature_segment == "preset":
                if not text:
                    return
                preset = text.lower()
                valid = {str(p) for p in Presets}
                if preset not in valid:
                    _logger.warning("Invalid preset %r", text)
                    return
                await self._lan.preset_request(preset, toy_id=toy_id)
                await self._publish_state_str(safe_id, "preset", preset, force=True)
                return

            action = topic_segment_to_action_name(feature_segment)
            if action is None:
                _logger.warning("Unknown feature segment %r", feature_segment)
                return
            if action not in features_for_toy(toy):
                _logger.warning("Toy %s does not support action %s", toy_id, action)
                return
            try:
                level = int(float(text))
            except ValueError:
                _logger.warning("Invalid number payload %r", text)
                return
            level_i = int(_clamp_feature(action, level))
            await self._lan.function_request({action: level_i}, toy_id=toy_id)
            await self._publish_state_str(safe_id, feature_segment, str(level_i), force=True)
        except Exception:  # pylint: disable=broad-exception-caught
            _logger.exception("Command failed topic=%s", topic)
