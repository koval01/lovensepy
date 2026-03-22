# Server API and QR pairing

### Step 1: Developer token

Get your developer token from the [Lovense Developer Dashboard](https://developer.lovense.com).

### Step 2: Callback URL

Set up a callback URL (for example ngrok) and configure it in the Dashboard. Lovense will POST to this URL when a user scans the QR code.

### Step 3: Request a QR code

```python
from lovensepy import get_qr_code

qr_data = get_qr_code(developer_token="YOUR_TOKEN", uid="user_123")
qr_url = qr_data["qr"]   # Image URL for user to scan
code = qr_data["code"]   # 6-char code for Remote
print(f"Scan QR: {qr_url}")
```

### Step 4: User scans QR

The user scans the QR code in Lovense Remote.

### Step 5: Callback payload

Lovense POSTs to your callback URL with `uid` and `toys`. Your server stores the `uid`.

### Step 6: Create `ServerClient`

```python
from lovensepy import ServerClient, Actions

client = ServerClient(developer_token="YOUR_TOKEN", uid="user_123")
```

For **`async def`** code (bots, FastAPI, workers), use **`AsyncServerClient`** instead; it implements **`LovenseAsyncControlClient`** alongside **`AsyncLANClient`** and the BLE async clients, so you can type-hint one abstract client and swap transport. See [LovenseAsyncControlClient](../api-reference.md#lovenseasynccontrolclient).

### Step 7: Send commands

Same high-level methods as LAN (for example `function_request`):

```python
import time

client.function_request({Actions.VIBRATE: 10}, time=5)
time.sleep(5)
client.stop()
```
