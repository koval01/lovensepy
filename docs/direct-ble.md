# Direct BLE {#direct-ble}

!!! warning "Compatibility"
    Lovense does not publish a stable BLE contract for third parties. Default UART behaviour works on many devices but is **not guaranteed** for every model or firmware.

`BleDirectHubSync` / `BleDirectHub` are meant to **drop in next to** `LANClient` / `AsyncLANClient` and `ServerClient` / `AsyncServerClient`: same `get_toys`, `function_request`, `play`, `preset_request`, `pattern_request`, `stop` flow after you connect. The async hub and :class:`~lovensepy.ble_direct.client.BleDirectClient` implement **`LovenseAsyncControlClient`** with the other async transports. See [Connection methods — Same control code, different transport](connection-methods.md#same-control-code-different-transport) and [API reference — LovenseAsyncControlClient](api-reference.md#lovenseasynccontrolclient).

## Install

```bash
pip install 'lovensepy[ble]'
```

You need a working Bluetooth adapter and OS permissions. Many toys allow **only one BLE central** — disconnect **Lovense Remote** (or any other app) before connecting from your machine.

## Quick start (same flow as LAN)

Use **`BleDirectHubSync`** for normal scripts: blocking calls, same method names as **`LANClient`** where BLE supports them (`get_toys`, `play`, `function_request`, `preset_request`, `pattern_request`, `stop`, …).

```python
import time
from lovensepy import BleDirectHubSync, Actions, Presets, features_for_toy

with BleDirectHubSync() as client:
    client.discover_and_connect(timeout=10.0)

    response = client.get_toys()
    toys = {toy.id: toy.model_dump() for toy in response.data.toys} if response.data else {}

    # Same idea as the LAN tutorial: vibration while the block runs, then auto-stop.
    # Use time=0: on BLE, time>0 is enforced inside function_request (blocking), while LAN
    # sends timeSec to the app and returns immediately — time=0 + time.sleep matches LAN.
    with client.play({Actions.VIBRATE: 10}, time=0):
        time.sleep(5)

    client.preset_request(Presets.PULSE, time=5)
    time.sleep(5)

    client.pattern_request([5, 10, 15, 20], time=4)
    time.sleep(4)

    client.stop()
```

**Timed one-liner (BLE-specific):** `client.function_request({Actions.VIBRATE: 10}, time=5)` already waits for the hold plus internal motor stop — no extra `time.sleep`, and no need for `play`.

**One toy vs all:** pass `toy_id` from `get_toys()` into `play`, `function_request`, `preset_request`, or `pattern_request`. Leave it unset (default `None`) to address every toy registered on the hub.

### Per toy and per motor (dual vibrators)

Same `toy_id` and **`Actions.VIBRATE1`** / **`Actions.VIBRATE2`** as on LAN. Use **`features_for_toy`** on each row’s `model_dump()` to see which channels exist.

If you paste only this snippet into a REPL, run once: `from lovensepy import features_for_toy` (it is already included in the quick-start import above).

```python
import time
from lovensepy import Actions, Presets, features_for_toy  # omit if you ran the quick start import

# `client` is BleDirectHubSync after discover_and_connect; `toys` from get_toys() as above

for tid, row in toys.items():
    client.function_request({Actions.VIBRATE: 8}, time=2, toy_id=tid)
    time.sleep(0.3)

first_id, first_row = next(iter(toys.items()))
if "Vibrate1" in features_for_toy(first_row) and "Vibrate2" in features_for_toy(first_row):
    client.function_request({Actions.VIBRATE1: 12}, time=2, toy_id=first_id)
    time.sleep(0.25)
    client.function_request({Actions.VIBRATE2: 6}, time=2, toy_id=first_id)

client.preset_request(Presets.WAVE, time=4, toy_id=first_id)
client.pattern_request([4, 8, 12], time=3, toy_id=first_id, actions=[Actions.VIBRATE2])
```

On BLE, prefer short gaps between back-to-back motor commands on dual-motor toys if the host stack drops writes (see troubleshooting below).

## Async code

Inside `async def`, use **`BleDirectHub`** and `await` (same methods, prefixed with `await`):

```python
import asyncio
from lovensepy import BleDirectHub, Actions

async def main() -> None:
    hub = BleDirectHub()
    try:
        await hub.discover_and_connect(timeout=10.0)
        response = await hub.get_toys()
        _ = response
        await hub.function_request({Actions.VIBRATE: 10}, time=5, toy_id=None)
    finally:
        await hub.disconnect_all()

asyncio.run(main())
```

`async with hub:` is supported if you prefer a context manager.

## Notes

- **Built-in presets** (`pulse`, `wave`, `fireworks`, `earthquake`): over BLE the client sends **`Pat:{n};`** or **`Preset:{n};`** (integer **`n`**). Connect uses **`Pat`**; some firmware / UART docs expect **`Preset`**. Set the prefix with constructor **`ble_preset_uart_keyword`**. Names map via :data:`~lovensepy.PRESET_BLE_PAT_INDEX` (default **1–4**); you can also pass a **digit-only** ``name`` (0–20) for a raw slot. If the toy **ignores Pat/Preset** but **pattern stepping works**, use **`ble_preset_emulate_with_pattern=True`** or FastAPI **`LOVENSEPY_BLE_PRESET_EMULATE_PATTERN=1`** (reconnect after changing). Otherwise use **`/command/pattern`**. **FastAPI BLE** defaults to **`Preset`** on **`/ble/connect`**; **`LOVENSEPY_BLE_PRESET_UART=Pat`** switches to Connect-style **`Pat`**.
- **Several toys:** `discover_and_connect` registers each matching advertiser (default name prefix **`LVS-`**) and opens one `BleDirectClient` per address.
- **macOS:** peripheral `connect` / discovery is **serialized** across clients to reduce CoreBluetooth flakiness.
- **Sync timeouts:** `BleDirectHubSync` runs BLE on a background asyncio loop. Each call waits up to **`LOVENSEPY_BLE_SYNC_TIMEOUT`** seconds (default **300**; `0`, `none`, or `inf` = unbounded). Do **not** use `BleDirectHubSync` from code that already has a running asyncio loop — use `BleDirectHub` and `await` instead.
- **Link loss:** by default the client may reconnect and send a UART stop burst; whether motors stop without UART is **firmware-dependent**. See **`silence_on_link_loss`** on `BleDirectClient` in the API reference.

## Where to read more

- **Constructors, UART tuning, dual-motor behaviour:** [API reference — BleDirectClient / hub](api-reference.md#bledirectclient).
- **Interactive scan / multi-select CLI:** `python examples/ble_direct_scan_and_two.py`.
- **Hardware integration test** (real radio): `uv run --extra ble pytest tests/test_ble_direct_integration.py -v -s`.

## Troubleshooting (motors quiet while logs look fine)

- **Dual-motor (Edge / Diamo):** two GATT writes per update; try `write_with_response=True` in `client_kwargs` on `add_toy` / `discover_and_connect`, or increase `uart_inter_command_delay_s`. After timed `function_request`, the client waits briefly before the next command (`post_timed_function_silence_cooldown_s`).
- **Host stack (especially macOS):** increase pauses between steps; the integration scenario honours `LOVENSE_BLE_INTER_STEP_SEC` and related `LOVENSE_BLE_DUAL_PROBE_*` variables.
