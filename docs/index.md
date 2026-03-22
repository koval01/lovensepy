# LovensePy documentation

Long-form guides, API tables, and reference material for [LovensePy](https://github.com/koval01/lovensepy) live here. The [repository README](https://github.com/koval01/lovensepy#readme) stays short for PyPI and quick orientation.

## Start here

- [Installation and setup](installation.md) — prerequisites, extras (`[mqtt]`, `[ble]`), first Game Mode script
- [Connection methods and architecture](connection-methods.md) — which client to use, traffic paths, diagram
- [Direct BLE](direct-ble.md) — `BleDirectHubSync` quick start (LAN-like), async hub, notes

## Tutorials

- [LAN Game Mode and direct BLE hub](tutorials/lan.md)
- [Server API + QR pairing](tutorials/server-qr.md)
- [Socket API](tutorials/socket.md)
- [Toy Events](tutorials/toy-events.md)
- [Home Assistant MQTT](tutorials/home-assistant-mqtt.md)
- [FastAPI LAN REST](tutorials/fastapi-lan-rest.md)

## Reference

- [API Reference](api-reference.md) — constructors, methods, pattern players, utilities
- [Appendix](appendix.md) — actions/presets, event types, Lovense flow diagrams, examples table, tests, external links
- [Changelog](changelog.md) — release notes (links to repository `CHANGELOG.md`)

## Build locally

```bash
pip install -e ".[docs]"
mkdocs serve
```

Open `http://127.0.0.1:8000` to preview.

The live site is built from this folder with [MkDocs](https://www.mkdocs.org/); configuration lives in [`mkdocs.yml`](https://github.com/koval01/lovensepy/blob/main/mkdocs.yml). GitHub Actions deploys the static output. If the site does not update after the first workflow run, open the repository **Settings**, then **Pages**, and set **Build and deployment** to **GitHub Actions**.
