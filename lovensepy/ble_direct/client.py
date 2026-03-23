"""
Direct BLE client for Lovense devices that expose a UART-style TX characteristic.

Requires ``pip install 'lovensepy[ble]'`` (``bleak``). Not all models/firmware
revisions are known to match :data:`DEFAULT_UART_TX_UUIDS`.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import json
import logging
import os
import re
import sys
import threading
import uuid as uuidlib
import weakref
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from lovensepy._command_utils import (
    actions_to_rule_letters,
    clamp_time_sec_in_payload,
)
from lovensepy._constants import ERROR_CODES, PRESET_BLE_PAT_INDEX, Actions, Presets
from lovensepy._models import CommandResponse, GetToyNameResponse, GetToysResponse, PatternV2Action
from lovensepy.exceptions import LovenseBLEError
from lovensepy.standard.async_base import LovenseAsyncControlClient

from .standard_compat import (
    ble_actions_to_uart_strings,
    ble_clamp_actions,
    parse_pattern_rule_and_strength,
    pattern_rule_first_letter_to_feature,
)
from .uart_catalog import (
    ble_stop_command_strings_for_toy_type,
    ble_uart_features_for_toy_type,
    default_full_stop_payloads,
)
from .uart_replies import DeviceTypeFields, parse_battery_percent, parse_device_type_fields

# When ``time`` is 0 and ``open_ended`` is false, hold the preset this long before a stop burst.
_DEFAULT_BLE_PRESET_HOLD_SEC = 12.0

# Typical firmware accepts Pat/Preset slot roughly 0..20; keep raw numeric presets in range.
_BLE_PAT_INDEX_MAX = 20

# When ``ble_preset_emulate_with_pattern`` is true, the four Remote names use stepped ``Vibrate*``
# (same transport path as :meth:`BleDirectClient.pattern_request`) — for firmware that ignores UART Pat/Preset.
_BLE_APP_PRESET_AS_PATTERN: dict[str, tuple[list[int], int]] = {
    "pulse": ([3, 5, 7, 5], 100),
    "wave": ([2, 6, 10, 14, 10, 6], 100),
    "fireworks": ([5, 10, 5, 15, 8, 18, 10, 20, 12, 16, 8, 12], 100),
    "earthquake": ([18, 20, 16, 20, 18, 19, 20, 17], 100),
}

_logger = logging.getLogger(__name__)


def _transient_gatt_write_exception_types() -> tuple[type[BaseException], ...]:
    """Exception types that often indicate a flaky BLE link (worth retrying a GATT write)."""
    types: list[type[BaseException]] = [TimeoutError, OSError]
    try:
        from bleak import BleakError

        types.append(BleakError)
    except ImportError:
        pass
    return tuple(types)


def _is_transient_gatt_write_error(exc: BaseException) -> bool:
    if isinstance(exc, asyncio.CancelledError):
        return False
    transient = _transient_gatt_write_exception_types()
    if isinstance(exc, transient):
        return True
    cause = getattr(exc, "__cause__", None)
    if cause is not None and cause is not exc:
        return _is_transient_gatt_write_error(cause)
    return False


def normalize_ble_preset_uart_keyword(raw: str) -> str:
    """Return ``Pat`` or ``Preset`` for UART preset lines (case-insensitive input)."""
    s = (raw or "Pat").strip().lower()
    if s == "pat":
        return "Pat"
    if s == "preset":
        return "Preset"
    raise LovenseBLEError(
        f"ble_preset_uart_keyword must be 'Pat' or 'Preset' (got {raw!r})",
        endpoint="ble_direct",
    )


def ble_preset_connect_kwargs(
    *,
    uart_keyword_raw: str | None,
    emulate_pattern: bool,
) -> dict[str, Any]:
    """Build :class:`BleDirectClient` kwargs for preset UART behaviour.

    Same rules as FastAPI :meth:`ServiceConfig.ble_connect_client_kwargs`.
    """
    raw = (uart_keyword_raw or "Preset").strip()
    if not raw:
        raw = "Preset"
    out: dict[str, Any] = {
        "ble_preset_uart_keyword": normalize_ble_preset_uart_keyword(raw),
    }
    if emulate_pattern:
        out["ble_preset_emulate_with_pattern"] = True
    return out


def ble_direct_client_preset_kwargs_from_env() -> dict[str, Any]:
    """Preset-related :class:`BleDirectClient` kwargs from standard env vars.

    - ``LOVENSEPY_BLE_PRESET_UART`` — ``Pat`` or ``Preset`` (default ``Preset``, same as FastAPI).
    - ``LOVENSEPY_BLE_PRESET_EMULATE_PATTERN`` — truthy to emulate presets via pattern stepping.
    """
    ble_uart_raw = (os.environ.get("LOVENSEPY_BLE_PRESET_UART") or "Preset").strip()
    emulate_raw = os.environ.get("LOVENSEPY_BLE_PRESET_EMULATE_PATTERN", "").strip().lower()
    emulate = emulate_raw in ("1", "true", "yes", "on")
    return ble_preset_connect_kwargs(
        uart_keyword_raw=ble_uart_raw or None,
        emulate_pattern=emulate,
    )


def _resolve_ble_pat_index(name: str | Presets) -> int:
    raw = str(name).strip().lower()
    if raw in PRESET_BLE_PAT_INDEX:
        return PRESET_BLE_PAT_INDEX[raw]
    if raw.isdigit():
        n = int(raw)
        if n < 0 or n > _BLE_PAT_INDEX_MAX:
            raise LovenseBLEError(
                f"BLE Pat index out of range (0–{_BLE_PAT_INDEX_MAX}): {n}",
                endpoint="ble_direct",
                payload={"preset": raw},
            )
        return n
    raise LovenseBLEError(
        "Unknown BLE preset; use pulse, wave, fireworks, earthquake, "
        f"or a numeric Pat index string 0–{_BLE_PAT_INDEX_MAX} (got {name!r}).",
        endpoint="ble_direct",
        payload={"preset": raw},
    )


def _schedule_deferred_ble_coro(
    coro: Any,
    *,
    label: str,
    data_extra: dict[str, Any] | None = None,
) -> CommandResponse:
    """Run ``coro`` in the background; return immediately (HTTP-style, LAN-like)."""

    async def _run() -> None:
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception:
            _logger.exception("Deferred BLE command failed (%s)", label)

    asyncio.create_task(_run(), name=f"lovensepy:ble_deferred:{label}")
    data: dict[str, Any] = {"deferred": True}
    if data_extra:
        data.update(data_extra)
    return CommandResponse(
        code=200,
        type="OK",
        result=True,
        data=data,
    )


# Order: commonly reported UUIDs first, then alternate generations / stacks.
# Lovense uses several 128-bit “product family” prefixes (5030 Edge-class, 455a Gush, 5330 Lush,
# 5730 Domi, …) with the same trailing tail; TX is always *0002 in the first segment.
DEFAULT_UART_TX_UUIDS: tuple[str, ...] = (
    "50300002-0023-4bd4-bbd5-a6920e4c5653",
    "50300002-0024-4bd4-bbd5-a6920e4c5653",
    "455a0002-0023-4bd4-bbd5-a6920e4c5653",
    "455a0002-0024-4bd4-bbd5-a6920e4c5653",
    "53300002-0023-4bd4-bbd5-a6920e4c5653",
    "53300002-0024-4bd4-bbd5-a6920e4c5653",
    "57300002-0023-4bd4-bbd5-a6920e4c5653",
    "57300002-0024-4bd4-bbd5-a6920e4c5653",
    "6e400002-b5a3-f393-e0a9-e50e24dcca9e",
    "0000fff2-0000-1000-8000-00805f9b34fb",
)

# RX (notify): sibling of TX (*0003). Nordic NUS; legacy gen-1 uses fff1.
DEFAULT_UART_RX_UUIDS: tuple[str, ...] = (
    "50300003-0023-4bd4-bbd5-a6920e4c5653",
    "50300003-0024-4bd4-bbd5-a6920e4c5653",
    "455a0003-0023-4bd4-bbd5-a6920e4c5653",
    "455a0003-0024-4bd4-bbd5-a6920e4c5653",
    "53300003-0023-4bd4-bbd5-a6920e4c5653",
    "53300003-0024-4bd4-bbd5-a6920e4c5653",
    "57300003-0023-4bd4-bbd5-a6920e4c5653",
    "57300003-0024-4bd4-bbd5-a6920e4c5653",
    "6e400003-b5a3-f393-e0a9-e50e24dcca9e",
    "0000fff1-0000-1000-8000-00805f9b34fb",
)

# Any Lovense-family UART TX: first segment ends with 0002; middle segment varies (0023, 0024, …).
_FLEX_LOVENSE_FAMILY_TX = re.compile(
    r"^[0-9a-f]{4}0002-[0-9a-f]{4}-4bd4-bbd5-a6920e4c5653$",
    re.IGNORECASE,
)

_FLEX_LOVENSE_FAMILY_RX = re.compile(
    r"^[0-9a-f]{4}0003-[0-9a-f]{4}-4bd4-bbd5-a6920e4c5653$",
    re.IGNORECASE,
)

_WRITE_PROPS = frozenset({"write", "write-without-response"})
_NOTIFY_PROPS = frozenset({"notify", "indicate"})

# CoreBluetooth is unreliable when two peripherals connect/discover GATT at once.
# One lock per running event loop (pytest-asyncio may use a fresh loop per test).
_loop_locks: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = (
    weakref.WeakKeyDictionary()
)
_loop_locks_guard = threading.Lock()


def _ble_connect_serializer() -> asyncio.Lock | None:
    if sys.platform != "darwin":
        return None
    loop = asyncio.get_running_loop()
    with _loop_locks_guard:
        lock = _loop_locks.get(loop)
        if lock is None:
            lock = asyncio.Lock()
            _loop_locks[loop] = lock
        return lock


def _norm_uuid(u: str | uuidlib.UUID | Any) -> str:
    if isinstance(u, uuidlib.UUID):
        return str(u).lower()
    return str(u).lower()


def _normalize_ble_uuid(u: Any) -> str:
    """Match Bleak’s UUID canonical form (16/32-bit expansion, lowercase)."""
    from bleak.uuids import normalize_uuid_str

    return normalize_uuid_str(str(u))


def _uuid_match(a: Any, b: Any) -> bool:
    try:
        return _normalize_ble_uuid(a) == _normalize_ble_uuid(b)
    except ValueError:
        return _norm_uuid(a) == _norm_uuid(b)


def _iter_characteristics(services: Any) -> Iterator[Any]:
    """Bleak exposes a flat ``characteristics`` dict; fall back to per-service lists if needed."""
    seen: set[int] = set()

    def emit(ch: Any) -> Iterator[Any]:
        h = getattr(ch, "handle", None)
        key = int(h) if h is not None else id(ch)
        if key in seen:
            return
        seen.add(key)
        yield ch

    raw = getattr(services, "characteristics", None)
    if isinstance(raw, dict):
        for ch in raw.values():
            yield from emit(ch)
    try:
        for service in services:
            for ch in service.characteristics:
                yield from emit(ch)
    except TypeError:
        pass


def _char_is_writable(properties: list[str] | Any) -> bool:
    if not properties:
        return False
    props = {str(p).lower() for p in properties}
    return bool(props & _WRITE_PROPS)


def _is_lovense_family_uart_tx(char_uuid: Any) -> bool:
    try:
        s = _normalize_ble_uuid(char_uuid)
    except ValueError:
        return False
    return _FLEX_LOVENSE_FAMILY_TX.match(s) is not None


def _is_lovense_family_uart_rx(char_uuid: Any) -> bool:
    try:
        s = _normalize_ble_uuid(char_uuid)
    except ValueError:
        return False
    return _FLEX_LOVENSE_FAMILY_RX.match(s) is not None


def _char_is_notifiable(properties: list[str] | Any) -> bool:
    if not properties:
        return False
    props = {str(p).lower() for p in properties}
    return bool(props & _NOTIFY_PROPS)


def _tx_uuid_to_rx_guess(tx_uuid: str) -> str | None:
    """Infer RX UUID from resolved TX (…0002… → …0003… in the same family)."""
    try:
        s = _normalize_ble_uuid(tx_uuid)
    except ValueError:
        return None
    if "0002-" not in s:
        return None
    return s.replace("0002-", "0003-", 1)


def discover_uart_rx_notify(
    services: Any,
    *,
    uart_rx_uuid: str | None,
    tx_uuid: str | None,
    candidates: tuple[str, ...] = DEFAULT_UART_RX_UUIDS,
) -> str:
    """Pick an RX characteristic that supports notify/indicate."""

    chars = list(_iter_characteristics(services))

    if uart_rx_uuid:
        found: Any | None = None
        for char in chars:
            if _uuid_match(char.uuid, uart_rx_uuid):
                found = char
                break
        if found is None:
            raise LovenseBLEError(
                f"No GATT characteristic for uart_rx_uuid={uart_rx_uuid!r}. "
                "Check the BLE address or disconnect other apps (e.g. Lovense Remote)."
            )
        return _normalize_ble_uuid(found.uuid)

    if tx_uuid:
        guess = _tx_uuid_to_rx_guess(tx_uuid)
        if guess:
            for char in chars:
                if _uuid_match(char.uuid, guess) and _char_is_notifiable(char.properties):
                    return _normalize_ble_uuid(char.uuid)
            for char in chars:
                if _uuid_match(char.uuid, guess):
                    return _normalize_ble_uuid(char.uuid)

    for cand in candidates:
        for char in chars:
            if _uuid_match(char.uuid, cand) and _char_is_notifiable(char.properties):
                return _normalize_ble_uuid(char.uuid)

    for cand in candidates:
        for char in chars:
            if _uuid_match(char.uuid, cand):
                return _normalize_ble_uuid(char.uuid)

    flex = [c for c in chars if _is_lovense_family_uart_rx(c.uuid)]
    for char in flex:
        if _char_is_notifiable(char.properties):
            return _normalize_ble_uuid(char.uuid)
    for char in flex:
        return _normalize_ble_uuid(char.uuid)

    raise LovenseBLEError(
        "No UART RX characteristic with notify/indicate found. "
        "Pass uart_rx_uuid=... explicitly if your firmware uses another UUID."
    )


def discover_writable_uart_tx(
    services: Any,
    *,
    uart_tx_uuid: str | None,
    candidates: tuple[str, ...] = DEFAULT_UART_TX_UUIDS,
) -> str:
    """Pick a TX UUID after connect, or raise :exc:`LovenseBLEError`."""

    chars = list(_iter_characteristics(services))

    if uart_tx_uuid:
        found: Any | None = None
        for char in chars:
            if _uuid_match(char.uuid, uart_tx_uuid):
                found = char
                break
        if found is None:
            msg = (
                f"No GATT characteristic for uart_tx_uuid={uart_tx_uuid!r}. "
                "Check the BLE address or disconnect other apps (e.g. Lovense Remote)."
            )
            raise LovenseBLEError(msg)
        return _normalize_ble_uuid(found.uuid)

    for cand in candidates:
        for char in chars:
            if _uuid_match(char.uuid, cand) and _char_is_writable(char.properties):
                return _normalize_ble_uuid(char.uuid)

    for cand in candidates:
        for char in chars:
            if _uuid_match(char.uuid, cand):
                return _normalize_ble_uuid(char.uuid)

    flex = [c for c in chars if _is_lovense_family_uart_tx(c.uuid)]
    for char in flex:
        if _char_is_writable(char.properties):
            return _normalize_ble_uuid(char.uuid)
    for char in flex:
        return _normalize_ble_uuid(char.uuid)

    raise LovenseBLEError(
        "No known Lovense UART TX characteristic found on this device. "
        "Pass uart_tx_uuid=... explicitly if your firmware uses another UUID."
    )


def _bleak_client_cls() -> Any:
    try:
        from bleak import BleakClient
    except ImportError as exc:
        raise LovenseBLEError(
            "Direct BLE requires the 'bleak' package. Install: pip install 'lovensepy[ble]'"
        ) from exc
    return BleakClient


def ensure_bleak_installed() -> None:
    """Fail fast if ``bleak`` is missing (optional dependency).

    Uses :func:`importlib.util.find_spec` so tests can still patch
    :func:`_bleak_client_cls` without an extra import side effect at construction.
    """
    if importlib.util.find_spec("bleak") is None:
        raise LovenseBLEError(
            "Direct BLE requires the 'bleak' package. Install: pip install 'lovensepy[ble]'"
        )


def build_vibrate_command(level: int) -> str:
    """Return the UART text for vibration level ``0..20`` (Lovense-style framing)."""
    n = max(0, min(20, int(level)))
    return f"Vibrate:{n};"


# Pause between consecutive UART writes produced from one clamped Function update (e.g. two
# GATT writes for ``Vibrate1`` + ``Vibrate2``). Some stacks/firmware combinations drop the
# second back-to-back write; a short gap matches typical app timing. Set to ``0`` to disable.
DEFAULT_UART_INTER_COMMAND_DELAY_S = 0.015

# After ``silence_all_motors`` at the end of :meth:`BleDirectClient.function_request` with
# ``time > 0``, wait briefly so the next command is not lost on busy stacks/firmware.
DEFAULT_POST_TIMED_FUNCTION_SILENCE_COOLDOWN_S = 0.22

# Dual-motor (Vibrate1+Vibrate2): before a **single** non-zero channel write, some firmware
# ignores switching to the peer motor until that peer was explicitly zero in its **own**
# preceding GATT write (distinct from bundling both lines in one logical update).
DEFAULT_DUAL_SINGLE_CHANNEL_PRIME_DELAY_S = 0.045


@dataclass(frozen=True)
class LovenseBleAdvertisement:
    """One discovered BLE peripheral (address, name, RSSI if the stack exposes it)."""

    address: str
    name: str | None
    rssi: int | None = None


async def scan_lovense_ble_advertisements(
    timeout: float = 8.0,
    *,
    name_prefix: str | None = "LVS-",
) -> list[LovenseBleAdvertisement]:
    """Discover BLE peripherals with optional RSSI (``getattr(device, \"rssi\", None)``).

    When ``name_prefix`` is not ``None``, only devices whose advertised name
    starts with that prefix (case-insensitive) are returned — typical Lovense
    broadcast names look like ``LVS-…``. Pass ``name_prefix=None`` to list all
    discovered devices.
    """
    try:
        from bleak import BleakScanner
    except ImportError as exc:
        raise LovenseBLEError(
            "Direct BLE requires the 'bleak' package. Install: pip install 'lovensepy[ble]'"
        ) from exc

    devices = await BleakScanner.discover(timeout=timeout)
    rows: list[LovenseBleAdvertisement] = []
    for d in devices:
        name = d.name
        if name_prefix is not None:
            n = (name or "").strip()
            if not n.upper().startswith(name_prefix.upper()):
                continue
        rssi = getattr(d, "rssi", None)
        if type(rssi) in (int, float):
            rssi_i = int(rssi)
        else:
            rssi_i = None
        rows.append(LovenseBleAdvertisement(address=d.address, name=d.name, rssi=rssi_i))
    rows.sort(key=lambda r: ((r.name or "").lower(), r.address.lower()))
    return rows


async def scan_lovense_ble_devices(
    timeout: float = 8.0,
    *,
    name_prefix: str | None = "LVS-",
) -> list[tuple[str, str | None]]:
    """Discover BLE peripherals as ``(address, name)`` pairs.

    Same filtering as :func:`scan_lovense_ble_advertisements` without RSSI in the
    return type (backward compatible).
    """
    adv = await scan_lovense_ble_advertisements(timeout=timeout, name_prefix=name_prefix)
    return [(a.address, a.name) for a in adv]


async def _safe_disconnect(client: Any) -> None:
    with contextlib.suppress(Exception):
        await client.disconnect()


def _slug_from_adv_name(name: str | None) -> str | None:
    """``LVS-Edge`` / ``LVS-Edge 2`` → ``edge`` (used with :func:`ble_uart_features_for_toy_type`)."""
    if not name:
        return None
    low = name.strip().lower()
    if low.startswith("lvs-"):
        slug = low[4:].split("-")[0].split(":")[0]
        # Strip trailing model revision (``Edge 2`` → ``edge``); ``re.sub`` leaves a
        # trailing space if the name was ``edge 2`` — normalize with ``strip()``.
        slug = re.sub(r"\d+$", "", slug).strip()
        return slug or None
    tail = re.sub(r"\d+$", "", low.split(":", 1)[-1].strip()).strip()
    return tail or None


class BleDirectClient(LovenseAsyncControlClient):
    """One BLE peripheral per instance; use multiple instances for multiple toys.

    The **library API mirrors** :class:`~lovensepy.standard.async_lan.AsyncLANClient`
    (same enums, ``function_request`` / ``preset_request`` / ``send_command``, …) so
    code can swap transport; **under the hood** this client uses GATT UART writes
    instead of HTTP to Lovense Remote — **no LAN Game Mode** and **no in-app
    bridge**, only your machine’s Bluetooth radio. Disconnect Lovense Remote /
    other centrals first if the link is exclusive.

    On **unexpected BLE disconnect**, if ``silence_on_link_loss`` is true
    (default), the client schedules a **short reconnect** and sends a **full**
    UART stop burst (see :data:`lovensepy.ble_direct.uart_catalog.DEFAULT_FULL_STOP_COMMANDS`).
    That is best-effort: if the toy is out of range, reconnect fails and motor
    behaviour depends on firmware.

    **GATT write resilience:** optional exponential backoff retries on transient
    transport errors (``BleakError``, timeouts, some ``OSError``) from
    ``write_gatt_char``. This is **not** the same as Socket API
    ``start_background(auto_reconnect=True)`` (session-level); it only re-sends
    individual writes. Use ``gatt_write_max_attempts > 1`` on noisy links.
    """

    def __init__(
        self,
        address: str,
        *,
        uart_tx_uuid: str | None = None,
        uart_rx_uuid: str | None = None,
        write_with_response: bool = False,
        silence_on_link_loss: bool = True,
        link_loss_silence_timeout: float = 12.0,
        toy_type: str | None = None,
        advertised_name: str | None = None,
        uart_inter_command_delay_s: float = DEFAULT_UART_INTER_COMMAND_DELAY_S,
        post_timed_function_silence_cooldown_s: float = DEFAULT_POST_TIMED_FUNCTION_SILENCE_COOLDOWN_S,
        dual_single_channel_prime_peer_zero: bool = True,
        dual_single_channel_prime_delay_s: float = DEFAULT_DUAL_SINGLE_CHANNEL_PRIME_DELAY_S,
        ble_preset_uart_keyword: str = "Pat",
        ble_preset_emulate_with_pattern: bool = False,
        gatt_write_max_attempts: int = 1,
        gatt_write_retry_base_delay: float = 0.2,
        gatt_write_retry_max_delay: float = 2.0,
    ) -> None:
        ensure_bleak_installed()
        self.address = address
        self._uart_tx_uuid_hint = uart_tx_uuid
        self._uart_rx_uuid_hint = uart_rx_uuid
        self._write_with_response = write_with_response
        self._uart_inter_command_delay_s = float(uart_inter_command_delay_s)
        self._post_timed_function_silence_cooldown_s = float(post_timed_function_silence_cooldown_s)
        self._dual_single_channel_prime_peer_zero = bool(dual_single_channel_prime_peer_zero)
        self._dual_single_channel_prime_delay_s = float(dual_single_channel_prime_delay_s)
        self._silence_on_link_loss = silence_on_link_loss
        self._link_loss_silence_timeout = float(link_loss_silence_timeout)
        self._toy_type_hint = toy_type
        self._client: Any = None
        self._resolved_tx_uuid: str | None = None
        self._resolved_rx_uuid: str | None = None
        # Dedupe for set_vibration: sorted (channel, level) tuples (single or multi motor).
        self._last_vibrate_sig: tuple[tuple[str, int], ...] | None = None
        # Edge/Diamo: last UART levels after each dual-motor :meth:`_send_uart_for_clamped`.
        self._dual_vibrate_levels: tuple[int, int] = (0, 0)
        # Which motor(s) last ran non-zero over UART (survives silence_all_motors). Used to
        # prime the peer with :0; only when switching channels — always priming caused laggy
        # / “one step behind” behaviour on some firmware after every timed stop.
        self._dual_last_nonzero_motor: str | None = None
        # Slug from ``advertised_name`` / fetch_ble_snapshot(adv_name=…) — motor routing.
        self._last_adv_slug: str | None = (
            _slug_from_adv_name(advertised_name) if advertised_name else None
        )
        self._intentional_disconnect = False
        self._link_loss_task: asyncio.Task[None] | None = None
        self._query_lock = asyncio.Lock()
        #: Background hold / pattern tail; superseded by new playback or :meth:`stop`.
        self._deferred_playback_task: asyncio.Task[None] | None = None
        # Standard API parity (:class:`~lovensepy.standard.async_lan.AsyncLANClient`)
        self.actions = Actions
        self.presets = Presets
        self.error_codes = ERROR_CODES
        self.last_command: dict[str, Any] | None = None
        self._ble_preset_uart_keyword = normalize_ble_preset_uart_keyword(ble_preset_uart_keyword)
        self._ble_preset_emulate_with_pattern = bool(ble_preset_emulate_with_pattern)
        self._gatt_write_max_attempts = max(1, int(gatt_write_max_attempts))
        self._gatt_write_retry_base_delay = float(gatt_write_retry_base_delay)
        self._gatt_write_retry_max_delay = float(
            max(gatt_write_retry_base_delay, gatt_write_retry_max_delay)
        )

    async def _write_gatt_char_resilient(self, payload: bytes) -> None:
        """Write to TX with optional exponential backoff on transient BLE errors."""
        if not self.is_connected or not self._resolved_tx_uuid or not self._client:
            raise LovenseBLEError("Not connected")
        attempts = self._gatt_write_max_attempts
        delay = self._gatt_write_retry_base_delay
        cap = self._gatt_write_retry_max_delay
        last: BaseException | None = None
        for attempt in range(attempts):
            try:
                await self._client.write_gatt_char(
                    self._resolved_tx_uuid,
                    payload,
                    response=self._write_with_response,
                )
                return
            except BaseException as e:
                last = e
                if isinstance(e, asyncio.CancelledError):
                    raise
                if attempt + 1 >= attempts or not _is_transient_gatt_write_error(e):
                    break
                _logger.debug(
                    "GATT write retry %s/%s after %s: %s",
                    attempt + 1,
                    attempts,
                    type(e).__name__,
                    e,
                )
                await asyncio.sleep(min(delay, cap))
                delay = min(delay * 2.0, cap)
        exc = last
        if exc is None:
            raise LovenseBLEError("BLE GATT write failed")
        if isinstance(exc, LovenseBLEError):
            raise exc
        raise LovenseBLEError(f"BLE GATT write failed: {exc}") from exc

    @property
    def is_connected(self) -> bool:
        return bool(self._client and getattr(self._client, "is_connected", False))

    @property
    def uart_tx_uuid(self) -> str | None:
        """TX characteristic UUID (Bleak-normalized) after :meth:`connect`, else ``None``."""
        return self._resolved_tx_uuid

    @property
    def uart_rx_uuid(self) -> str | None:
        """RX notify characteristic after :meth:`connect` if discovered, else ``None``."""
        return self._resolved_rx_uuid

    def _on_bleak_disconnected(self, _bleak_client: Any) -> None:
        """Bleak: unsolicited disconnect — clear session; optionally reconnect to send stop."""
        if self._intentional_disconnect:
            return
        known_tx = self._resolved_tx_uuid
        self._client = None
        self._resolved_tx_uuid = None
        self._resolved_rx_uuid = None
        self._last_vibrate_sig = None
        self._dual_vibrate_levels = (0, 0)
        self._dual_last_nonzero_motor = None
        if not self._silence_on_link_loss:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        prev = self._link_loss_task
        if prev is not None and not prev.done():
            prev.cancel()
        self._link_loss_task = loop.create_task(self._silence_after_link_loss(known_tx))

    async def _silence_after_link_loss(self, known_tx: str | None) -> None:
        """Reconnect once and write stop commands (ignored if model has no Vibrate1/2)."""
        BleakClient = _bleak_client_cls()
        temp: Any = None
        try:

            async def _inner() -> None:
                nonlocal temp
                temp = BleakClient(self.address)
                await asyncio.wait_for(
                    temp.connect(),
                    timeout=self._link_loss_silence_timeout,
                )
                if not getattr(temp, "is_connected", False):
                    return
                tx = discover_writable_uart_tx(
                    temp.services,
                    uart_tx_uuid=self._uart_tx_uuid_hint or known_tx,
                    candidates=DEFAULT_UART_TX_UUIDS,
                )
                for payload in default_full_stop_payloads():
                    with contextlib.suppress(Exception):
                        await temp.write_gatt_char(
                            tx,
                            payload,
                            response=self._write_with_response,
                        )

            lock = _ble_connect_serializer()
            if lock is not None:
                async with lock:
                    await _inner()
            else:
                await _inner()
        except asyncio.CancelledError:
            raise
        except Exception:  # nosec B110
            pass
        finally:
            if temp is not None:
                await _safe_disconnect(temp)

    async def connect(self) -> None:
        BleakClient = _bleak_client_cls()
        self._last_vibrate_sig = None
        if self._link_loss_task is not None and not self._link_loss_task.done():
            self._link_loss_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._link_loss_task
        self._link_loss_task = None

        async def _establish() -> None:
            client = BleakClient(
                self.address,
                disconnected_callback=self._on_bleak_disconnected,
            )
            await client.connect()
            if not getattr(client, "is_connected", False):
                await _safe_disconnect(client)
                raise LovenseBLEError(f"BLE connection failed for {self.address!r}")

            self._resolved_tx_uuid = discover_writable_uart_tx(
                client.services,
                uart_tx_uuid=self._uart_tx_uuid_hint,
                candidates=DEFAULT_UART_TX_UUIDS,
            )
            try:
                self._resolved_rx_uuid = discover_uart_rx_notify(
                    client.services,
                    uart_rx_uuid=self._uart_rx_uuid_hint,
                    tx_uuid=self._resolved_tx_uuid,
                    candidates=DEFAULT_UART_RX_UUIDS,
                )
            except LovenseBLEError:
                self._resolved_rx_uuid = None
            self._client = client

        lock = _ble_connect_serializer()
        if lock is not None:
            async with lock:
                await _establish()
        else:
            await _establish()

    async def cancel_deferred_playback(self) -> None:
        """Cancel a prior :meth:`preset_request` / pattern / timed function tail (if any)."""
        t = self._deferred_playback_task
        if t is None or t.done():
            self._deferred_playback_task = None
            return
        t.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await t
        self._deferred_playback_task = None

    async def begin_deferred_playback(
        self,
        coro_factory: Callable[[], Awaitable[Any]],
        *,
        label: str,
        data_extra: dict[str, Any] | None = None,
    ) -> CommandResponse:
        """Schedule ``coro_factory()`` as the sole deferred playback task for this link.

        The factory is invoked from inside the background task so a coroutine is not
        created and then discarded if the task is cancelled before it starts.
        """
        await self.cancel_deferred_playback()

        async def _run() -> None:
            try:
                await coro_factory()
            except asyncio.CancelledError:
                raise
            except Exception:
                _logger.exception("Deferred BLE command failed (%s)", label)
            finally:
                ct = asyncio.current_task()
                if self._deferred_playback_task is ct:
                    self._deferred_playback_task = None

        self._deferred_playback_task = asyncio.create_task(
            _run(), name=f"lovensepy:ble_deferred:{label}"
        )
        data: dict[str, Any] = {"deferred": True}
        if data_extra:
            data.update(data_extra)
        return CommandResponse(
            code=200,
            type="OK",
            result=True,
            data=data,
        )

    async def disconnect(self) -> None:
        self._intentional_disconnect = True
        try:
            await self.cancel_deferred_playback()
            if self._link_loss_task is not None and not self._link_loss_task.done():
                self._link_loss_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await self._link_loss_task
            self._link_loss_task = None
            if self._client:
                await _safe_disconnect(self._client)
        finally:
            self._intentional_disconnect = False
            self._client = None
            self._resolved_tx_uuid = None
            self._resolved_rx_uuid = None
            self._last_vibrate_sig = None
            self._dual_vibrate_levels = (0, 0)
            self._dual_last_nonzero_motor = None

    def _coerce_dual_vibrate_actions(
        self, clamped: dict[str, int | float]
    ) -> dict[str, int | float]:
        """Normalize dual-motor Function dicts to explicit ``Vibrate1`` + ``Vibrate2`` keys.

        If the caller passes **both** channels, values are kept. If only one channel is
        present, the peer is coerced to **0** (not the last UART level) so
        :func:`~lovensepy.ble_direct.standard_compat.ble_actions_to_uart_strings` can emit
        a **single** motor line and channel-switch priming stays meaningful. Passing only
        ``Vibrate2`` previously duplicated the last ``Vibrate1`` level and produced two
        active channels, which felt “one step behind” on hardware probes.
        """
        hint = self._motor_toy_type_hint()
        feats = ble_uart_features_for_toy_type(hint)
        if "Vibrate1" not in feats or "Vibrate2" not in feats:
            return clamped
        v1 = clamped.get("Vibrate1")
        v2 = clamped.get("Vibrate2")
        if v1 is not None and v2 is not None:
            return {"Vibrate1": int(v1), "Vibrate2": int(v2)}
        if v1 is None and v2 is None:
            return clamped
        if v1 is not None:
            return {"Vibrate1": int(v1), "Vibrate2": 0}
        return {"Vibrate1": 0, "Vibrate2": int(v2)}

    async def query_uart_line(
        self,
        command: str,
        *,
        timeout: float = 4.0,
        encoding: str = "utf-8",
    ) -> str:
        """Write a command to TX and return the first complete line from RX notify (``…;``).

        Requires a discovered RX characteristic. Many toys answer ``DeviceType;``,
        ``Battery;``, etc. with ASCII lines; availability varies by firmware.
        """
        if not self.is_connected or not self._client or not self._resolved_tx_uuid:
            raise LovenseBLEError("Not connected")
        if not self._resolved_rx_uuid:
            raise LovenseBLEError(
                "No UART RX (notify) characteristic — cannot read replies. "
                "Try uart_rx_uuid=... or another firmware."
            )
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[str] = asyncio.Queue()
        buf = bytearray()
        tlock = threading.Lock()

        def handler(_sender: Any, data: bytearray) -> None:
            with tlock:
                buf.extend(data)
                while True:
                    raw = bytes(buf)
                    if b";" not in raw:
                        break
                    i = raw.index(b";")
                    line = bytes(buf[: i + 1])
                    del buf[: i + 1]
                    try:
                        text = line.decode(encoding).strip()
                    except UnicodeDecodeError:
                        continue
                    if text:
                        loop.call_soon_threadsafe(queue.put_nowait, text)

        async with self._query_lock:
            await self._client.start_notify(self._resolved_rx_uuid, handler)
            try:
                await self.send_uart_command(command, encoding=encoding)
                return await asyncio.wait_for(queue.get(), timeout=timeout)
            finally:
                with contextlib.suppress(Exception):
                    await self._client.stop_notify(self._resolved_rx_uuid)

    async def fetch_battery_percent(
        self,
        *,
        attempts: int = 3,
        retry_delay: float = 0.2,
    ) -> int:
        """Send ``Battery;`` and parse the percentage (0–100).

        Some firmware returns a stale or non-battery line on the first notify chunk
        after another UART query; we retry with a short pause between attempts.
        """
        last: Exception | None = None
        n = max(1, attempts)
        for i in range(n):
            try:
                line = await self.query_uart_line("Battery")
                return parse_battery_percent(line)
            except Exception as e:
                last = e
                if i + 1 < n:
                    await asyncio.sleep(retry_delay)
        exc = last
        if exc is None:
            raise RuntimeError("fetch_battery_percent: expected failure after retries") from None
        raise exc

    async def fetch_device_type_fields(self) -> DeviceTypeFields:
        """Send ``DeviceType;`` and parse model letter / firmware / BT address."""
        line = await self.query_uart_line("DeviceType")
        return parse_device_type_fields(line)

    async def fetch_ble_snapshot(
        self,
        *,
        adv_name: str | None = None,
    ) -> dict[str, Any]:
        """Battery + ``DeviceType`` fields + suggested motor features from advertised name.

        Motor roles (which is “vibrate” vs “rotate”) are not usually sent as a list
        over UART; use ``suggested_features`` from the ``LVS-…`` name and
        :func:`~lovensepy.ble_direct.uart_catalog.ble_uart_features_for_toy_type`.
        """
        dev = await self.fetch_device_type_fields()
        await asyncio.sleep(0.12)
        pct = await self.fetch_battery_percent()
        if adv_name is not None:
            slug = _slug_from_adv_name(adv_name)
            self._last_adv_slug = slug
        else:
            slug = self._last_adv_slug
        feats = ble_uart_features_for_toy_type(slug) if slug else ("Vibrate",)
        return {
            "battery_percent": pct,
            "device_type": dev,
            "suggested_features": feats,
            "adv_name_slug": slug,
        }

    def _motor_toy_type_hint(self) -> str | None:
        """Prefer explicit ``toy_type``; else slug from last ``fetch_ble_snapshot(adv_name=...)``."""
        return self._toy_type_hint or self._last_adv_slug

    async def set_vibration(self, level: int) -> None:
        """Set vibration level ``0..20`` (same intent as LAN ``Function`` with ``Vibrate``).

        Under the hood, maps to every ``Vibrate*`` channel the toy is expected to
        have (from ``toy_type`` or a name slug learned via :meth:`fetch_ble_snapshot`
        with ``adv_name``) — e.g. dual-motor models get ``Vibrate1`` + ``Vibrate2``.
        Skips duplicate writes when the full channel set and level are unchanged.
        """
        if not self.is_connected or not self._resolved_tx_uuid or not self._client:
            raise LovenseBLEError("Not connected")
        level = max(0, min(20, int(level)))
        hint = self._motor_toy_type_hint()
        feats = ble_uart_features_for_toy_type(hint)
        vib = tuple(f for f in feats if str(f).startswith("Vibrate"))
        if not vib:
            vib = ("Vibrate",)
        clamped: dict[str, int] = {f: level for f in vib}
        sig = tuple(sorted((k, int(v)) for k, v in clamped.items()))
        if sig == self._last_vibrate_sig:
            return
        if len(clamped) == 1 and next(iter(clamped)) == "Vibrate":
            payload = build_vibrate_command(level).encode()
            await self._write_gatt_char_resilient(payload)
        else:
            await self._send_uart_for_clamped(ble_clamp_actions(clamped))
        self._last_vibrate_sig = sig

    async def send_uart_bytes(
        self,
        payload: bytes,
        *,
        reset_dual_motor_route: bool = True,
    ) -> None:
        """Write raw bytes to the resolved TX characteristic (UTF-8 ASCII commands in practice)."""
        if not self.is_connected or not self._resolved_tx_uuid or not self._client:
            raise LovenseBLEError("Not connected")
        self._last_vibrate_sig = None
        if reset_dual_motor_route:
            self._dual_last_nonzero_motor = None
        await self._write_gatt_char_resilient(payload)

    async def send_uart_command(
        self,
        command: str,
        *,
        encoding: str = "utf-8",
        ensure_semicolon: bool = True,
        reset_dual_motor_route: bool = True,
    ) -> None:
        """Send a Lovense-style UART string (e.g. ``DeviceType;``, ``Battery;``, ``PowerOff;``).

        If ``ensure_semicolon`` is true, a trailing ``;`` is appended when missing.
        This clears vibration dedupe state so a later :meth:`set_vibration` is not
        skipped incorrectly.

        ``reset_dual_motor_route`` (default true): clear internal dual-motor channel
        memory; false for internal peer-``…:0;`` primes so the next switch detection
        still sees the previous active motor.
        """
        text = command.strip()
        if ensure_semicolon and text and not text.endswith(";"):
            text += ";"
        await self.send_uart_bytes(
            text.encode(encoding), reset_dual_motor_route=reset_dual_motor_route
        )

    async def silence_all_motors(self, toy_type: str | None = None) -> None:
        """Send stop commands for ``toy_type`` (or the constructor ``toy_type`` hint).

        If both are absent, sends the same full burst as link-loss recovery
        (:func:`~lovensepy.ble_direct.uart_catalog.default_full_stop_payloads`).
        Per-command failures are ignored so every channel in the list is tried.
        """
        if not self.is_connected or not self._resolved_tx_uuid or not self._client:
            raise LovenseBLEError("Not connected")
        tt = toy_type if toy_type is not None else self._motor_toy_type_hint()
        if tt:
            payloads = [s.encode("utf-8") for s in ble_stop_command_strings_for_toy_type(tt)]
        else:
            payloads = list(default_full_stop_payloads())
        self._last_vibrate_sig = None
        for payload in payloads:
            with contextlib.suppress(Exception):
                await self._write_gatt_char_resilient(payload)
        self._dual_vibrate_levels = (0, 0)

    # --- Standard API parity (async LAN–like control over UART) ---

    def _parse_command_payload(self, command_data: dict[str, Any]) -> dict[str, Any]:
        return clamp_time_sec_in_payload(command_data)

    def _clamp_actions(self, actions: dict[str | Actions, int | float]) -> dict[str, int | float]:
        return ble_clamp_actions(actions)

    @staticmethod
    def _parse_function_action_string(s: str) -> dict[str, float]:
        out: dict[str, float] = {}
        for part in s.split(","):
            part = part.strip()
            if not part:
                continue
            if ":" in part:
                k, v = part.split(":", 1)
                out[k.strip()] = float(v)
        return out

    def _actions_to_rule_letters(self, actions: list[str | Actions] | None) -> str:
        if not actions or Actions.ALL in actions:
            return ""
        return actions_to_rule_letters(actions)

    def _ble_command_response(self, *, uart: list[str] | None = None) -> CommandResponse:
        data: dict[str, Any] = {"transport": "ble"}
        if uart is not None:
            data["uart"] = uart
        return CommandResponse(code=200, type="OK", result=True, data=data)

    async def _send_uart_for_clamped(self, clamped: dict[str, int | float]) -> list[str]:
        expanded = self._coerce_dual_vibrate_actions(clamped)
        try:
            lines = ble_actions_to_uart_strings(expanded, toy_type_hint=self._motor_toy_type_hint())
        except ValueError as e:
            raise LovenseBLEError(str(e)) from e

        hint = self._motor_toy_type_hint()
        prime_d = self._dual_single_channel_prime_delay_s
        if self._dual_single_channel_prime_peer_zero and len(lines) == 1 and prime_d >= 0:
            feats_p = ble_uart_features_for_toy_type(hint)
            if "Vibrate1" in feats_p and "Vibrate2" in feats_p:
                line0 = lines[0]
                last_m = self._dual_last_nonzero_motor
                peer_cmd: str | None = None
                if line0.startswith("Vibrate1:") and not line0.startswith("Vibrate1:0;"):
                    if last_m is not None and last_m != "1":
                        peer_cmd = "Vibrate2:0;"
                elif line0.startswith("Vibrate2:") and not line0.startswith("Vibrate2:0;"):
                    if last_m is not None and last_m != "2":
                        peer_cmd = "Vibrate1:0;"
                if peer_cmd is not None:
                    await self.send_uart_command(
                        peer_cmd,
                        ensure_semicolon=False,
                        reset_dual_motor_route=False,
                    )
                    if prime_d > 0:
                        await asyncio.sleep(prime_d)

        delay = self._uart_inter_command_delay_s
        for i, line in enumerate(lines):
            if i > 0 and delay > 0:
                await asyncio.sleep(delay)
            await self.send_uart_command(line, ensure_semicolon=False)
        feats = ble_uart_features_for_toy_type(hint)
        if (
            "Vibrate1" in feats
            and "Vibrate2" in feats
            and ("Vibrate1" in expanded or "Vibrate2" in expanded)
        ):
            self._dual_vibrate_levels = (
                int(expanded.get("Vibrate1", self._dual_vibrate_levels[0])),
                int(expanded.get("Vibrate2", self._dual_vibrate_levels[1])),
            )
            v1e = int(expanded.get("Vibrate1", 0))
            v2e = int(expanded.get("Vibrate2", 0))
            if v1e > 0 and v2e > 0:
                self._dual_last_nonzero_motor = "both"
            elif v1e > 0:
                self._dual_last_nonzero_motor = "1"
            elif v2e > 0:
                self._dual_last_nonzero_motor = "2"
        return lines

    def _parse_pattern_v2_actions(self, actions: list[dict[str, int]]) -> list[PatternV2Action]:
        """Same validation as :class:`~lovensepy.standard.lan.LANClient`."""
        result: list[PatternV2Action] = []
        for i, a in enumerate(actions):
            if not isinstance(a, dict):
                raise ValueError(
                    f"actions[{i}] must be a dict with 'ts' and 'pos' keys, got {type(a).__name__}"
                )
            if "ts" not in a:
                raise ValueError(f"actions[{i}] missing required key 'ts'")
            if "pos" not in a:
                raise ValueError(f"actions[{i}] missing required key 'pos'")
            try:
                result.append(PatternV2Action(ts=a["ts"], pos=a["pos"]))
            except Exception as e:
                raise ValueError(
                    f"actions[{i}] invalid (ts and pos must be int, pos 0-100): {e}"
                ) from e
        return result

    async def function_request(
        self,
        actions: dict[str | Actions, int | float],
        time: float = 0,
        loop_on_time: float | None = None,
        loop_off_time: float | None = None,
        toy_id: str | list[str] | None = None,
        stop_previous: bool | None = None,
        timeout: float | None = None,
        *,
        wait_for_completion: bool = True,
    ) -> CommandResponse:
        """Send motor levels over UART (same idea as LAN ``Function``).

        If ``time`` is ``0``, levels stay until :meth:`stop` (same idea as LAN with no auto-off).

        When ``wait_for_completion`` is ``False``, timed / looped playback runs in a background
        task and this method returns immediately (matches LAN HTTP fire-and-forget semantics).
        """
        if toy_id is not None:
            pass  # single BLE peripheral; toy id ignored

        async def _body() -> CommandResponse:
            if any(str(k) == str(Actions.STOP) for k in actions):
                await self.silence_all_motors()
                return self._ble_command_response(uart=[])

            if stop_previous:
                await self.silence_all_motors()

            clamped = self._clamp_actions(actions)
            uart: list[str] = []

            if loop_on_time is not None and loop_off_time is not None:
                lo = float(max(loop_on_time, 1.0))
                hi = float(max(loop_off_time, 1.0))
                deadline = asyncio.get_running_loop().time() + time if time > 0 else None
                while True:
                    uart.extend(await self._send_uart_for_clamped(clamped))
                    await asyncio.sleep(lo)
                    await self.silence_all_motors()
                    await asyncio.sleep(hi)
                    if deadline is None:
                        break
                    if asyncio.get_running_loop().time() >= deadline:
                        break
                await self.silence_all_motors()
                return self._ble_command_response(uart=uart)

            uart.extend(await self._send_uart_for_clamped(clamped))
            if time > 0:
                await asyncio.sleep(float(time))
                await self.silence_all_motors()
                chill = self._post_timed_function_silence_cooldown_s
                if chill > 0:
                    await asyncio.sleep(chill)
            return self._ble_command_response(uart=uart)

        has_stop_action = any(str(k) == str(Actions.STOP) for k in actions)
        may_block_after_uart = not has_stop_action and (
            (loop_on_time is not None and loop_off_time is not None) or float(time) > 0
        )
        try:
            if timeout is None:
                if not wait_for_completion and may_block_after_uart:
                    return await self.begin_deferred_playback(
                        _body, label="BleDirectClient.function_request"
                    )
                return await _body()
            if not wait_for_completion and may_block_after_uart:
                return await self.begin_deferred_playback(
                    _body, label="BleDirectClient.function_request"
                )
            return await asyncio.wait_for(_body(), timeout=timeout)
        except TimeoutError as e:
            raise LovenseBLEError("BLE command timed out") from e

    async def stop(
        self,
        toy_id: str | list[str] | None = None,
        timeout: float | None = None,
    ) -> CommandResponse:
        """Stop motors (UART stop burst, same role as LAN ``Function`` + ``Stop``)."""
        if toy_id is not None:
            pass

        await self.cancel_deferred_playback()

        async def _body() -> CommandResponse:
            await self.silence_all_motors()
            return self._ble_command_response(uart=[])

        try:
            if timeout is None:
                return await _body()
            return await asyncio.wait_for(_body(), timeout=timeout)
        except TimeoutError as e:
            raise LovenseBLEError("BLE stop timed out") from e

    async def pattern_request_raw(
        self,
        strength: str,
        rule: str = "V:1;F:;S:100#",
        time: float = 0,
        toy_id: str | list[str] | None = None,
        timeout: float | None = None,
        *,
        wait_for_completion: bool = True,
    ) -> CommandResponse:
        """Replay a strength list over UART (LAN ``Pattern`` is app-side; this emulates).

        With ``wait_for_completion=False``, UART stepping runs in the background so callers
        (e.g. HTTP handlers) are not held open for the whole pattern duration.
        """
        if toy_id is not None:
            pass

        await self.cancel_deferred_playback()

        async def _body() -> CommandResponse:
            try:
                steps, interval_ms, f_letters = parse_pattern_rule_and_strength(rule, strength)
            except ValueError as e:
                raise LovenseBLEError(str(e)) from e
            if not steps:
                return self._ble_command_response(uart=[])

            try:
                feat = pattern_rule_first_letter_to_feature(f_letters)
            except ValueError as e:
                raise LovenseBLEError(str(e)) from e

            interval_sec = interval_ms / 1000.0
            uart: list[str] = []
            deadline = asyncio.get_running_loop().time() + time if time > 0 else None

            while True:
                for n in steps:
                    if deadline is not None and asyncio.get_running_loop().time() >= deadline:
                        await self.silence_all_motors()
                        return self._ble_command_response(uart=uart)
                    lines = await self._send_uart_for_clamped({feat: float(n)})
                    uart.extend(lines)
                    await asyncio.sleep(interval_sec)
                if deadline is None:
                    break
            await self.silence_all_motors()
            return self._ble_command_response(uart=uart)

        try:
            if timeout is None:
                if not wait_for_completion:
                    return await self.begin_deferred_playback(
                        _body, label="BleDirectClient.pattern_request_raw"
                    )
                return await _body()
            if not wait_for_completion:
                return await self.begin_deferred_playback(
                    _body, label="BleDirectClient.pattern_request_raw"
                )
            return await asyncio.wait_for(_body(), timeout=timeout)
        except TimeoutError as e:
            raise LovenseBLEError("BLE pattern timed out") from e

    async def pattern_request(
        self,
        pattern: list[int] | str,
        actions: list[str | Actions] | str | None = None,
        interval: int = 100,
        time: float = 0,
        toy_id: str | list[str] | None = None,
        timeout: float | None = None,
        *,
        wait_for_completion: bool = True,
    ) -> CommandResponse:
        """Pattern over UART (same parameters as LAN; built from ``rule`` + ``strength``)."""
        if isinstance(pattern, str):
            raise TypeError(
                "BleDirectClient.pattern_request expects a list of levels; "
                "use pattern_request_raw(strength, rule, ...) for raw strings."
            )
        if actions is not None and not isinstance(actions, list):
            raise TypeError(
                "pattern_request([levels], actions=...) — `actions` must be a list or None"
            )
        actions = actions or [Actions.ALL]
        pattern = pattern[:50]
        pattern = [min(max(0, n), 20) for n in pattern]
        interval = min(max(interval, 100), 1000)

        letters = self._actions_to_rule_letters(actions)
        rule = f"V:1;F:{letters};S:{interval}#" if letters else f"V:1;F:;S:{interval}#"
        strength = ";".join(map(str, pattern))
        return await self.pattern_request_raw(
            strength,
            rule,
            time,
            toy_id,
            timeout=timeout,
            wait_for_completion=wait_for_completion,
        )

    async def preset_request(
        self,
        name: str | Presets,
        time: float = 0,
        toy_id: str | list[str] | None = None,
        timeout: float | None = None,
        *,
        open_ended: bool = False,
        wait_for_completion: bool = True,
    ) -> CommandResponse:
        """Run a built-in Remote preset over BLE UART: ``Pat:{n};`` or ``Preset:{n};`` with an integer.

        The four names ``pulse`` / ``wave`` / ``fireworks`` / ``earthquake`` map to indices in
        :data:`~lovensepy._constants.PRESET_BLE_PAT_INDEX`. You may also pass a string of digits
        as ``name`` (e.g. ``\"5\"``) for that slot (0–20).

        If constructor ``ble_preset_emulate_with_pattern`` is true (or FastAPI env
        ``LOVENSEPY_BLE_PRESET_EMULATE_PATTERN``), those **four names only** are driven via
        :meth:`pattern_request` instead of Pat/Preset — use when firmware ignores UART preset lines
        but stepping still works.

        UART prefix comes from constructor ``ble_preset_uart_keyword`` (default ``Pat``); public UART
        documentation often documents ``Preset`` for the same idea.

        If ``time`` > 0, that many seconds run before a motor stop burst. If ``time`` is 0 and
        ``open_ended`` is false, :data:`_DEFAULT_BLE_PRESET_HOLD_SEC` is used. If ``open_ended`` is
        true and ``time`` is 0, only the preset line is sent and the device keeps the firmware-defined
        preset until you :meth:`stop` or send another command.

        With ``wait_for_completion=False`` and a positive hold window, the preset line is written before
        return and the sleep + silence runs in a deferred task.

        After cancelling any deferred playback, sends a motor stop burst before the preset UART line
        so firmware is not left in a bad Function step state.
        """
        if toy_id is not None:
            pass
        raw_name = str(name).strip().lower()
        if self._ble_preset_emulate_with_pattern and raw_name in _BLE_APP_PRESET_AS_PATTERN:
            steps_src, interval_ms = _BLE_APP_PRESET_AS_PATTERN[raw_name]
            pattern = [min(max(0, n), 20) for n in list(steps_src)[:50]]
            interval = min(max(interval_ms, 100), 1000)
            await self.cancel_deferred_playback()
            await self.silence_all_motors()

            if time > 0:
                return await self.pattern_request(
                    pattern,
                    actions=[Actions.ALL],
                    interval=interval,
                    time=float(time),
                    toy_id=toy_id,
                    timeout=timeout,
                    wait_for_completion=wait_for_completion,
                )

            if open_ended:
                letters = self._actions_to_rule_letters([Actions.ALL])
                rule = f"V:1;F:{letters};S:{interval}#" if letters else f"V:1;F:;S:{interval}#"
                strength = ";".join(map(str, pattern))

                async def _repeat_forever() -> None:
                    steps_p, interval_ms_p, f_letters = parse_pattern_rule_and_strength(
                        rule, strength
                    )
                    if not steps_p:
                        return
                    feat = pattern_rule_first_letter_to_feature(f_letters)
                    interval_sec = interval_ms_p / 1000.0
                    while True:
                        for n in steps_p:
                            await self._send_uart_for_clamped({feat: float(n)})
                            await asyncio.sleep(interval_sec)

                return await self.begin_deferred_playback(
                    _repeat_forever,
                    label="BleDirectClient.preset_request:emulated_repeat",
                    data_extra={
                        "transport": "ble",
                        "preset_emulated": raw_name,
                        "uart_pattern": strength,
                    },
                )

            return await self.pattern_request(
                pattern,
                actions=[Actions.ALL],
                interval=interval,
                time=float(_DEFAULT_BLE_PRESET_HOLD_SEC),
                toy_id=toy_id,
                timeout=timeout,
                wait_for_completion=wait_for_completion,
            )

        pat_index = _resolve_ble_pat_index(name)
        uart_kw = self._ble_preset_uart_keyword

        await self.cancel_deferred_playback()
        await self.silence_all_motors()
        if time > 0:
            hold_sec = float(time)
        elif open_ended:
            hold_sec = 0.0
        else:
            hold_sec = float(_DEFAULT_BLE_PRESET_HOLD_SEC)

        uart_line = f"{uart_kw}:{pat_index};"

        async def _body() -> CommandResponse:
            await self.send_uart_command(f"{uart_kw}:{pat_index}", ensure_semicolon=True)
            if hold_sec > 0:
                await asyncio.sleep(hold_sec)
                await self.silence_all_motors()
            return self._ble_command_response(uart=[uart_line])

        async def _hold_then_stop() -> None:
            await asyncio.sleep(hold_sec)
            await self.silence_all_motors()

        try:
            if timeout is None:
                if not wait_for_completion and hold_sec > 0:
                    await self.send_uart_command(f"{uart_kw}:{pat_index}", ensure_semicolon=True)
                    return await self.begin_deferred_playback(
                        _hold_then_stop,
                        label="BleDirectClient.preset_request",
                        data_extra={"transport": "ble", "uart": [uart_line]},
                    )
                return await _body()
            if not wait_for_completion and hold_sec > 0:
                await asyncio.wait_for(
                    self.send_uart_command(f"{uart_kw}:{pat_index}", ensure_semicolon=True),
                    timeout=timeout,
                )
                return await self.begin_deferred_playback(
                    _hold_then_stop,
                    label="BleDirectClient.preset_request",
                    data_extra={"transport": "ble", "uart": [uart_line]},
                )
            return await asyncio.wait_for(_body(), timeout=timeout)
        except TimeoutError as e:
            raise LovenseBLEError("BLE preset timed out") from e

    async def position_request(
        self,
        value: int,
        toy_id: str | list[str] | None = None,
        timeout: float | None = None,
    ) -> CommandResponse:
        """Position command for compatible hardware (UART ``Position:{0..100};``)."""
        if toy_id is not None:
            pass
        v = max(0, min(100, int(value)))

        async def _body() -> CommandResponse:
            line = f"Position:{v};"
            await self.send_uart_command(line, ensure_semicolon=False)
            return self._ble_command_response(uart=[line])

        try:
            if timeout is None:
                return await _body()
            return await asyncio.wait_for(_body(), timeout=timeout)
        except TimeoutError as e:
            raise LovenseBLEError("BLE position timed out") from e

    async def pattern_v2_setup(
        self,
        actions: list[dict[str, int]],
        timeout: float | None = None,
    ) -> CommandResponse:
        raise LovenseBLEError(
            "PatternV2 Setup is not available over direct BLE (use LAN or Remote).",
            endpoint="ble_direct",
            payload={"command": "PatternV2", "type": "Setup"},
        )

    async def pattern_v2_play(
        self,
        toy_id: str | list[str] | None = None,
        start_time: int | None = None,
        offset_time: int | None = None,
        time_ms: float | None = None,
        timeout: float | None = None,
    ) -> CommandResponse:
        raise LovenseBLEError(
            "PatternV2 Play is not available over direct BLE (use LAN or Remote).",
            endpoint="ble_direct",
            payload={"command": "PatternV2", "type": "Play"},
        )

    async def pattern_v2_init_play(
        self,
        actions: list[dict[str, int]],
        toy_id: str | list[str] | None = None,
        start_time: int | None = None,
        offset_time: int | None = None,
        stop_previous: int = 0,
        timeout: float | None = None,
    ) -> CommandResponse:
        raise LovenseBLEError(
            "PatternV2 InitPlay is not available over direct BLE (use LAN or Remote).",
            endpoint="ble_direct",
            payload={"command": "PatternV2", "type": "InitPlay"},
        )

    async def pattern_v2_stop(
        self,
        toy_id: str | list[str] | None = None,
        timeout: float | None = None,
    ) -> CommandResponse:
        raise LovenseBLEError(
            "PatternV2 Stop is not available over direct BLE (use LAN or Remote).",
            endpoint="ble_direct",
            payload={"command": "PatternV2", "type": "Stop"},
        )

    async def pattern_v2_sync_time(self, timeout: float | None = None) -> CommandResponse:
        raise LovenseBLEError(
            "PatternV2 SyncTime is not available over direct BLE (use LAN or Remote).",
            endpoint="ble_direct",
            payload={"command": "PatternV2", "type": "SyncTime"},
        )

    async def get_toys(
        self,
        timeout: float | None = None,
        *,
        query_battery: bool = True,
    ) -> GetToysResponse:
        _ = query_battery
        _ = timeout
        raise LovenseBLEError(
            "GetToys is not available over direct BLE; use fetch_ble_snapshot / DeviceType UART.",
            endpoint="ble_direct",
            payload={"command": "GetToys"},
        )

    async def get_toys_name(self, timeout: float | None = None) -> GetToyNameResponse:
        raise LovenseBLEError(
            "GetToyName is not available over direct BLE.",
            endpoint="ble_direct",
            payload={"command": "GetToyName"},
        )

    async def send_command(
        self,
        command_data: dict[str, Any],
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Route the same JSON-style LAN commands to UART (BLE transport)."""
        cmd = self._parse_command_payload(command_data)
        self.last_command = cmd
        kind = cmd.get("command")

        if kind == "Function":
            action = str(cmd.get("action", ""))
            if action.strip().lower() == "stop":
                r = await self.stop(toy_id=cmd.get("toy"), timeout=timeout)
            else:
                parsed = self._parse_function_action_string(action)
                r = await self.function_request(
                    parsed,
                    time=float(cmd.get("timeSec") or 0),
                    loop_on_time=cmd.get("loopRunningSec"),
                    loop_off_time=cmd.get("loopPauseSec"),
                    toy_id=cmd.get("toy"),
                    stop_previous=bool(cmd.get("stopPrevious"))
                    if cmd.get("stopPrevious") is not None
                    else None,
                    timeout=timeout,
                )
            return r.model_dump()

        if kind == "Pattern":
            r = await self.pattern_request_raw(
                str(cmd.get("strength", "")),
                str(cmd.get("rule", "V:1;F:;S:100#")),
                time=float(cmd.get("timeSec") or 0),
                toy_id=cmd.get("toy"),
                timeout=timeout,
            )
            return r.model_dump()

        if kind == "Preset":
            r = await self.preset_request(
                str(cmd.get("name", "")),
                time=float(cmd.get("timeSec") or 0),
                toy_id=cmd.get("toy"),
                timeout=timeout,
                open_ended=bool(cmd.get("openEnded")),
            )
            return r.model_dump()

        if kind == "Position":
            r = await self.position_request(
                int(str(cmd.get("value", "0"))),
                toy_id=cmd.get("toy"),
                timeout=timeout,
            )
            return r.model_dump()

        if kind == "PatternV2":
            ptype = str(cmd.get("type", ""))
            if ptype == "Setup":
                acts = cmd.get("actions") or []
                if not isinstance(acts, list):
                    raise LovenseBLEError(
                        "PatternV2 Setup: actions must be a list", endpoint="ble_direct"
                    )
                self._parse_pattern_v2_actions(acts)  # validate only
                return (await self.pattern_v2_setup(acts, timeout=timeout)).model_dump()
            if ptype == "Play":
                return (
                    await self.pattern_v2_play(
                        toy_id=cmd.get("toy"),
                        start_time=cmd.get("startTime"),
                        offset_time=cmd.get("offsetTime"),
                        time_ms=cmd.get("timeMs"),
                        timeout=timeout,
                    )
                ).model_dump()
            if ptype == "InitPlay":
                acts = cmd.get("actions") or []
                if not isinstance(acts, list):
                    raise LovenseBLEError(
                        "PatternV2 InitPlay: actions must be a list", endpoint="ble_direct"
                    )
                self._parse_pattern_v2_actions(acts)
                return (
                    await self.pattern_v2_init_play(
                        acts,
                        toy_id=cmd.get("toy"),
                        start_time=cmd.get("startTime"),
                        offset_time=cmd.get("offsetTime"),
                        stop_previous=int(cmd.get("stopPrevious") or 0),
                        timeout=timeout,
                    )
                ).model_dump()
            if ptype == "Stop":
                return (
                    await self.pattern_v2_stop(toy_id=cmd.get("toy"), timeout=timeout)
                ).model_dump()
            if ptype == "SyncTime":
                return (await self.pattern_v2_sync_time(timeout=timeout)).model_dump()

        if kind == "GetToys":
            return (await self.get_toys(timeout=timeout)).model_dump()

        if kind == "GetToyName":
            return (await self.get_toys_name(timeout=timeout)).model_dump()

        raise LovenseBLEError(
            f"Unsupported or unknown LAN command over BLE: {kind!r}",
            endpoint="ble_direct",
            payload=cmd,
        )

    def decode_response(self, response: dict[str, Any] | BaseModel | None) -> str:
        """Format response like :meth:`~lovensepy.standard.async_lan.AsyncLANClient.decode_response`."""
        if response is None:
            return "No BLE response object."
        if isinstance(response, BaseModel):
            response = response.model_dump()
        rtype = response.get("type", "Not Response")
        code = response.get("code")
        msg = (
            self.error_codes.get(code, "Unknown Error")
            if isinstance(code, int)
            else f"Unknown code {code}"
        )
        out = f"Response from the app: {rtype}\nResponse from the toy: {msg}, {code}\n"
        if (data := response.get("data")) is not None:
            out += f"Data: {json.dumps(data, indent=4)}"
        return out

    class _PlayContextManager:
        """Async context manager: auto-stop on exit (same as :class:`~lovensepy.standard.async_lan.AsyncLANClient`)."""

        def __init__(
            self,
            client: BleDirectClient,
            actions: dict[str | Actions, int | float],
            *,
            time: float,
            loop_on_time: float | None,
            loop_off_time: float | None,
            toy_id: str | list[str] | None,
            stop_previous: bool | None,
            timeout: float | None,
        ) -> None:
            self._client = client
            self._actions = actions
            self._time = time
            self._loop_on_time = loop_on_time
            self._loop_off_time = loop_off_time
            self._toy_id = toy_id
            self._stop_previous = stop_previous
            self._timeout = timeout
            self._response: CommandResponse | None = None

        async def __aenter__(self) -> CommandResponse:
            self._response = await self._client.function_request(
                self._actions,
                time=self._time,
                loop_on_time=self._loop_on_time,
                loop_off_time=self._loop_off_time,
                toy_id=self._toy_id,
                stop_previous=self._stop_previous,
                timeout=self._timeout,
            )
            return self._response

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            try:
                await self._client.stop(self._toy_id, timeout=self._timeout)
            except LovenseBLEError:
                if exc_type is None:
                    raise
            return False

    def play(
        self,
        actions: dict[str | Actions, int | float],
        *,
        time: float = 0,
        loop_on_time: float | None = None,
        loop_off_time: float | None = None,
        toy_id: str | list[str] | None = None,
        stop_previous: bool | None = None,
        timeout: float | None = None,
    ) -> BleDirectClient._PlayContextManager:
        """Async: start a Function command on enter and stop on exit."""
        return BleDirectClient._PlayContextManager(
            self,
            actions,
            time=time,
            loop_on_time=loop_on_time,
            loop_off_time=loop_off_time,
            toy_id=toy_id,
            stop_previous=stop_previous,
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self.disconnect()
