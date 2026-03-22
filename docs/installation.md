# Installation and setup

## What you need

Before using LovensePy, ensure you have:

- **Lovense Remote** or **Lovense Connect** app installed on your phone
- **Lovense toy** paired with the app
- **Same Wi-Fi network** as the device (required for LAN / Game Mode)
- **Developer token** (for Server / Socket API) — obtain from [Lovense Developer Dashboard](https://developer.lovense.com)
- **Callback URL** (for Server API QR pairing) — e.g. ngrok tunnel or similar to receive pairing callbacks

## Capabilities

- **Standard API LAN (Game Mode)**: GetToys, GetToyName, Function, Stop, Pattern, Preset, Position, PatternV2
- **Standard API Server**: Function, Pattern, Preset via Lovense cloud; `get_qr_code` for QR pairing
- **Standard Socket API**: getToken, getSocketUrl, WebSocket client for QR flow and remote control
- **Toy Events API**: Real-time events (toy-list, button-down, function-strength-changed, etc.)
- **Home Assistant MQTT bridge** (optional): MQTT Discovery + control via local Game Mode (`pip install 'lovensepy[mqtt]'`)
- **Direct BLE** (optional): `BleDirectHubSync` / `BleDirectHub` / `BleDirectClient` — see [Direct BLE](direct-ble.md)
- **FastAPI service** (`lovensepy.services.fastapi`, optional extra `[service]`): HTTP REST + OpenAPI `/docs` for Game Mode or BLE — see [FastAPI tutorial](tutorials/fastapi-lan-rest.md). Example shim: `examples/fastapi_lan_api.py`.

## Install

```bash
pip install lovensepy
```

MQTT / Home Assistant bridge (installs `paho-mqtt`):

```bash
pip install 'lovensepy[mqtt]'
```

Direct BLE (installs `bleak` and `pick` for the interactive BLE example menu):

```bash
pip install 'lovensepy[ble]'
```

**Dependencies:** `httpx`, `pydantic`, `websockets`, `hyperframe`. Optional: `paho-mqtt` (via `[mqtt]`), `bleak` + `pick` (via `[ble]`).

## Quick start (Game Mode)

### Install the package

Use the commands in [Install](#install) above.

### Enable Game Mode

In Lovense Remote: **Discover** → **Game Mode** → **Enable LAN**. Note the host **IP address** (for example `192.168.1.100`) and **port** (often **20011** for Remote, **34567** for Connect).

### Run a command

```python
from lovensepy import LANClient, Actions

client = LANClient("MyApp", "192.168.1.100", port=20011)
client.function_request({Actions.VIBRATE: 10}, time=3)
```

The toy should run at level 10 for 3 seconds.

!!! tip "Async code and swapping LAN / Server / BLE"
    For **`async def`** programs, **`AsyncLANClient`**, **`AsyncServerClient`**, **`BleDirectHub`**, and **`BleDirectClient`** all implement **`LovenseAsyncControlClient`**: the same control methods with a single type you can annotate, swapping only how you build the client. Sync **`LANClient`** / **`ServerClient`** mirror the names but stay blocking. See [Connection methods](connection-methods.md#same-control-code-different-transport) and [API reference — LovenseAsyncControlClient](api-reference.md#lovenseasynccontrolclient).

!!! note "Time units"
    The `time` argument is in **seconds**. The device holds the level until the next command or until you call `client.stop()`.

For longer guides, see the [tutorials index](index.md#tutorials).
