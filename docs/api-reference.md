# API Reference

### LANClient

Standard API LAN (Game Mode) client. Sends commands via HTTP/HTTPS to the Lovense app on the same network.

For async applications (Discord, Telegram, FastAPI, workers), use `AsyncLANClient`.

#### Constructor

```python
LANClient(
    app_name: str,
    local_ip: str | None = None,
    *,
    domain: str | None = None,
    port: int = 20011,
    ssl_port: int = 30011,
    use_https: bool = False,
    verify_ssl: bool = True,
    timeout: float = 10.0,
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `app_name` | str | — | Application name (e.g. "MyApp") |
| `local_ip` | str | None | Device IP (e.g. "192.168.1.100"). Use with `domain=None`. |
| `domain` | str | None | Pre-built domain (e.g. "192-168-1-100.lovense.club"). Use when you have domain from Socket API. |
| `port` | int | 20011 | HTTP port (Lovense Remote: 20011, Connect: 34567) |
| `ssl_port` | int | 30011 | HTTPS port |
| `use_https` | bool | False | Use HTTPS instead of HTTP |
| `verify_ssl` | bool | True | Verify SSL cert. If False, uses fingerprint pinning. |
| `timeout` | float | 10.0 | Request timeout in seconds |

**Example:**

```python
client = LANClient("MyApp", "192.168.1.100", port=20011)
```

**Class method:** `LANClient.from_device_info(app_name, domain, https_port=30011, **kwargs)` — Create from Socket API device info (e.g. `basicapi_update_device_info_tc` payload).

#### Methods

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `get_toys()` | — | `GetToysResponse` | Get connected toys. Uses a typed `data.toys[]` list. |
| `get_toys_name()` | — | `GetToyNameResponse` | Get connected toy names. |
| `function_request(actions, time=0, loop_on_time=None, loop_off_time=None, toy_id=None, stop_previous=None)` | `actions`: dict like `{Actions.VIBRATE: 10}` or per-motor `{Actions.VIBRATE1: 12, Actions.VIBRATE2: 6}`; `toy_id`: one id, list, or `None` for all | `CommandResponse` | Send Function command. `time` in seconds. |
| `stop(toy_id=None)` | `toy_id`: str or list | `CommandResponse` | Stop all motors. |
| `preset_request(name, time=0, toy_id=None)` | `name`: Presets enum or str | `CommandResponse` | Send Preset (pulse, wave, etc.). |
| `pattern_request(pattern, actions=None, interval=100, time=0, toy_id=None)` | `pattern`: list of 0–20; `actions`: e.g. `[Actions.VIBRATE1]` for one motor; `toy_id` optional | `CommandResponse` | Custom pattern. |
| `pattern_request_raw(strength, rule="V:1;F:;S:100#", time=0, toy_id=None)` | Raw rule/strength strings | `CommandResponse` | Advanced pattern. |
| `position_request(value, toy_id=None)` | `value`: 0–100 | `CommandResponse` | Position for Solace Pro. |
| `pattern_v2_setup(actions)` | `actions`: list of `{ts, pos}` | `CommandResponse` | PatternV2 Setup. |
| `pattern_v2_play(toy_id=None, start_time=None, offset_time=None, time_ms=None)` | — | `CommandResponse` | PatternV2 Play. |
| `pattern_v2_init_play(actions, toy_id=None, ...)` | — | `CommandResponse` | PatternV2 Setup + Play. |
| `pattern_v2_stop(toy_id=None)` | — | `CommandResponse` | PatternV2 Stop. |
| `pattern_v2_sync_time()` | — | `CommandResponse` | PatternV2 SyncTime. |
| `send_command(command_data, timeout=None)` | Raw command dict | `dict` | Low-level; returns raw dict. Raises `LovenseError` on failures. |
| `decode_response(response)` | Response dict | str | Human-readable response string. |

**Examples:**

```python
import time

with client.play({Actions.VIBRATE: 10}, time=5, toy_id="T123"):
    time.sleep(5)

