"""Optional periodic BLE advertisement scan (RSSI) for service callbacks."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import TYPE_CHECKING, Any

from lovensepy.ble_direct.client import LovenseBleAdvertisement, scan_lovense_ble_advertisements

if TYPE_CHECKING:
    from .config import ServiceConfig

_logger = logging.getLogger(__name__)


def merge_ble_advertisement_rows(
    last_map: dict[str, dict[str, Any]],
    rows: Iterable[LovenseBleAdvertisement],
) -> None:
    """Update ``last_map`` (address → ``{address, name, rssi}``) from scan results."""
    for row in rows:
        last_map[row.address] = {
            "address": row.address,
            "name": row.name,
            "rssi": row.rssi,
        }


async def _ble_advertisement_monitor_loop(
    *,
    cfg: ServiceConfig,
    stop: asyncio.Event,
    state: Any,
    on_sync: Callable[[LovenseBleAdvertisement], None] | None,
    on_async: Callable[[LovenseBleAdvertisement], Awaitable[None]] | None,
) -> None:
    prefix = cfg.ble_scan_prefix_or_none()
    while not stop.is_set():
        try:
            rows = await scan_lovense_ble_advertisements(
                timeout=min(cfg.ble_scan_timeout, 8.0),
                name_prefix=prefix,
            )
        except Exception:
            _logger.debug("BLE advertisement scan failed", exc_info=True)
            rows = []
        merge_ble_advertisement_rows(state.last_ble_advertisements, rows)
        for row in rows:
            if on_sync is not None:
                try:
                    on_sync(row)
                except Exception:
                    _logger.debug("on_ble_advertisement callback failed", exc_info=True)
            if on_async is not None:
                try:
                    await on_async(row)
                except Exception:
                    _logger.debug("on_ble_advertisement_async callback failed", exc_info=True)
        try:
            await asyncio.wait_for(stop.wait(), timeout=cfg.ble_monitor_interval_sec)
        except TimeoutError:
            continue


def start_ble_advertisement_monitor(
    *,
    cfg: ServiceConfig,
    state: Any,
    on_sync: Callable[[LovenseBleAdvertisement], None] | None,
    on_async: Callable[[LovenseBleAdvertisement], Awaitable[None]] | None,
) -> tuple[asyncio.Event, asyncio.Task[None]]:
    stop = asyncio.Event()
    task = asyncio.create_task(
        _ble_advertisement_monitor_loop(
            cfg=cfg,
            stop=stop,
            state=state,
            on_sync=on_sync,
            on_async=on_async,
        ),
        name="lovensepy:ble_advert_monitor",
    )
    return stop, task
