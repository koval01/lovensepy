# FastAPI service (LAN + BLE) {#fastapi-lan-rest-tutorial}

**HTTP API** for dashboards, scripts, or mobile apps: **FastAPI** + **OpenAPI** at `/docs`, a browser [control panel](../web-ui.md) at `/`, and an **asyncio** scheduler (per-motor `Function` slots, preset and pattern sessions, `GET /tasks`). The implementation is **`lovensepy.services.http_api`** (importable as **`lovensepy.services.fastapi`** for backward compatibility): **LAN** mode uses **Game Mode** (`AsyncLANClient`); **BLE** mode uses **`BleDirectHub`**; **hybrid** runs several transports at once. All backends satisfy **`LovenseControlBackend`**, a `Protocol` aligned with the **`LovenseAsyncControlClient`** surface used by the scheduler (see [API reference — LovenseAsyncControlClient](../api-reference.md#lovenseasynccontrolclient)).

!!! tip "Just want to use your toys?"
    Run the service and open `http://127.0.0.1:8000/` — the bundled panel does discovery, connection and control for you. This page is about driving the API yourself.

## Requirements

```bash
pip install 'lovensepy[service]'
# BLE mode also needs:
pip install 'lovensepy[ble]'
```

## LAN mode (default)

### Environment

```bash
export LOVENSE_LAN_IP=192.168.1.100   # host running Lovense Remote (Game Mode)
export LOVENSE_SERVICE_MODE=lan        # default; can be omitted
# optional: LOVENSE_LAN_PORT=20011 LOVENSE_APP_NAME=... LOVENSE_TOY_IDS=id1,id2
# optional: LOVENSE_SESSION_MAX_SEC=60  # server /tasks row when preset/pattern time is 0
```

### Run the server

```bash
uvicorn lovensepy.services.http_api.app:app --host 0.0.0.0 --port 8000
```

Legacy shim (deprecated warning on import):

```bash
uvicorn examples.fastapi_lan_api:app --host 0.0.0.0 --port 8000
```

### Programmatic setup

```python
from lovensepy.services import ServiceConfig, create_app

app = create_app(ServiceConfig(mode="lan", lan_ip="192.168.1.100"))
```

Optional BLE advertisement callbacks (BLE mode only, see below): pass `on_ble_advertisement` and/or `on_ble_advertisement_async` to `create_app(...)`.

## BLE mode

Use direct BLE instead of Game Mode. Nothing is connected at startup: call `POST /ble/connect/auto` for the "just work" path, or scan and `POST /ble/connect` per address (or use callbacks to drive `BleDirectHub.add_toy` / `connect` yourself).

```bash
export LOVENSE_SERVICE_MODE=ble
# optional: LOVENSE_BLE_SCAN_TIMEOUT=8 LOVENSE_BLE_SCAN_PREFIX=LVS-  (empty prefix = all names)
# optional passive RSSI-style updates: LOVENSE_BLE_ADVERT_MONITOR=1 LOVENSE_BLE_ADVERT_MONITOR_INTERVAL=2
# optional presets: LOVENSEPY_BLE_PRESET_UART=Pat   (BleDirectClient default; service default is Preset for /command/preset)
# optional: LOVENSEPY_BLE_PRESET_EMULATE_PATTERN=1  (pulse/wave/… via pattern if UART preset lines ignored)
# optional: LOVENSE_BLE_AUTO_RECONNECT=0  (stop keeping registered toys connected)
uvicorn lovensepy.services.http_api.app:app --host 0.0.0.0 --port 8000
```

Extra HTTP routes (BLE only):

- `POST /ble/scan` — on-demand scan; query `timeout` optional; returns `address`, `name`, `rssi`
- `GET /ble/advertisements` — last merged advertisement map (scans plus the optional monitor)
- `GET /ble/toys` — registration view: address, link state, cached UART metadata, auto-reconnect status
- `POST /ble/connect` — body: `address`, optional `toy_id`, `name`, `toy_type`, `replace`
- `POST /ble/connect/auto` — scan, connect everything that answers, reconnect registered toys; one call for setup
- `POST /ble/reconnect/{toy_id}` — reconnect and clear the pause left by a manual disconnect
- `POST /ble/disconnect/{toy_id}` — GATT disconnect (toy stays registered, auto-reconnect pauses)
- `DELETE /ble/toys/{toy_id}` — disconnect and remove registration

`GET /toys` and command routes match LAN behavior once toys are connected. Registered toys are kept connected in the background with per-toy exponential backoff (`LOVENSE_BLE_AUTO_RECONNECT=0` to disable); the current state is in `GET /state` → `ble.supervisor`.

## Status in one call, live updates in one socket

- `GET /state` — toys merged across transports, active scheduler rows, BLE discovery and supervisor status, Socket API pairing state, capabilities and configuration. The toy list is cached for `LOVENSE_STATE_CACHE_TTL` seconds (default 2); `?fresh=true` bypasses it. This is what a dashboard should poll instead of hitting `/toys` in a loop — on BLE each `GET /toys` with `battery=true` costs a UART round-trip per device.
- `WS /ws` — the same snapshot pushed on change, with a heartbeat while idle. Send `{"op": "refresh"}` for an immediate fresh snapshot, `{"op": "ping"}` to get `{"type": "pong"}`.
- `GET /system/network` — URLs that reach this service (used for the "open on your phone" QR code).

## Configure at runtime

No restart and no environment variables needed:

- `POST /config/lan-ip` — `{"lan_ip": "192.168.1.100", "lan_port": 20011}` enables LAN in place
- `POST /config/socket` — Socket API credentials (memory only, never written to disk)
- `POST /config/ble` — auto-reconnect, background scanning, scan filter, preset dialect
- `POST /config/transports` — `{"lan": true, "ble": false}` to flip transports
- `GET /config` — current configuration without secrets

Endpoints belonging to a disabled transport answer **409**, so a client can tell "turned off" from "no such route".

## OpenAPI

Open `http://127.0.0.1:8000/docs` (ReDoc at `/redoc`) and try `GET /state`, `POST /command/preset`, `GET /tasks`, and the stop endpoints (`/command/stop/...` and batch variants).

## Behavior notes

- **BLE:** Patterns (and looped ``Function``) may hold work open while :class:`~lovensepy.ble_direct.client.BleDirectClient` steps UART timing. **Presets** from this service default to UART ``Preset:{n};`` (set ``LOVENSEPY_BLE_PRESET_UART=Pat`` to match the direct BLE client default). With ``LOVENSEPY_BLE_PRESET_EMULATE_PATTERN=1``, the four app names use pattern stepping instead (same idea as ``/command/pattern``). Timed presets still defer the hold + stop burst when the service passes ``wait_for_completion=False``. Direct :class:`~lovensepy.ble_direct.client.BleDirectClient` calls default to ``wait_for_completion=True``.
- Sending the **same** preset or pattern again for the same toy **extends** the session and **issues another transport command** with the new `time` (Lovense stops after each command’s `timeSec` otherwise).
- The service starts even when a transport is unusable (no LAN IP, no `bleak`, no Socket credentials): those endpoints answer **409** until you configure them via `/config/*` or the panel. Only a genuinely broken environment configuration falls back to the health-only app.
- `GET /tasks` returns **function** rows (`kind: function`), **function_loop** rows when `POST /command/function` uses `loop_on_time` / `loop_off_time`, and **preset** / **pattern** rows (`kind: preset` / `pattern`). Timestamps include `started_at` (UTC) and `started_monotonic_sec` for stable `remaining_sec` calculations.

See also the [Web control panel](../web-ui.md) page and the [Examples](../appendix.md#examples) table row for the HTTP service.