# One toy, separate motors (Edge-class); check channels with features_for_toy(toy_dict)
client.function_request({Actions.VIBRATE1: 14}, time=2, toy_id="T123")
client.function_request({Actions.VIBRATE2: 8}, time=2, toy_id="T123")

# Pattern on motor 2 only
client.pattern_request([6, 12, 18], time=4, toy_id="T123", actions=[Actions.VIBRATE2])
```

See also the [LAN tutorial](tutorials/lan.md#step-5-one-toy-at-a-time-or-one-motor-at-a-time).

---

### ServerClient

Standard API Server client. Sends commands via Lovense cloud. Requires developer token and uid from QR pairing.

#### Constructor

```python
ServerClient(
    developer_token: str,
    uid: str,
    timeout: float = 10.0,
)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `developer_token` | str | From Lovense Developer Dashboard |
| `uid` | str | User ID from QR pairing callback |
| `timeout` | float | Request timeout |

#### Methods

Aligned with :class:`LANClient` for swapping transports: `get_toys`, `get_toys_name`, `function_request`, `stop`, `play`, `preset_request`, `pattern_request`, `pattern_request_raw`, `send_command`, `decode_response`.

`pattern_request` accepts either a **list of strengths** (same as LAN) or raw ``(rule, strength)`` positional strings; `pattern_request_raw(strength, rule=..., ...)` matches LAN parameter order.

**Per toy / per motor:** same `toy_id` and `Actions.VIBRATE1` / `VIBRATE2` as `LANClient` (after `get_toys()` to learn ids).

```python
r = client.get_toys()
toys = {t.id: t.model_dump() for t in r.data.toys} if r.data else {}
for tid in toys:
    client.function_request({Actions.VIBRATE: 7}, time=2, toy_id=tid)
```

---

### LovenseAsyncControlClient

Abstract base class (`abc.ABC`) for the **shared async control API**: same method names and compatible signatures on **`AsyncLANClient`**, **`AsyncServerClient`**, **`BleDirectClient`**, and **`BleDirectHub`**. Use it when you want one `async def` (or class field) that can hold any of those implementations — swap transport by changing only **how you construct** the client.

Sync **`LANClient`** / **`ServerClient`** are **not** subclasses; they mirror the same ideas with blocking calls. For new asyncio apps, prefer the async types + this ABC.

```python
from lovensepy import Actions, LovenseAsyncControlClient, AsyncLANClient, AsyncServerClient

async def pulse_once(client: LovenseAsyncControlClient) -> None:
    await client.function_request({Actions.VIBRATE: 8}, time=1.5)

# Pick one transport:
async def via_lan():
    async with AsyncLANClient("App", "192.168.1.50", port=20011) as c:
        await pulse_once(c)

async def via_server():
    async with AsyncServerClient("DEV_TOKEN", "user_uid") as c:
        await pulse_once(c)
```

The FastAPI service types its backend as **`LovenseControlBackend`** (a `Protocol` subset of this surface: `get_toys`, `function_request`, `stop`, `pattern_request`, `preset_request`). See `lovensepy.services.fastapi`.

---

### AsyncServerClient

Async version of the Standard API Server client for server-side bots.

Subclasses **`LovenseAsyncControlClient`**.

#### Lifecycle and resource management

`AsyncServerClient` is an async client and should be closed when you stop the process:

```python
from lovensepy import AsyncServerClient, Actions

async def run_once():
    async with AsyncServerClient("YOUR_DEV_TOKEN", "USER_UID") as client:
        await client.function_request({Actions.VIBRATE: 10}, time=2)
```

If you don't use `async with`, call `await client.aclose()` explicitly.

#### Per-request timeout overrides

High-level async methods accept `timeout` to override the client default for that single call.

---

### AsyncLANClient

Async version of LAN client for local applications (runs on the same network as the Lovense device).
If you're building a production bot that runs on your server, prefer `AsyncServerClient` or `SocketAPIClient` instead.

Subclasses **`LovenseAsyncControlClient`**.

#### Lifecycle and resource management

`AsyncLANClient` reuses HTTP sessions for better throughput. Close it when done:

