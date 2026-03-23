"""
Multi-toy BLE facade: one hub, many :class:`BleDirectClient` instances.

Mirrors the *shape* of the LAN API (``toy`` / ``toy_id`` routing, ``get_toys``,
``send_command``) while each peripheral still uses its own GATT connection.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from lovensepy._command_utils import clamp_time_sec_in_payload
from lovensepy._constants import ERROR_CODES, Actions, Presets
from lovensepy._models import (
    CommandResponse,
    GetToyNameResponse,
    GetToysResponse,
)
from lovensepy.exceptions import LovenseBLEError
from lovensepy.standard.async_base import LovenseAsyncControlClient

from .branding_resolve import resolve_ble_branding_nickname
from .client import (
    BleDirectClient,
    _schedule_deferred_ble_coro,
    _slug_from_adv_name,
    scan_lovense_ble_devices,
)

_logger = logging.getLogger(__name__)


@dataclass
class _ToyEntry:
    client: BleDirectClient
    display_name: str
    toy_type_slug: str | None = None
    firmware: str | None = None
    model_letter: str | None = None
    suggested_features: tuple[str, ...] = field(default_factory=tuple)
    #: Last known UART battery from :meth:`BleDirectClient.fetch_ble_snapshot` (enrich).
    battery_percent: int | None = None


def _make_toy_id(address: str, advertised_name: str | None, index: int) -> str:
    """Stable id from BLE address + advertised name (LAN ``toyId``-like)."""
    slug = _slug_from_adv_name(advertised_name)
    tail = re.sub(r"[^0-9a-fA-F]", "", address)[-10:]
    if slug and tail:
        return f"{slug}_{tail.lower()}"
    if tail:
        return f"toy_{tail.lower()}"
    return f"toy_{index}"


def make_ble_toy_id(address: str, advertised_name: str | None, index: int = 0) -> str:
    """Stable toy id for a scan row before :meth:`BleDirectHub.add_toy`."""
    return _make_toy_id(address, advertised_name, index)


def _toy_id_from_device_bt_mac(slug: str | None, bt_addr_hex: str) -> str | None:
    """Prefer ``DeviceType`` BT address (real MAC) over OS address (opaque on Apple OS)."""
    clean = re.sub(r"[^0-9a-fA-F]", "", bt_addr_hex)
    if len(clean) < 10:
        return None
    tail = clean[-10:].lower()
    if slug:
        return f"{slug}_{tail}"
    return f"toy_{tail}"


def _display_name_from_entry(ent: _ToyEntry) -> str:
    """Prefer clean marketing-ish name (without raw model/firmware noise)."""
    name, _src = resolve_ble_branding_nickname(
        advertised_name=ent.display_name,
        toy_type_slug=ent.toy_type_slug,
        model_letter=ent.model_letter,
        firmware=ent.firmware,
    )
    return name


async def _sleep_until_cancel_or_timeout(cancel: asyncio.Event, seconds: float) -> None:
    """Like ``asyncio.sleep(seconds)`` but ends early if ``cancel`` is set (e.g. :meth:`stop`)."""
    sleep_task = asyncio.create_task(asyncio.sleep(seconds))
    wait_task = asyncio.create_task(cancel.wait())
    try:
        await asyncio.wait(
            {sleep_task, wait_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        for t in (sleep_task, wait_task):
            if not t.done():
                t.cancel()
        await asyncio.gather(sleep_task, wait_task, return_exceptions=True)


class _HubMultiPlay:
    """Async ``play`` across several :class:`BleDirectClient` instances."""

    def __init__(self, managers: list[Any]) -> None:
        self._managers = managers

    async def __aenter__(self) -> Any:
        outs = await asyncio.gather(*(m.__aenter__() for m in self._managers))
        return outs[0] if len(outs) == 1 else outs

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        await asyncio.gather(*(m.__aexit__(exc_type, exc, tb) for m in self._managers))
        return False


def _parse_command_payload(command_data: dict[str, Any]) -> dict[str, Any]:
    return clamp_time_sec_in_payload(command_data)


def _bundle_multi_command_results(
    ids: list[str], results: list[CommandResponse]
) -> CommandResponse:
    if len(results) == 1:
        return results[0]
    return CommandResponse(
        code=200,
        type="OK",
        result=True,
        data={
            "transport": "ble_hub",
            "toys": {i: r.model_dump() for i, r in zip(ids, results)},
        },
    )


class BleDirectHub(LovenseAsyncControlClient):
    """LAN-style multi-toy control over direct BLE (one link per registered toy).

    **Quick path:** :meth:`discover_and_connect` scans for ``LVS-…`` advertisers,
    assigns ids, connects, and optionally reads UART (battery / ``DeviceType``) so
    :meth:`get_toys` looks like the LAN tutorial.

    Or register addresses yourself with :meth:`add_toy`, then ``connect_all`` /
    ``connect`` and use ``function_request``, ``preset_request``, ``send_command``,
    etc. ``toy_id=None`` means **all** registered toys.

    This does **not** replace Lovense Remote for pairing; each device must be
    connectable from your OS Bluetooth stack, and most toys allow only one
    central at a time.
    """

    def __init__(self) -> None:
        self._toys: dict[str, _ToyEntry] = {}
        self.actions = Actions
        self.presets = Presets
        self.error_codes = ERROR_CODES
        self.last_command: dict[str, Any] | None = None
        #: Set during multi-toy coordinated hold so :meth:`stop` can shorten the wait.
        self._active_hold_cancel: asyncio.Event | None = None

    def __len__(self) -> int:
        return len(self._toys)

    @property
    def toy_ids(self) -> tuple[str, ...]:
        """Registered toy ids (sorted)."""
        return tuple(sorted(self._toys))

    def add_toy(
        self,
        toy_id: str,
        address: str,
        *,
        toy_type: str | None = None,
        name: str | None = None,
        replace: bool = False,
        **client_kwargs: Any,
    ) -> None:
        """Register a peripheral. Does not connect — use :meth:`connect` / :meth:`connect_all`.

        ``**client_kwargs`` are passed to :class:`BleDirectClient` (e.g.
        ``uart_tx_uuid``, ``write_with_response``).
        """
        tid = str(toy_id).strip()
        if not tid:
            raise ValueError("toy_id must not be empty")
        if tid in self._toys and not replace:
            raise ValueError(f"Toy id {tid!r} already registered (pass replace=True to swap)")
        if tid in self._toys and replace:
            old = self._toys.pop(tid)
            if old.client.is_connected:
                raise LovenseBLEError(
                    f"Toy {tid!r} is still connected; await disconnect_toy() before replace",
                    endpoint="ble_direct",
                )
        display = (name or "").strip() or tid
        raw_name = (name or "").strip()
        client_kw: dict[str, Any] = dict(client_kwargs)
        if raw_name.upper().startswith("LVS-"):
            client_kw.setdefault("advertised_name", raw_name)
        self._toys[tid] = _ToyEntry(
            client=BleDirectClient(address, toy_type=toy_type, **client_kw),
            display_name=display,
            toy_type_slug=toy_type,
        )

    def get_client(self, toy_id: str) -> BleDirectClient:
        """Return the underlying :class:`BleDirectClient` for advanced use."""
        try:
            return self._toys[toy_id].client
        except KeyError as e:
            raise LovenseBLEError(f"Unknown toy id {toy_id!r}", endpoint="ble_direct") from e

    def _require_ids(self, toy_id: str | list[str] | None) -> list[str]:
        if not self._toys:
            raise LovenseBLEError("No toys registered on this hub", endpoint="ble_direct")
        if toy_id is None:
            return list(self._toys.keys())
        if isinstance(toy_id, str):
            if toy_id not in self._toys:
                raise LovenseBLEError(f"Unknown toy id {toy_id!r}", endpoint="ble_direct")
            return [toy_id]
        out: list[str] = []
        for t in toy_id:
            if t not in self._toys:
                raise LovenseBLEError(f"Unknown toy id {t!r}", endpoint="ble_direct")
            out.append(t)
        return out

    async def connect(self, toy_id: str) -> None:
        await self.get_client(toy_id).connect()

    async def connect_all(self) -> None:
        await asyncio.gather(*(e.client.connect() for e in self._toys.values()))

    async def disconnect(self, toy_id: str) -> None:
        await self.get_client(toy_id).disconnect()

    async def disconnect_all(self) -> None:
        await asyncio.gather(*(e.client.disconnect() for e in self._toys.values()))

    async def remove_toy(self, toy_id: str) -> None:
        """Disconnect (if needed) and drop registration."""
        tid = str(toy_id).strip()
        ent = self._toys.pop(tid, None)
        if ent is None:
            return
        if ent.client.is_connected:
            with contextlib.suppress(Exception):
                await ent.client.silence_all_motors(ent.toy_type_slug)
            await ent.client.disconnect()

    async def _clear_registry(self) -> None:
        for tid in list(self._toys.keys()):
            await self.remove_toy(tid)

    async def enrich_toy_from_uart(
        self,
        toy_id: str,
        *,
        adv_name: str | None = None,
    ) -> str:
        """After :meth:`connect`, read UART (``DeviceType`` / battery) and refresh hub fields.

        Used for ``GetToys`` (``version``, ``nickName``, ``type``, features). Pass
        ``adv_name`` (e.g. ``LVS-Lush``) when known from a scan so ToyConfig slug /
        branding resolves; if omitted, uses ``display_name`` when it differs from
        ``toy_id``, else still queries UART so ``model_letter`` / ``firmware`` fill in.

        Returns the toy id to use after a possible MAC-based rename (same as
        :meth:`discover_and_connect`).
        """
        ent = self._toys.get(toy_id)
        if ent is None or not ent.client.is_connected:
            return toy_id
        try:
            adv = (adv_name or "").strip() or None
            if adv is None:
                dn = ent.display_name.strip()
                if dn and dn != toy_id:
                    adv = dn
            if adv and adv.upper().startswith("LVS-"):
                ent.display_name = adv
                if sl := _slug_from_adv_name(adv):
                    ent.toy_type_slug = ent.toy_type_slug or sl
            snap = await ent.client.fetch_ble_snapshot(adv_name=adv)
            dt = snap["device_type"]
            ent.firmware = dt.firmware
            ent.model_letter = dt.model_letter
            ent.suggested_features = tuple(snap.get("suggested_features") or ())
            bp = snap.get("battery_percent")
            ent.battery_percent = int(bp) if isinstance(bp, int) else None
            slug = (_slug_from_adv_name(adv) if adv else None) or ent.toy_type_slug
            preferred = _toy_id_from_device_bt_mac(slug, dt.bt_addr_hex)
            cur = toy_id
            if preferred and preferred != cur and preferred not in self._toys:
                self._toys[preferred] = self._toys.pop(cur)
                cur = preferred
            return cur
        except Exception:
            _logger.debug(
                "UART enrichment failed for toy %r (adv_name=%r):",
                toy_id,
                adv_name,
                exc_info=True,
            )
            return toy_id

    async def discover_and_connect(
        self,
        *,
        timeout: float = 10.0,
        name_prefix: str | None = "LVS-",
        clear: bool = True,
        enrich_uart: bool = True,
        **client_kwargs: Any,
    ) -> list[str]:
        """Scan, register, connect, and optionally enrich from UART (like “finding” toys).

        ``timeout`` is **only** how long BLE discovery listens — not motor/preset duration.

        Returns registered toy ids (sorted). Uses
        :func:`~lovensepy.ble_direct.client.scan_lovense_ble_devices`.
        """
        rows = await scan_lovense_ble_devices(timeout=timeout, name_prefix=name_prefix)
        if clear:
            await self._clear_registry()
        for i, (addr, name) in enumerate(rows):
            tid = _make_toy_id(addr, name, i)
            slug = _slug_from_adv_name(name)
            self.add_toy(
                tid,
                addr,
                toy_type=slug,
                name=name or tid,
                replace=False,
                **client_kwargs,
            )
        await self.connect_all()
        if enrich_uart and self._toys:
            for _tid, ent in list(self._toys.items()):
                adv = ent.display_name if ent.display_name and ent.display_name != _tid else None
                await self.enrich_toy_from_uart(_tid, adv_name=adv)
        for _tid, ent in list(self._toys.items()):
            if not ent.client.is_connected:
                continue
            with contextlib.suppress(Exception):
                await ent.client.silence_all_motors(ent.toy_type_slug)
        return list(self.toy_ids)

    async def aclose(self) -> None:
        """Disconnect every registered toy."""
        await self.disconnect_all()

    async def __aenter__(self) -> BleDirectHub:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        await self.aclose()
        return False

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
        """Fan-out to clients. For **several** toys with ``time > 0`` (no loop pattern),
        starts all motors, then **one** shared wall-clock hold (cancellable via
        :meth:`stop`), then stops all — so effects stay aligned and host stacks
        (e.g. macOS BLE) cannot serialize two per-client sleeps into a long train.
        """
        ids = self._require_ids(toy_id)
        coordinated_hold = (
            len(ids) > 1
            and float(time) > 0
            and loop_on_time is None
            and loop_off_time is None
            and not any(str(k) == str(Actions.STOP) for k in actions)
        )

        if coordinated_hold:
            for i in ids:
                await self._toys[i].client.cancel_deferred_playback()

            async def _coordinated() -> CommandResponse:
                cancel_hold = asyncio.Event()
                self._active_hold_cancel = cancel_hold
                try:
                    if stop_previous:
                        await asyncio.gather(
                            *(
                                self._toys[i].client.silence_all_motors(self._toys[i].toy_type_slug)
                                for i in ids
                            )
                        )
                    await asyncio.gather(
                        *(
                            self._toys[i].client.function_request(
                                actions,
                                time=0,
                                loop_on_time=None,
                                loop_off_time=None,
                                toy_id=None,
                                stop_previous=False,
                                timeout=None,
                            )
                            for i in ids
                        )
                    )
                    await _sleep_until_cancel_or_timeout(cancel_hold, float(time))
                    results = await asyncio.gather(
                        *(self._toys[i].client.stop(timeout=None) for i in ids)
                    )
                    return _bundle_multi_command_results(ids, list(results))
                finally:
                    if self._active_hold_cancel is cancel_hold:
                        self._active_hold_cancel = None

            if not wait_for_completion:
                return _schedule_deferred_ble_coro(
                    _coordinated(), label="BleDirectHub.function_coordinated"
                )
            try:
                if timeout is not None:
                    return await asyncio.wait_for(_coordinated(), timeout=timeout)
                return await _coordinated()
            except TimeoutError as e:
                raise LovenseBLEError(
                    "BLE hub command timed out",
                    endpoint="ble_direct",
                    payload={"toy_ids": ids},
                ) from e

        coros = [
            self._toys[i].client.function_request(
                actions,
                time=time,
                loop_on_time=loop_on_time,
                loop_off_time=loop_off_time,
                toy_id=None,
                stop_previous=stop_previous,
                timeout=timeout,
                wait_for_completion=wait_for_completion,
            )
            for i in ids
        ]
        results = await asyncio.gather(*coros)
        return _bundle_multi_command_results(ids, list(results))

    async def stop(
        self,
        toy_id: str | list[str] | None = None,
        timeout: float | None = None,
    ) -> CommandResponse:
        if self._active_hold_cancel is not None:
            self._active_hold_cancel.set()
        ids = self._require_ids(toy_id)
        results = await asyncio.gather(*(self._toys[i].client.stop(timeout=timeout) for i in ids))
        if len(results) == 1:
            return results[0]
        return CommandResponse(
            code=200,
            type="OK",
            result=True,
            data={
                "transport": "ble_hub",
                "toys": {i: r.model_dump() for i, r in zip(ids, results)},
            },
        )

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
        ids = self._require_ids(toy_id)
        results = await asyncio.gather(
            *(
                self._toys[i].client.pattern_request_raw(
                    strength, rule, time, None, timeout, wait_for_completion=wait_for_completion
                )
                for i in ids
            )
        )
        if len(results) == 1:
            return results[0]
        return CommandResponse(
            code=200,
            type="OK",
            result=True,
            data={
                "transport": "ble_hub",
                "toys": {i: r.model_dump() for i, r in zip(ids, results)},
            },
        )

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
        if isinstance(pattern, str):
            raise TypeError(
                "BleDirectHub.pattern_request expects a list of levels; "
                "use pattern_request_raw(strength, rule, ...) for raw strings."
            )
        if actions is not None and not isinstance(actions, list):
            raise TypeError(
                "pattern_request([levels], actions=...) — `actions` must be a list or None"
            )
        ids = self._require_ids(toy_id)
        results = await asyncio.gather(
            *(
                self._toys[i].client.pattern_request(
                    pattern,
                    actions,
                    interval,
                    time,
                    None,
                    timeout,
                    wait_for_completion=wait_for_completion,
                )
                for i in ids
            )
        )
        if len(results) == 1:
            return results[0]
        return CommandResponse(
            code=200,
            type="OK",
            result=True,
            data={
                "transport": "ble_hub",
                "toys": {i: r.model_dump() for i, r in zip(ids, results)},
            },
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
        ids = self._require_ids(toy_id)
        results = await asyncio.gather(
            *(
                self._toys[i].client.preset_request(
                    name,
                    time,
                    None,
                    timeout,
                    open_ended=open_ended,
                    wait_for_completion=wait_for_completion,
                )
                for i in ids
            )
        )
        if len(results) == 1:
            return results[0]
        return CommandResponse(
            code=200,
            type="OK",
            result=True,
            data={
                "transport": "ble_hub",
                "toys": {i: r.model_dump() for i, r in zip(ids, results)},
            },
        )

    async def position_request(
        self,
        value: int,
        toy_id: str | list[str] | None = None,
        timeout: float | None = None,
    ) -> CommandResponse:
        ids = self._require_ids(toy_id)
        results = await asyncio.gather(
            *(self._toys[i].client.position_request(value, None, timeout) for i in ids)
        )
        if len(results) == 1:
            return results[0]
        return CommandResponse(
            code=200,
            type="OK",
            result=True,
            data={
                "transport": "ble_hub",
                "toys": {i: r.model_dump() for i, r in zip(ids, results)},
            },
        )

    async def pattern_v2_setup(
        self,
        actions: list[dict[str, int]],
        timeout: float | None = None,
    ) -> CommandResponse:
        raise LovenseBLEError(
            "PatternV2 is not available over direct BLE (hub or single client).",
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
            "PatternV2 is not available over direct BLE (hub or single client).",
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
            "PatternV2 is not available over direct BLE (hub or single client).",
            endpoint="ble_direct",
            payload={"command": "PatternV2", "type": "InitPlay"},
        )

    async def pattern_v2_stop(
        self,
        toy_id: str | list[str] | None = None,
        timeout: float | None = None,
    ) -> CommandResponse:
        raise LovenseBLEError(
            "PatternV2 is not available over direct BLE (hub or single client).",
            endpoint="ble_direct",
            payload={"command": "PatternV2", "type": "Stop"},
        )

    async def pattern_v2_sync_time(self, timeout: float | None = None) -> CommandResponse:
        raise LovenseBLEError(
            "PatternV2 is not available over direct BLE (hub or single client).",
            endpoint="ble_direct",
            payload={"command": "PatternV2", "type": "SyncTime"},
        )

    async def get_toys(
        self,
        timeout: float | None = None,
        *,
        query_battery: bool = True,
    ) -> GetToysResponse:
        """Synthetic ``GetToys`` from registered toys. Optionally queries UART battery per toy."""
        if not self._toys:
            return GetToysResponse.model_validate({"data": {"toys": []}})
        toy_rows: list[dict[str, Any]] = []
        for tid in sorted(self._toys):
            ent = self._toys[tid]
            c = ent.client
            connected = c.is_connected
            battery: int | None = None
            if query_battery and connected:
                try:
                    battery = await c.fetch_battery_percent()
                except Exception:
                    battery = None
                if battery is None and ent.battery_percent is not None:
                    battery = ent.battery_percent
            row: dict[str, Any] = {
                "id": tid,
                "name": ent.display_name,
                "nickName": _display_name_from_entry(ent),
                "status": "1" if connected else "0",
            }
            if ent.toy_type_slug:
                row["type"] = ent.toy_type_slug
            if ent.firmware:
                row["version"] = ent.firmware
            if ent.suggested_features:
                row["fullFunctionNames"] = list(ent.suggested_features)
            if battery is not None:
                row["battery"] = battery
            toy_rows.append(row)
        # ``GetToysResponse`` validates ``data`` via LAN-shaped dicts, not a nested Pydantic model.
        return GetToysResponse.model_validate({"data": {"toys": toy_rows}})

    async def get_toys_name(self, timeout: float | None = None) -> GetToyNameResponse:
        names = [self._toys[i].display_name for i in sorted(self._toys)]
        return GetToyNameResponse(data=names)

    async def send_command(
        self,
        command_data: dict[str, Any],
        timeout: float | None = None,
    ) -> dict[str, Any]:
        cmd = _parse_command_payload(command_data)
        self.last_command = cmd
        kind = cmd.get("command")
        if kind == "GetToys":
            return (await self.get_toys(timeout=timeout)).model_dump()
        if kind == "GetToyName":
            return (await self.get_toys_name(timeout=timeout)).model_dump()
        raw_toy = cmd.get("toy")
        if raw_toy is None:
            targets = self._require_ids(None)
        elif isinstance(raw_toy, str):
            targets = self._require_ids(raw_toy)
        else:
            targets = self._require_ids(list(raw_toy))

        async def _one(tid: str) -> dict[str, Any]:
            sub = dict(cmd)
            sub.pop("toy", None)
            return await self._toys[tid].client.send_command(sub, timeout=timeout)

        results = await asyncio.gather(*(_one(t) for t in targets))
        if len(results) == 1:
            return results[0]
        return {
            "code": 200,
            "type": "OK",
            "data": {"transport": "ble_hub", "per_toy": dict(zip(targets, results))},
        }

    def decode_response(self, response: dict[str, Any] | BaseModel | None) -> str:
        """Human-readable summary of a hub command response (like LAN ``decode_response``)."""
        if response is None:
            return "No BLE hub response object."
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
    ) -> Any:
        """Async context manager like :meth:`BleDirectClient.play`. ``toy_id=None`` = all toys."""
        ids = self._require_ids(toy_id)
        if len(ids) == 1:
            return self.get_client(ids[0]).play(
                actions,
                time=time,
                loop_on_time=loop_on_time,
                loop_off_time=loop_off_time,
                toy_id=None,
                stop_previous=stop_previous,
                timeout=timeout,
            )
        managers = [
            self.get_client(tid).play(
                actions,
                time=time,
                loop_on_time=loop_on_time,
                loop_off_time=loop_off_time,
                toy_id=None,
                stop_previous=stop_previous,
                timeout=timeout,
            )
            for tid in ids
        ]
        return _HubMultiPlay(managers)


__all__ = ["BleDirectHub"]
