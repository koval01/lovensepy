# Web control panel {#web-ui}

The HTTP service ships a browser control panel at **`/`**; the OpenAPI documentation moved to **`/docs`**. Start the service, open the page, and control toys without writing any code — connecting, reconnecting and status polling are handled for you.

```bash
pip install 'lovensepy[service,ble]'
lovensepy-service        # picks a free port, opens the panel in your browser
```

`lovensepy-service` defaults to `hybrid` mode, so BLE controls are there without any environment variables; `LOVENSE_PORT`, `LOVENSE_HOST` and `LOVENSE_OPEN_BROWSER=0` override its choices. To run it under your own server instead:

```bash
LOVENSE_SERVICE_MODE=hybrid uvicorn lovensepy.services.http_api.app:app --host 0.0.0.0 --port 8000
# then open http://127.0.0.1:8000/
```

The prebuilt downloads (macOS `.dmg` / Windows `.exe`) are the same launcher and open the panel on their own.

## What it does

| Area | Behaviour |
| --- | --- |
| **Devices** | One card per toy: a slider per motor (`POST /command/function`), the four Lovense presets, a pattern editor, device-side pulsing, and per-toy stop. |
| **Running** | Every scheduler row from `GET /tasks` with a live countdown and a stop button. |
| **Connect** | Bluetooth scan and one-tap **Connect everything** (`POST /ble/connect/auto`), Game Mode address form (`POST /config/lan-ip`), Lovense cloud pairing QR (`POST /config/socket`, `GET /socket/qr`). |
| **Settings** | Toggle transports, tune Bluetooth behaviour (auto-reconnect, background scanning, preset dialect, scan filter), theme, screen wake lock. |
| **Header** | Link status, **Stop all** (`POST /command/stop/all`) and a QR code with this machine's LAN URLs (`GET /system/network`) so a phone can join. |

Nothing is stored in the browser except UI preferences (theme, last duration, wake-lock choice). Credentials entered in **Connect** live in the service process memory only.

## Phone access

Open the panel on a phone on the same Wi-Fi: tap the phone icon in the header on the desktop and scan the QR code, or type the LAN address directly. There is no app to install and no pairing step — it is the same service, same live state, so a desktop and a phone can drive the same toy at once.

Because the page is served over plain HTTP on a LAN address, a few browser features are unavailable outside a secure context; the panel degrades quietly (clipboard copy falls back to a legacy path, the wake-lock toggle hides itself where the API is missing).

## How it stays in sync

- **`GET /state`** returns one snapshot: toys merged across transports, running sessions, Bluetooth discovery and supervisor status, Socket API pairing state, capabilities and configuration. One request renders the whole panel.
- **`WS /ws`** pushes that snapshot whenever something changes, with a heartbeat in between. The browser falls back to polling `GET /state` if the socket cannot be opened (strict proxy, old Safari over http) and keeps retrying it in the background.
- A phone that sleeps suspends its socket without closing it, so the panel watches for silence, forces a fresh connection when the tab becomes visible again, and re-reads state on `online` / `pageshow`.
- Slider moves are coalesced: at most one write per motor is in flight, only the newest value survives the wait, and the value at release is always sent last. Without this every drag would queue dozens of Bluetooth writes and the toy would lag behind the finger.
- Registered Bluetooth toys are kept connected by the service itself (per-toy exponential backoff, paused only when *you* disconnect), so a toy that walks out of range reappears on its own. See `GET /state` → `ble.supervisor`.

## Environment variables

Everything the panel touches can also be set up front. Nothing here is required — the panel can configure transports at runtime.

| Variable | Default | Meaning |
| --- | --- | --- |
| `LOVENSE_WEBUI` | `1` | `0` serves the API only: `/` returns 404, `/docs` still works. |
| `LOVENSE_CORS_ORIGINS` | *(empty)* | Extra allowed origins, comma separated. `*` is accepted but opens the API to any page you visit. |
| `LOVENSE_CORS_ALLOW_LOCALHOST` | `1` | Allow `localhost` / `127.0.0.1` / `[::1]` origins (Vite dev server). |
| `LOVENSE_STATE_CACHE_TTL` | `2` | Seconds the toy list is cached for `GET /state` and `/ws`. `GET /toys` is never cached. |
| `LOVENSE_EVENTS_INTERVAL` | `1` | Seconds between `/ws` pushes; identical snapshots are skipped. |
| `LOVENSE_BLE_AUTO_RECONNECT` | `1` | Keep registered Bluetooth toys connected in the background. |
| `LOVENSE_BLE_AUTO_RECONNECT_INTERVAL` | `5` | Seconds between supervisor rounds. |
| `LOVENSE_BLE_BATTERY_REFRESH` | `120` | Seconds between cached battery reads per toy. |
| `LOVENSE_TUNNEL` | `0` | `1` starts a Cloudflare quick tunnel (`cloudflared tunnel --url …`) with the service. The public `https://*.trycloudflare.com` URL appears in the phone QR dialog and under Settings → Phone from anywhere. |
| `LOVENSE_CLOUDFLARED_BIN` | *(PATH)* | Optional absolute path to the `cloudflared` binary. |
| `LOVENSE_TUNNEL_HOST` | `127.0.0.1` | Loopback host cloudflared dials (leave default). |
| `LOVENSE_GATE` | `1` | Outside the local network, visitors must enter a 6-digit code printed in the service console. Set `0` only if you deliberately want an open public panel. |

Install [`cloudflared`](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) first (`brew install cloudflared` on macOS). Same-Wi-Fi access stays open; a tunnel / public hostname shows an authorization page and prints a code in the console where you started the service.

See the [FastAPI service tutorial](tutorials/fastapi-lan-rest.md) for transport variables (`LOVENSE_SERVICE_MODE`, `LOVENSE_LAN_IP`, Socket credentials, BLE scan options).

## Building from a source checkout

Wheels and the packaged executables include the built panel. A plain git checkout does not: the service then serves a short placeholder page (the API keeps working). Build it once with Node 22+:

```bash
cd frontend
npm ci
npm run build     # → lovensepy/services/http_api/webui_dist/
```

For UI development, run the service on `:8000` and Vite next to it — API paths and `/ws` are proxied, so the dev server behaves like the bundled build:

```bash
cd frontend
npm run dev       # http://127.0.0.1:5173
# point it elsewhere with LOVENSE_SERVICE_URL=http://192.168.1.10:8000
```

The stack is React 19 + TypeScript + Vite, Tailwind CSS v4 and shadcn/ui components. `npm run build` typechecks first, so a type error fails the build.