```python
from lovensepy import AsyncLANClient, Actions

async def run_once():
    async with AsyncLANClient("MyBot", "192.168.1.100", port=20011) as client:
        await client.function_request({Actions.VIBRATE: 10}, time=2)
```

If you do not use `async with`, call `await client.aclose()` explicitly.

#### Per-request timeout overrides

All high-level async methods accept `timeout` to override client default timeout for that call:

```python
toys = await client.get_toys(timeout=2.0)  # quick call
await client.pattern_request([5, 10, 15, 20], time=20, timeout=15.0)  # longer call
```

#### Concurrency safety

For HTTPS with `verify_ssl=False`, certificate fingerprint verification is guarded internally to avoid duplicate concurrent checks when many commands hit the same endpoint at once.

---

### Server-side multi-session bot pattern (Discord/Telegram)

When your bot runs on a server, you typically use:
- `AsyncServerClient` (Standard API Server): cloud HTTP requests (token + `uid`)
- `SocketAPIClient` (Socket API): cloud WebSocket + event loop

Key idea: your backend must authenticate the incoming request, then resolve *the correct* Lovense session from your own stored mapping (e.g. in a database). Never accept a Lovense `uid` (or socket auth token) directly from the user request.

This avoids:
- data conflicts (shared mutable objects across users)
- accidental session mix-ups (sending commands to someone else’s `uid`)
- security issues (exposing or trusting client-provided session identifiers)

```python
import asyncio
from lovensepy import AsyncServerClient, Actions


class ServerSessionPool:
    """
    Keeps per-user clients in memory.

    user_id: your app user ID (Discord/Telegram).
    lovense_uid: stored in your DB after QR pairing / OAuth-like flow.
    """

    def __init__(self):
        self._clients: dict[str, AsyncServerClient] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, user_id: str, *, lovense_uid: str) -> AsyncServerClient:
        async with self._lock:
            client = self._clients.get(user_id)
            if client is None:
                client = AsyncServerClient(
                    developer_token="YOUR_DEV_TOKEN",
                    uid=lovense_uid,
                    timeout=5.0,
                )
                self._clients[user_id] = client
            return client

    async def close_session(self, user_id: str) -> None:
        async with self._lock:
            client = self._clients.pop(user_id, None)
        if client is not None:
            await client.aclose()

    async def shutdown(self) -> None:
        async with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        await asyncio.gather(*(c.aclose() for c in clients), return_exceptions=True)


sessions = ServerSessionPool()


async def handle_vibrate(user_id: str, level: int) -> None:
    # 1) Authenticate request on your server (Discord/Telegram auth).
    # 2) Look up lovense_uid for this authenticated user from your DB.
    lovense_uid = "LOOKED_UP_FROM_YOUR_DB"

    # 3) Resolve the correct per-user client.
    client = await sessions.get_or_create(user_id, lovense_uid=lovense_uid)

    # 4) Use per-request timeout if needed.
    await client.function_request({Actions.VIBRATE: level}, time=2, timeout=3.0)
```

Scaling notes (server-side):
- Use one shared event loop and non-blocking handlers (`await` everywhere).
- Reuse clients per user/session; avoid creating them per command.
- Put an upper bound on concurrency (e.g. `asyncio.Semaphore`) if a single user or a spike of users can spam commands.
- Add idle cleanup (TTL) so inactive sessions are closed automatically.
- For very large loads, shard bot workers/processes and keep per-process session maps.
- If you use `SocketAPIClient`, create and keep one WebSocket client per Lovense user session (per `ws_url`/auth token), and route commands through the correct per-session instance just like above.

---

### SocketAPIClient

Async WebSocket client for Socket API. Commands via WebSocket (or LAN HTTPS when `use_local_commands=True`).

#### Constructor

