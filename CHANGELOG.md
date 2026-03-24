# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.3] - 2026-03-24

### Changed

- **HTTP** uses **aiohttp** end-to-end: sync :class:`~lovensepy.transport.http.HttpTransport`,
  :class:`~lovensepy.transport.async_http.AsyncHttpTransport`, :func:`~lovensepy.socket_api.auth.get_token`,
  :func:`~lovensepy.socket_api.auth.get_socket_url`, and :func:`~lovensepy.standard.server.get_qr_code` share
  :func:`~lovensepy._aiohttp_helpers.read_response_json` so JSON bodies decode even when ``Content-Type`` is not
  ``application/json`` (common on Lovense LAN ``/command``).
- **WebSocket** transport (:class:`~lovensepy.transport.ws.WsTransport`) uses **aiohttp** instead of the **websockets**
  package; direct runtime dependencies are now **aiohttp** and **pydantic** only (**websockets** and **hyperframe**
  removed).

### Fixed

- WebSocket: keep a stable connection reference for the receive loop while :meth:`~lovensepy.transport.ws.WsTransport.close`
  clears transport state, matching prior ``websockets`` behaviour and avoiding recv teardown races.
- WebSocket: serialize all ``send_str`` calls with an :class:`asyncio.Lock` so concurrent Engine.IO frames (commands,
  ping, handshake replies) do not corrupt or drop writes on aiohttp.

## [1.1.2] - 2026-03-24

### Added

- Internal :mod:`lovensepy._command_utils` helpers shared by LAN, Server, and BLE clients:
  ``timeSec`` clamp, nested JSON parsing, pattern-rule letters, and function action clamping.
- Unit tests for :class:`~lovensepy.services.fastapi.scheduler.ControlScheduler` concurrency and for
  Darwin BLE connect-serializer lock reuse; expanded :file:`tests/run_all.py` phases (FastAPI service,
  BLE scan/branding/marketing-firmware tests).

### Changed

- :class:`~lovensepy.services.fastapi.scheduler.ControlScheduler` uses an async state lock for
  consistent task/meta/session bookkeeping under parallel HTTP handlers.
- FastAPI service: shared helpers for ``LovenseError`` → HTTP 502, shutdown/scheduler errors, and
  async task listing / session matching.
- :class:`~lovensepy.transport.async_http.AsyncHttpTransport` guards lazy ``aiohttp.ClientSession``
  creation with a thread lock to avoid duplicate clients under concurrent first requests.

### Fixed

- macOS: thread-safe initialization of the per-event-loop BLE connect lock (CoreBluetooth
  serialization) to avoid races when multiple coroutines connect at once.
- Documentation appendix lists ``examples/ble_direct_send_uart_once.py``.

### Deprecated / compatibility

- Legacy Pydantic request payload classes in :mod:`lovensepy._models` remain in the module but are no
  longer exported via ``__all__`` (runtime clients build dict payloads directly).

## [1.1.1] - 2026-03-23

### Added

- BLE **marketing / firmware** metadata (`toy_config_ble_marketing*.json`) and
  :func:`~lovensepy.ble_direct.branding_resolve.resolve_ble_branding_nickname` for consistent display
  names (ToyConfig map, firmware rules, UART fallback).
- **Russian** documentation mirror of the English site (`.ru.md` alongside `.en.md`); MkDocs nav and
  workflows updated.

### Changed

- :class:`~lovensepy.integrations.mqtt.ha_bridge.HAMqttBridge` and MQTT discovery: topic/layout and
  bridge behaviour refinements (see tests and `ha_bridge` / `discovery` / `topics`).
- FastAPI LAN service: configuration, models, and BLE/connect endpoints aligned with current BLE hub
  behaviour.
- Examples (`fastapi_lan_api`, `ha_mqtt_bridge`) and CI/docs workflows adjusted for the new doc layout.

### Fixed

- BLE direct client / hub edge cases covered by expanded unit tests (branding, marketing firmware,
  hub lifecycle).

## [1.1.0] - 2026-03-22

### Added

- :class:`~lovensepy.integrations.mqtt.ha_bridge.HAMqttBridge` **BLE transport** (`transport="ble"`):
  optional :class:`~lovensepy.ble_direct.hub.BleDirectHub` or automatic
  :meth:`~lovensepy.ble_direct.hub.BleDirectHub.discover_and_connect` on :meth:`~lovensepy.integrations.mqtt.ha_bridge.HAMqttBridge.start`;
  Toy Events remain **LAN-only**. Example script supports ``LOVENSE_TRANSPORT=ble`` and BLE scan env vars.
- :class:`~lovensepy.standard.async_base.LovenseAsyncControlClient` — abstract base for the shared
  async API on :class:`~lovensepy.standard.async_lan.AsyncLANClient`,
  :class:`~lovensepy.standard.async_server.AsyncServerClient`,
  :class:`~lovensepy.ble_direct.client.BleDirectClient`, and
  :class:`~lovensepy.ble_direct.hub.BleDirectHub` so apps can swap transport by changing which class
  they construct. Exported from :mod:`lovensepy` and :mod:`lovensepy.services.fastapi`.
