# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-03-22

### Added

- :class:`~lovensepy.standard.async_base.LovenseAsyncControlClient` — abstract base for the shared
  async API on :class:`~lovensepy.standard.async_lan.AsyncLANClient`,
  :class:`~lovensepy.standard.async_server.AsyncServerClient`,
  :class:`~lovensepy.ble_direct.client.BleDirectClient`, and
  :class:`~lovensepy.ble_direct.hub.BleDirectHub` so apps can swap transport by changing which class
  they construct. Exported from :mod:`lovensepy` and :mod:`lovensepy.services.fastapi`.
- Documentation (README, installation, connection-methods, tutorials, direct-ble, API reference)
  explains how to type-hint and swap async transports via :class:`~lovensepy.standard.async_base.LovenseAsyncControlClient`.

### Changed

- :class:`~lovensepy.standard.async_server.AsyncServerClient` now matches the async control
  signatures used by LAN/BLE (e.g. ``wait_for_completion``, ``open_ended`` on preset, ``get_toys(...,
  query_battery=...)``, Position / PatternV2 helpers). :class:`~lovensepy.standard.async_lan.AsyncLANClient`
  preset requests accept ``open_ended`` (``openEnded`` in JSON when true).
- :class:`~lovensepy.services.fastapi.backend.LovenseControlBackend` documents the same keyword-only
  parameters as that async surface for ``get_toys`` and ``preset_request``.
- Removed optional ``uart_index`` / ``uart_keyword`` from ``POST /command/preset``; use
  ``LOVENSEPY_BLE_PRESET_UART`` (and reconnect) to switch ``Pat`` vs ``Preset``.
- FastAPI BLE: default UART prefix for presets is **Preset** (public UART docs + `/command/preset`
  naming); set **`LOVENSEPY_BLE_PRESET_UART=Pat`** to match Lovense Connect’s decompiled **`Pat`**.
  :class:`~lovensepy.ble_direct.client.BleDirectClient` still defaults to **Pat** when constructed
  without kwargs.
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

[Unreleased]: https://github.com/koval01/lovensepy/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/koval01/lovensepy/releases/tag/v1.1.0
[1.0.6]: https://github.com/koval01/lovensepy/releases/tag/v1.0.6