```python
SocketAPIClient(
    ws_url: str,
    *,
    use_local_commands: bool = False,
    app_name: str = "lovensepy",
    raise_on_disconnect: bool = False,
    on_socket_open: Callable | None = None,
    on_socket_close: Callable | None = None,
    on_socket_error: Callable[[Exception], ...] | None = None,
    on_socket_io_connected: Callable | None = None,
    on_event: Callable[[str, Any], ...] | None = None,
)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `ws_url` | str | WebSocket URL from `build_websocket_url` |
| `use_local_commands` | bool | Send commands via LAN HTTPS when device on same network |
| `app_name` | str | App name for local commands |
| `raise_on_disconnect` | bool | Raise `ConnectionError` when sending while disconnected |
| `on_socket_open`, `on_socket_close`, `on_socket_error` | Callable | Connection lifecycle callbacks |
| `on_socket_io_connected` | Callable | Fired when Socket.IO handshake complete |
| `on_event` | Callable | Fired for each Socket.IO event `(event_name, payload)` |

#### Methods

| Method | Description |
|--------|-------------|
| `connect()` | Async. Connect and start background ping/recv tasks (non-blocking). |
| `run_forever()` | Async. Connect and block until disconnected. |
| `start_background(auto_reconnect=False, retry_delay=5.0)` | Start `run_forever` (or reconnect loop) as a task. |
| `connect_with_retry(retry_delay=5.0, max_retries=None)` | Reconnect loop for 24/7 bots. |
| `wait_closed()` | Wait until current connection fully closes. |
| `disconnect()` | Close connection. |
| `send_command(command, action, time_sec=0, toy=None, ...)` | Send command (non-blocking). |
| `send_command_await(command, action, ...)` | Send command and await delivery. Use for stops. |
| `send_event(event, payload=None)` | Send raw Socket.IO event. |
| `on(event_name)` | Decorator to register per-event handlers. |
| `add_event_handler(event_name, handler)` | Register per-event handler programmatically. |

Event routing example:

```python
@client.on("basicapi_update_device_info_tc")
async def on_device_info(payload):
    print("Device info:", payload)
