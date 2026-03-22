# Socket API

The Socket API is **async only**. Use `asyncio.run()` to run your async entrypoint.

### Step 1: Auth token

```python
from lovensepy import get_token

auth_token = get_token(
    developer_token="YOUR_TOKEN",
    uid="user_123",
    uname="User"
)
```

### Step 2: Socket URL

The `platform` argument must match the **Website Name** from your Lovense Developer Dashboard exactly.

```python
from lovensepy import get_socket_url

socket_info = get_socket_url(auth_token, platform="Your App")
```

### Step 3: WebSocket URL

```python
from lovensepy import build_websocket_url

ws_url = build_websocket_url(socket_info, auth_token)
```

### Step 4: Connect

```python
import asyncio
from lovensepy import SocketAPIClient

async def main():
    client = SocketAPIClient(ws_url, on_event=lambda e, p: print(e, p))
    await client.connect()  # starts background loops and returns quickly
```

### Step 5: Request QR when Socket.IO is ready

```python
    client_ref = []

    def on_connected():
        client_ref[0].send_event("basicapi_get_qrcode_ts", {"ackId": "1"})

    client = SocketAPIClient(ws_url, on_socket_io_connected=on_connected, on_event=...)
    client_ref.append(client)
```

### Step 6: Device info after scan

The user scans QR. You receive `basicapi_update_device_info_tc` with the toy list in the payload.

### Step 7: Send commands

When `client.is_socket_io_connected` is true:

```python
    if client.is_socket_io_connected:
        client.send_command("Function", "Vibrate:10", time_sec=5, toy="toy_id")
```

### Step 8: Await critical stops

```python
    await client.send_command_await("Function", "Stop", time_sec=0, toy="toy_id")
```

### Step 9: Long-lived connections

```python
    # Keep connection alive even after transient disconnects.
    runner = client.start_background(auto_reconnect=True, retry_delay=5.0)
```

You can also use `await client.connect_with_retry(retry_delay=5.0)` directly.

### Local commands on the same LAN

Pass `use_local_commands=True` so that, after QR scan, commands go over HTTPS to the device instead of only over the WebSocket path to the cloud.
