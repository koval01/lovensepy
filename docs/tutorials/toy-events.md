# Toy Events {#toy-events-tutorial}

Toy Events work with **Lovense Remote only** (port **20011**). Lovense Connect does not support Toy Events.

### Step 1: Remote and Game Mode

Use Lovense Remote with Game Mode enabled. Port is typically **20011**.

### Step 2: Client and callback

```python
import asyncio
from lovensepy import ToyEventsClient

def on_event(event_type, payload):
    print(event_type, payload)

client = ToyEventsClient(
    "192.168.1.100",
    port=20011,
    app_name="My App",
    on_event=on_event
)
```

### Step 3: Connect

```python
async def main():
    await client.connect()

asyncio.run(main())
```

### Step 4: Access prompt

The user grants access when Lovense Remote shows **Allow [My App] to access?**

### Step 5: Event stream

You receive events such as `toy-list`, `button-down`, `function-strength-changed`, and `shake`.