```

#### Properties

| Property | Type | Description |
|----------|------|-------------|
| `is_socket_io_connected` | bool | True when Socket.IO handshake done and ready for commands |
| `is_using_local_commands` | bool | True when commands go via LAN HTTPS |

---

### ToyEventsClient

Async WebSocket client for Toy Events API. Receives real-time events from toys. Lovense Remote only, port 20011.

#### Constructor

```python
ToyEventsClient(
    ip: str,
    port: int = 20011,
    use_https: bool = False,
    https_port: int = 30011,
    app_name: str = "lovensepy",
    *,
    on_open: Callable | None = None,
    on_close: Callable | None = None,
    on_error: Callable[[Exception], ...] | None = None,
    on_event: Callable[[str, Any], ...] | None = None,
)
```

#### Methods and Properties

| Method/Property | Description |
|-----------------|-------------|
| `connect()` | Async. Connect, request access, receive events until disconnected. |
| `disconnect()` | Close connection. |
| `is_connected` | True if WebSocket connected. |
| `is_access_granted` | True when user granted access in Lovense Remote. |

---

### BleDirectClient

**Direct BLE** control (optional `bleak`). See [Direct BLE](direct-ble.md#direct-ble) for limitations, multi-toy notes, and conflict with Lovense Remote.

Import: `from lovensepy import BleDirectClient` (lazy) or `from lovensepy.ble_direct import BleDirectClient`.

Subclasses **`LovenseAsyncControlClient`**.

#### Constructor

```python
BleDirectClient(
    address: str,
    *,
    uart_tx_uuid: str | None = None,
    uart_rx_uuid: str | None = None,
    write_with_response: bool = False,
    silence_on_link_loss: bool = True,
    link_loss_silence_timeout: float = 12.0,
    toy_type: str | None = None,
    uart_inter_command_delay_s: float = 0.015,
    post_timed_function_silence_cooldown_s: float = 0.22,
    dual_single_channel_prime_peer_zero: bool = True,
    dual_single_channel_prime_delay_s: float = 0.045,
)
```

| Parameter | Description |
|-----------|-------------|
| `address` | BLE device address (OS-specific string, e.g. UUID on macOS). |
| `uart_tx_uuid` | If set, that characteristic must exist after connect (write flags optional). If `None`, tries `DEFAULT_UART_TX_UUIDS` (5030/455a/5330/5730-style Lovense UART, Nordic NUS TX, legacy `fff2`), then any `????0002-????-4bd4-bbd5-a6920e4c5653` Lovense-family TX. |
| `uart_rx_uuid` | Optional **RX** (notify) UUID. If `None`, the client tries `DEFAULT_UART_RX_UUIDS` and the sibling of TX (`…0002…` → `…0003…`). If nothing matches, query helpers are unavailable but `set_vibration`/`send_uart_command` still work. |
| `write_with_response` | Passed through to `bleak`’s `write_gatt_char(..., response=...)`. |
| `silence_on_link_loss` | If true (default), an **unexpected** disconnect schedules a short **reconnect** and writes the full stop list from `uart_catalog`. |
| `link_loss_silence_timeout` | Seconds for that reconnect + service discovery (default 12). |
| `toy_type` | Optional Lovense type string (`lush`, `edge`, `solace pro`, …) for :meth:`silence_all_motors` defaults and for :func:`lovensepy.toy_utils.features_for_toy` fallbacks. |
| `uart_inter_command_delay_s` | Seconds to wait between **consecutive UART lines** sent from one logical update (e.g. dual-motor `Vibrate1` then `Vibrate2`). Default matches :data:`DEFAULT_UART_INTER_COMMAND_DELAY_S` (~15 ms); use `0` for back-to-back writes without delay. |
| `post_timed_function_silence_cooldown_s` | After :meth:`function_request` with ``time > 0``, the client calls :meth:`silence_all_motors` then waits this many seconds before returning (default :data:`DEFAULT_POST_TIMED_FUNCTION_SILENCE_COOLDOWN_S`, ~220 ms). Helps the **next** command apply on some BLE stacks. Use `0` to disable. |
| `dual_single_channel_prime_peer_zero` | For toys with **both** ``Vibrate1`` and ``Vibrate2``, when a logical update maps to a **single** non-zero motor line **and** the last non-zero motor (tracked across :meth:`silence_all_motors`) was the **peer**, send that peer as ``…:0;`` in a **separate** preceding GATT write (default on). Avoids priming on every step (which could feel “one step behind” on some firmware). Set ``False`` to disable. Raw :meth:`send_uart_command` clears the motor memory. |
| `dual_single_channel_prime_delay_s` | Seconds to wait after the peer-zero prime write and before the main line (default :data:`DEFAULT_DUAL_SINGLE_CHANNEL_PRIME_DELAY_S`, ~45 ms). Use ``0`` to omit the delay (still two writes). |

#### Methods and properties

| Method / property | Description |
|-------------------|-------------|
| `async connect()` | Connect, resolve TX UUID (macOS: serialized across clients), raise `LovenseBLEError` if `bleak` is missing or no matching characteristic. |
| `async disconnect()` | Close BLE link. |
| `async aclose()` | Alias for `disconnect()`. |
| `async set_vibration(level)` | Sends `Vibrate:{level};` for `level` in `0..20`; skips duplicate consecutive levels. |
| `async send_uart_command(str, *, encoding, ensure_semicolon)` | Encode and write a UART command string; clears vibrate dedupe. |
| `async send_uart_bytes(bytes)` | Raw write to TX; clears vibrate dedupe. |
| `async silence_all_motors(toy_type=None)` | Stop burst: type-specific if `toy_type` or constructor `toy_type` is set, else the full `uart_catalog` list. |
| `async query_uart_line(command)` | Subscribe to RX, write command, return first `…;` line (for custom queries). |
| `async fetch_battery_percent()` | `Battery;` → percent 0–100. |
| `async fetch_device_type_fields()` | `DeviceType;` → :class:`DeviceTypeFields` (model letter, firmware, BT hex). |
| `async fetch_ble_snapshot(adv_name=None)` | Battery + device type + `suggested_features` from `LVS-…` name slug. |
| `is_connected` | True when the underlying client reports connected. |
| `uart_tx_uuid` | Resolved characteristic UUID after `connect()`, else `None`. |
| `uart_rx_uuid` | Resolved RX notify UUID after `connect()`, else `None` if not found. |
| `actions`, `presets`, `error_codes` | Same enums / maps as :class:`~lovensepy.standard.async_lan.AsyncLANClient` (`Actions`, `Presets`, `ERROR_CODES`) for drop-in style code. |
| `last_command` | Last JSON-style payload passed to `send_command`, mirroring the LAN client. |
| `async function_request(...)`, `async stop(...)`, `play(...)` | Standard API names: drive UART instead of HTTP (see `lovensepy/ble_direct/standard_compat.py`). Returns :class:`~lovensepy._models.CommandResponse` with `data.transport == "ble"`. |
| `async pattern_request` / `pattern_request_raw` | Emulates LAN pattern timing by stepping strengths over UART (not identical to in-app Pattern). |
| `async preset_request` | Sends UART ``Pat:{n};`` or ``Preset:{n};`` (integer **n**). Prefix: constructor ``ble_preset_uart_keyword``. Names map through :data:`~lovensepy.PRESET_BLE_PAT_INDEX`; digit-only ``name`` is a raw slot (0–20). |
| `async position_request` | Sends `Position:{0..100};` over UART. |
| `async send_command` | Routes the same `command` JSON keys as LAN (`Function`, `Pattern`, `Preset`, `Position`, …) to UART. |
| `decode_response` | Same human-readable formatting helper as the async LAN client. |
| `async get_toys` / `get_toys_name`, `async pattern_v2_*` | Raise `LovenseBLEError` — those flows need the Lovense app bridge (LAN). |

**Helpers** (same `lovensepy.ble_direct` import path): `scan_lovense_ble_devices(timeout, *, name_prefix="LVS-"|None)` → list of `(address, name)`; `build_vibrate_command(level)` → `Vibrate:n;` string; `DEFAULT_UART_INTER_COMMAND_DELAY_S`, `DEFAULT_POST_TIMED_FUNCTION_SILENCE_COOLDOWN_S`, `DEFAULT_DUAL_SINGLE_CHANNEL_PRIME_DELAY_S`; `ble_uart_features_for_toy_type`, `ble_stop_command_strings_for_toy_type`, `DEFAULT_FULL_STOP_COMMANDS`, `default_full_stop_payloads` (UART strings and per-type motor hints); `parse_battery_percent`, `parse_device_type_fields`, `DeviceTypeFields`.

#### BleDirectHub (multi-toy, LAN-shaped API)

Import: `from lovensepy import BleDirectHub` (lazy) or `from lovensepy.ble_direct import BleDirectHub`.

Subclasses **`LovenseAsyncControlClient`**.

One object in your code; **each registered toy** still has its own `BleDirectClient` and BLE connection. You choose string ids (like LAN `toyId`), map them to BLE addresses, then call the same method names as `AsyncLANClient` / `BleDirectClient`: `function_request`, `preset_request`, `stop`, `send_command`, `get_toys`, `get_toys_name`, `play(toy_id=...)` (context manager requires **one** id), etc. **`toy_id=None`** (or omitting `toy` in `send_command`) means **all** registered toys.

```python
hub = BleDirectHub()
hub.add_toy("a", "BLE-ADDRESS-1", name="LVS-Edge", toy_type="edge")
hub.add_toy("b", "BLE-ADDRESS-2", name="LVS-Lush")
await hub.connect_all()
await hub.preset_request(hub.presets.PULSE, time=10.0, toy_id=None)  # everyone
await hub.function_request({hub.actions.VIBRATE: 5}, toy_id="b")      # one
await hub.function_request({hub.actions.VIBRATE1: 10}, time=2, toy_id="a")  # Edge-style motor 1
await hub.function_request({hub.actions.VIBRATE2: 8}, time=2, toy_id="a")   # motor 2
await hub.disconnect_all()
```

Or skip manual addresses: ``await hub.discover_and_connect(timeout=10.0)`` scans ``LVS-…`` advertisers, registers stable ids, connects, and optionally reads UART so ``get_toys`` matches the LAN-style tutorial. The ``timeout`` is **scan listen time only**, not how long motors run.

`get_toys` is **synthetic** (registration + connection state + optional UART battery / type hints), not the Lovense app’s own inventory.

---

### HAMqttBridge

MQTT bridge for **Home Assistant** (MQTT Discovery). Uses `AsyncLANClient` for commands and `ToyEventsClient` for battery / strength updates. **Requires** optional dependency `paho-mqtt` (`pip install 'lovensepy[mqtt]'`).

Import: `from lovensepy import HAMqttBridge` (lazy-loaded) or `from lovensepy.integrations.mqtt import HAMqttBridge`.

#### Constructor

```python
HAMqttBridge(
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
)
```

| Parameter | Description |
|-----------|-------------|
| `mqtt_host`, `mqtt_port` | MQTT broker (Home Assistant integration uses the same broker). |
| `lan_ip`, `lan_port` | Lovense Remote Game Mode HTTP API (`/command`). |
| `toy_events_port` | Toy Events WebSocket (default: same as `lan_port`, usually 20011). |
| `topic_prefix` | Base prefix for state/command topics and discovery device grouping. |
| `use_toy_events` | If False, only polling `GetToys` is used (no live battery/strength). |

#### Methods and properties

| Method / property | Description |
|-------------------|-------------|
| `async start()` | Connect MQTT, subscribe, publish discovery, start refresh + Toy Events tasks. |
| `async stop()` | Cancel tasks, publish `offline`, disconnect. |
| `availability_topic` | Retained bridge status topic (e.g. `lovensepy/bridge/status`). |

---

### Pattern Players

High-level API for sine waves and combo patterns.

#### SyncPatternPlayer

For use with `LANClient`. Synchronous.

```python
SyncPatternPlayer(client: LANClient, toys: dict[str, dict] | GetToysResponse)
```

| Method | Parameters | Description |
|--------|------------|-------------|
| `play_sine_wave(toy_id, feature, duration_sec=5, num_steps=100, stop_prev_first=True)` | `feature`: e.g. "Vibrate1" | Play sine wave on one feature. |
| `play_combo(targets, duration_sec=4, num_steps=100)` | `targets`: `[(toy_id, feature), ...]` | Play combo with random phases. |
| `stop(toy_id)` | — | Stop toy. |
| `features(toy_id)` | — | Get features for toy. |

**Example:**

```python
player = SyncPatternPlayer(client, toys)
player.play_sine_wave("T123", "Vibrate1", duration_sec=5)
player.play_combo([("T1", "Vibrate1"), ("T2", "Vibrate")], duration_sec=4)
player.stop("T123")
```

#### AsyncPatternPlayer

For use with `SocketAPIClient`. Same methods, async (use `await`).

```python
player = AsyncPatternPlayer(client, toys)
await player.play_sine_wave("T123", "Vibrate1", duration_sec=5)
await player.stop("T123")
```

---

### Utilities

| Function | Parameters | Returns | Description |
|----------|------------|---------|-------------|
| `get_token(developer_token, uid, uname=None, utoken=None, timeout=10)` | — | str | Get auth token for Socket API. Raises on error. |
| `get_socket_url(auth_token, platform, timeout=10)` | `platform`: Website Name from Dashboard | dict | Get socket info dict. |
| `build_websocket_url(socket_info, auth_token)` | — | str | Build full wss:// URL. |
| `get_qr_code(developer_token, uid, uname=None, utoken=None, timeout=10)` | — | dict | Get QR for Server API. Returns `{qr, code}`. See security note in docstring. |
| `features_for_toy(toy)` | `toy`: dict from GetToys | list[str] | Get features (e.g. `["Vibrate1", "Rotate"]`). |
| `stop_actions(toy)` | `toy`: dict | dict | Build `{Vibrate1: 0, ...}` to stop. |

