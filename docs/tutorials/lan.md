# LAN Game Mode and direct BLE hub

The **Standard**-style calls below (`get_toys`, `play`, `preset_request`, `pattern_request`, `stop`) are shared with [**Standard Server**](../api-reference.md#serverclient) (`ServerClient` / `AsyncServerClient` with token + `uid`) and [**Direct BLE**](../direct-ble.md) (`BleDirectHubSync` / `BleDirectHub` after `discover_and_connect`). Swap the client class and connection setup; keep the middle of your script.

For **`async def`** code, you can annotate the client as **`LovenseAsyncControlClient`** so the same function body works with `AsyncLANClient`, `AsyncServerClient`, `BleDirectHub`, or `BleDirectClient` — see [LovenseAsyncControlClient](../api-reference.md#lovenseasynccontrolclient).

## Game Mode (LAN)

### Step 1: Enable Game Mode

- Lovense Remote: **Discover** → **Game Mode** → **Enable LAN**
- Lovense Connect: **Scan QR** → **Other connection modes** → **IP Address**

### Step 2: Note IP and port

- Lovense Remote: typically **20011** (HTTP) or **30011** (HTTPS)
- Lovense Connect: typically **34567**

### Step 3: Create the client

```python
from lovensepy import LANClient

client = LANClient("MyApp", "192.168.1.100", port=20011)
```

### Step 4: List connected toys

```python
response = client.get_toys()
toys = {toy.id: toy.model_dump() for toy in response.data.toys} if response.data else {}
# toys is {toy_id: toy_info}
```

### Step 5: One toy at a time, or one motor at a time

Pass **`toy_id`** (string from `get_toys`, or a list of ids) into `function_request`, `play`, `preset_request`, `pattern_request`, and `stop`. Omit it to hit **every** toy the app reports.

Dual-motor models (e.g. Edge) expose **`Vibrate1`** and **`Vibrate2`** as separate channels. Use **`Actions.VIBRATE1`** / **`Actions.VIBRATE2`** in the action dict. You can check what a row supports with **`features_for_toy`** (same dict shape as `toy.model_dump()`).

If you paste only the snippet below (e.g. in a REPL), run: `from lovensepy import Actions, Presets, features_for_toy` — or extend the Step 3–4 imports to include them.

```python
import time
from lovensepy import Actions, Presets, features_for_toy

# Each connected toy, same command, one after another
for tid, row in toys.items():
    client.function_request({Actions.VIBRATE: 8}, time=2, toy_id=tid)
    time.sleep(0.3)

# One toy, two motors separately (only if that toy lists both features)
edge_id = next(iter(toys))  # pick the right id in real code
if "Vibrate1" in features_for_toy(toys[edge_id]) and "Vibrate2" in features_for_toy(toys[edge_id]):
    client.function_request({Actions.VIBRATE1: 12}, time=2, toy_id=edge_id)
    time.sleep(0.2)
    client.function_request({Actions.VIBRATE2: 6}, time=2, toy_id=edge_id)

# Preset / pattern on a single toy
client.preset_request(Presets.PULSE, time=4, toy_id=edge_id)
client.pattern_request([5, 10, 15], time=3, toy_id=edge_id, actions=[Actions.VIBRATE1])
```

Patterns default to the generic **Vibrate** channel; pass **`actions=[Actions.VIBRATE1]`** (or a list of channels) to drive a specific motor where the API allows.

### Step 6: Function with auto-stop

```python
import time
from lovensepy import Actions

# Vibrate at level 10 for 5 seconds; toy is auto-stopped on context exit.
with client.play({Actions.VIBRATE: 10}, time=5):
    time.sleep(5)
```

### Step 7: Presets and patterns (optional)

```python
from lovensepy import Presets

client.preset_request(Presets.PULSE, time=5)
time.sleep(5)

# Custom pattern: list of strength levels (0-20)
client.pattern_request([5, 10, 15, 20], time=4)
time.sleep(4)

client.stop()
```

## Direct BLE

No LAN Game Mode required: your machine talks to the toy over Bluetooth. Install `pip install 'lovensepy[ble]'`, disconnect Lovense Remote from the toys, then follow **[Direct BLE](../direct-ble.md)** — same **`get_toys` → `play` / `function_request` → presets / patterns → `stop`** flow as above, using **`BleDirectHubSync`** in scripts or **`BleDirectHub`** with `await` in async code.

## Full LAN example

```python
import time
from lovensepy import LANClient, Actions, Presets, features_for_toy

client = LANClient("MyApp", "192.168.1.100", port=20011)

# Get toys
toys_response = client.get_toys()
toys = {toy.id: toy.model_dump() for toy in toys_response.data.toys} if toys_response.data else {}
print("Toys:", toys)

# Preset
client.preset_request(Presets.PULSE, time=5)
time.sleep(5)

# Function
client.function_request({Actions.ALL: 5}, time=3)
time.sleep(3)

# Pattern
client.pattern_request([5, 10, 15, 20], time=4)
time.sleep(4)

# Per-toy vibrate, then per-motor on first toy if it has two vibrators
for tid, row in toys.items():
    client.function_request({Actions.VIBRATE: 7}, time=2, toy_id=tid)
    time.sleep(0.25)
if toys:
    tid0, row0 = next(iter(toys.items()))
    feats = features_for_toy(row0)
    if "Vibrate1" in feats and "Vibrate2" in feats:
        client.function_request({Actions.VIBRATE1: 10}, time=2, toy_id=tid0)
        time.sleep(0.2)
        client.function_request({Actions.VIBRATE2: 8}, time=2, toy_id=tid0)

# Stop
client.stop()
```