- Documentation (README, installation, connection-methods, tutorials, direct-ble, API reference)
  explains how to type-hint and swap async transports via :class:`~lovensepy.standard.async_base.LovenseAsyncControlClient`.

### Changed

- :class:`~lovensepy.integrations.mqtt.ha_bridge.HAMqttBridge` MQTT Discovery uses **per-toy**
  retained availability (`{prefix}/{safe_toy_id}/device_availability`) together with the bridge topic,
  so Home Assistant reflects powered-off / disconnected toys (from GetToys ``status`` or BLE hub
  connection state). Restart the bridge once so updated discovery configs are retained on the broker.
- :class:`~lovensepy.integrations.mqtt.ha_bridge.HAMqttBridge` no longer drops toys from its cache when
  a GetToys snapshot omits them (empty list / glitch): entries stay for MQTT command routing, with
  ``device_availability`` set to ``offline`` and ``status`` forced to off.
- BLE Home Assistant naming now uses UART ``DeviceType`` enrich fields in ``nickName`` (for example
  ``Edge (model P, fw 240)``) so discovered entities are more descriptive than plain advertised names.
- :class:`~lovensepy.standard.async_server.AsyncServerClient` now matches the async control
  signatures used by LAN/BLE (e.g. ``wait_for_completion``, ``open_ended`` on preset, ``get_toys(...,
  query_battery=...)``, Position / PatternV2 helpers). :class:`~lovensepy.standard.async_lan.AsyncLANClient`
  preset requests accept ``open_ended`` (``openEnded`` in JSON when true).
- :class:`~lovensepy.services.fastapi.backend.LovenseControlBackend` documents the same keyword-only
  parameters as that async surface for ``get_toys`` and ``preset_request``.
- Removed optional ``uart_index`` / ``uart_keyword`` from ``POST /command/preset``; use
  ``LOVENSEPY_BLE_PRESET_UART`` (and reconnect) to switch ``Pat`` vs ``Preset``.
- FastAPI BLE: default UART prefix for presets is **Preset** (public UART docs + `/command/preset`
  naming). Set **`LOVENSEPY_BLE_PRESET_UART=Pat`** to align FastAPI with
  :class:`~lovensepy.ble_direct.client.BleDirectClient`, which still defaults to **Pat** when
  constructed without kwargs.
- CI runs the full fast unit test set (including BLE, UART, WebSocket, and
  Socket cleanup tests), Python 3.12 and 3.13 matrix, and coverage reporting.
- Async integration tests use `pytest-asyncio` (`asyncio_mode = auto`) consistently.
- PyPI publish workflow runs the test workflow before building and uploading.
- `BleDirectHubSync` / `run_ble_coroutine` use a bounded wait on the background
  BLE thread (`LOVENSEPY_BLE_SYNC_TIMEOUT`, default 300s; `none`/`0`/`inf` =
  unbounded).
- `WsTransport.close()` and `SocketAPIClient.disconnect()` close resources when
  no asyncio loop is running (no longer relying solely on GC).
- UART enrichment failures in `BleDirectHub.discover_and_connect` are logged at
  debug instead of failing silently with no signal.

### Fixed

- BLE ``preset_request`` sends ``Pat:{n};`` or ``Preset:{n};`` (configurable), not
  ``Pat:pulse``-style strings. Built-in names map via ``PRESET_BLE_PAT_INDEX``
  (default 1–4); digit-only ``name`` selects raw slots 0–20. FastAPI BLE connect
  honours ``LOVENSEPY_BLE_PRESET_UART`` (``Pat`` or ``Preset``). Optional
  ``LOVENSEPY_BLE_PRESET_EMULATE_PATTERN=1`` maps the four preset names to pattern
  stepping when UART preset lines are ignored. Non-numeric unknown names still
  raise ``LovenseBLEError``.
- `MANIFEST.in` no longer references a missing `version.py` file.

### Tooling

- `.pylintrc` disables a few design rules that duplicate Ruff / reflect protocol-shaped APIs,
  so `pylint lovensepy` matches CI expectations alongside Ruff.

## [1.0.6] - 2026-03-21

Initial changelog entry for this release line; see Git history for earlier changes.

[Unreleased]: https://github.com/koval01/lovensepy/compare/v1.1.3...HEAD
[1.1.3]: https://github.com/koval01/lovensepy/compare/v1.1.2...v1.1.3
[1.1.2]: https://github.com/koval01/lovensepy/compare/v1.1.1...v1.1.2
[1.1.1]: https://github.com/koval01/lovensepy/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/koval01/lovensepy/releases/tag/v1.1.0
[1.0.6]: https://github.com/koval01/lovensepy/releases/tag/v1.0.6
