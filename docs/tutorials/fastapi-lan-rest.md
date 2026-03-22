# FastAPI service (LAN + BLE) {#fastapi-lan-rest-tutorial}

**HTTP API** for dashboards, scripts, or mobile apps: **FastAPI** + **OpenAPI** at `/docs`, and an **asyncio** scheduler (per-motor `Function` slots, preset and pattern sessions, `GET /tasks`). The implementation is **`lovensepy.services.fastapi`** (under the **`lovensepy.services`** package): **LAN** mode uses **Game Mode** (`AsyncLANClient`); **BLE** mode uses **`BleDirectHub`** with manual scan/connect. Both backends satisfy **`LovenseControlBackend`**, a `Protocol` aligned with the **`LovenseAsyncControlClient`** surface used by the scheduler (see [API reference — LovenseAsyncControlClient](../api-reference.md#lovenseasynccontrolclient)).

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
uvicorn lovensepy.services.fastapi.app:app --host 0.0.0.0 --port 8000
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

Use direct BLE instead of Game Mode. Toys are **not** auto-connected: scan, then `POST /ble/connect` (or use callbacks to drive `BleDirectHub.add_toy` / `connect` yourself).

```bash
export LOVENSE_SERVICE_MODE=ble
# optional: LOVENSE_BLE_SCAN_TIMEOUT=8 LOVENSE_BLE_SCAN_PREFIX=LVS-  (empty prefix = all names)
# optional passive RSSI-style updates: LOVENSE_BLE_ADVERT_MONITOR=1 LOVENSE_BLE_ADVERT_MONITOR_INTERVAL=2
# optional presets: LOVENSEPY_BLE_PRESET_UART=Pat   (Connect-style; service default is Preset for /command/preset)
# optional: LOVENSEPY_BLE_PRESET_EMULATE_PATTERN=1  (pulse/wave/… via pattern if UART preset lines ignored)
uvicorn lovensepy.services.fastapi.app:app --host 0.0.0.0 --port 8000
```

Extra HTTP routes (BLE only):

- `POST /ble/scan` — on-demand scan; query `timeout` optional; returns `address`, `name`, `rssi`
- `GET /ble/advertisements` — last merged advertisement map when the optional monitor is enabled
- `POST /ble/connect` — body: `address`, optional `toy_id`, `name`, `toy_type`, `replace`
- `POST /ble/disconnect/{toy_id}` — GATT disconnect (toy stays registered)
- `DELETE /ble/toys/{toy_id}` — disconnect and remove registration

`GET /toys` and command routes match LAN behavior once toys are connected.

## OpenAPI

Open `http://127.0.0.1:8000/docs` and try `GET /toys`, `POST /command/preset`, `GET /tasks`, and the stop endpoints (`/command/stop/...` and batch variants).

## Behavior notes

- **BLE:** Patterns (and looped ``Function``) may hold work open while :class:`~lovensepy.ble_direct.client.BleDirectClient` steps UART timing. **Presets** from this service default to UART ``Preset:{n};`` (set ``LOVENSEPY_BLE_PRESET_UART=Pat`` for Lovense Connect parity). With ``LOVENSEPY_BLE_PRESET_EMULATE_PATTERN=1``, the four app names use pattern stepping instead (same idea as ``/command/pattern``). Timed presets still defer the hold + stop burst when the service passes ``wait_for_completion=False``. Direct :class:`~lovensepy.ble_direct.client.BleDirectClient` calls default to ``wait_for_completion=True``.
- Sending the **same** preset or pattern again for the same toy **extends** the session and **issues another transport command** with the new `time` (Lovense stops after each command’s `timeSec` otherwise).
- `GET /tasks` returns **function** rows (`kind: function`), **function_loop** rows when `POST /command/function` uses `loop_on_time` / `loop_off_time`, and **preset** / **pattern** rows (`kind: preset` / `pattern`). Timestamps include `started_at` (UTC) and `started_monotonic_sec` for stable `remaining_sec` calculations.

See also the [Examples](../appendix.md#examples) table row for the HTTP service.
