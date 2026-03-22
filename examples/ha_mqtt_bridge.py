#!/usr/bin/env python3
"""
Home Assistant MQTT bridge for Lovense Game Mode.

Publishes MQTT Discovery entities (numbers, stop button, presets, battery) and
forwards commands to the local Lovense HTTP API. Subscribes to Toy Events for
live battery / strength updates.

Requires:
    pip install 'lovensepy[mqtt]'

Environment:
    LOVENSE_LAN_IP       — phone running Lovense Remote (Game Mode), e.g. 192.168.1.100
    MQTT_HOST            — MQTT broker host (default: 192.168.1.2)
    MQTT_PORT            — broker port (default: 1883)
    MQTT_USER / MQTT_PASSWORD — optional broker auth
    LOVENSE_LAN_PORT     — HTTP command port (default: 20011)
    LOVENSE_TOY_EVENTS_PORT — WebSocket events port (default: same as LOVENSE_LAN_PORT)

Home Assistant: enable the MQTT integration pointing at the same broker. Entities
appear automatically under MQTT discovery.
"""

from __future__ import annotations

import asyncio
import os
import sys

from lovensepy import HAMqttBridge


async def _main() -> None:
    lan_ip = os.environ.get("LOVENSE_LAN_IP")
    if not lan_ip:
        print("Set LOVENSE_LAN_IP (Lovense Remote Game Mode host).", file=sys.stderr)
        raise SystemExit(1)

    mqtt_host = os.environ.get("MQTT_HOST", "192.168.1.2")
    mqtt_port = int(os.environ.get("MQTT_PORT", "1883"))
    lan_port = int(os.environ.get("LOVENSE_LAN_PORT", "20011"))
    toy_events_port = int(os.environ.get("LOVENSE_TOY_EVENTS_PORT", str(lan_port)))
    user = os.environ.get("MQTT_USER") or None
    password = os.environ.get("MQTT_PASSWORD") or None
    prefix = os.environ.get("MQTT_TOPIC_PREFIX", "lovensepy")

    bridge = HAMqttBridge(
        mqtt_host,
        mqtt_port,
        lan_ip=lan_ip,
        lan_port=lan_port,
        toy_events_port=toy_events_port,
        app_name=os.environ.get("LOVENSE_HA_APP_NAME", "lovensepy_ha"),
        topic_prefix=prefix,
        mqtt_username=user,
        mqtt_password=password,
    )

    await bridge.start()
    print(f"Bridge online. Availability: {bridge.availability_topic}", flush=True)
    print("Press Ctrl+C to exit.", flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        await bridge.stop()


def main() -> int:
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
