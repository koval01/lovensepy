"""
BLE integration: scan for Lovense advertisers, connect via :class:`BleDirectHub`, exercise APIs.

Used by ``tests/test_ble_direct_integration.py`` and sequential connection tests.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable

from lovensepy._constants import FUNCTION_RANGES, Actions, Presets
from lovensepy.ble_direct.hub import BleDirectHub
from lovensepy.exceptions import LovenseBLEError
from lovensepy.toy_utils import features_for_toy


def _log_default(msg: str) -> None:
    print(msg, flush=True)


def _env_truthy(key: str) -> bool:
    return os.environ.get(key, "").strip().lower() in ("1", "true", "yes")


def _step_trace() -> bool:
    return _env_truthy("LOVENSE_BLE_STEP_TRACE")


def _toy_dict_for_features(toy_row: object) -> dict:
    d = toy_row.model_dump() if hasattr(toy_row, "model_dump") else dict(toy_row)  # type: ignore[arg-type]
    if d.get("type") and not d.get("toyType"):
        d["toyType"] = d["type"]
    return d


def _level_for_feature(fname: str) -> int:
    lo, hi = FUNCTION_RANGES.get(fname, (0, 10))
    cap = min(6, hi)
    return max(lo, min(cap, 6))


def _action_for_feature(fname: str) -> Actions | None:
    if fname in ("All", "Stop"):
        return None
    try:
        return Actions(fname)
    except ValueError:
        return None


async def _try(
    label: str,
    coro,
    log: Callable[[str], None],
) -> bool:
    try:
        if _step_trace():
            log(f"  → {label}")
        await coro
        log(f"  ok: {label}")
        return True
    except (LovenseBLEError, TimeoutError, OSError, ValueError) as exc:
        log(f"  skip: {label} ({exc})")
        return False


async def run_ble_discovery_exercise(
    *,
    scan_timeout: float | None = None,
    log: Callable[[str], None] = _log_default,
) -> int:
    """
    Scan for ``LVS-`` devices, connect all, run vibrate / per-feature / preset / pattern / position.

    Returns the number of toys that were registered and connected. Returns ``0`` if none found.

    Environment:
    - ``LOVENSE_BLE_SCAN_TIMEOUT`` — BLE scan seconds (default 15).
    - ``LOVENSE_BLE_STEP_SEC`` — duration for timed motor steps (default 1.2).
    - ``LOVENSE_BLE_INTER_STEP_SEC`` — extra pause between steps (default ``0.2``). Helps
      flaky host stacks (e.g. macOS CoreBluetooth).
    - ``LOVENSE_BLE_STEP_TRACE`` — if ``1``/``true``/``yes``, log ``  → {label}`` **before**
      each step and ``  ok: {label}`` **after**. Timed steps send UART at the ``→`` line
      (start of the await); ``ok`` appears only after hold + internal stop + cooldown, so
      **do not** use ``ok`` as the moment the motor starts.

    **Note:** ``function_request`` / ``preset_request`` / ``pattern_request`` with ``time>0``
    already end with :meth:`silence_all_motors` inside :class:`BleDirectClient`. This scenario
    **does not** call :meth:`BleDirectHub.stop` again after those (doing so duplicated the
    stop burst and could make the **next** motor command fail — “every second step silent”).
    - ``LOVENSE_BLE_DUAL_PROBE_MIN_GAP`` — floor (seconds) for pause after each dual-probe
      ``stop`` (default ``0.35``); dual probe uses ``max(inter_step, this)``.
    - ``LOVENSE_BLE_DUAL_PROBE_PASS_BREAK`` — idle seconds **between** the V1→V2 pass and
      the V2→V1 pass (default ``0.55``).
    - ``LOVENSE_BLE_DUAL_PROBE_PEER_MOTOR_PAD`` — extra pause before the **second** motor in
      each pass: before ``Vibrate2`` in V1→V2 and before ``Vibrate1`` in V2→V1 (default
      ``0.5``). Falls back to ``LOVENSE_BLE_DUAL_PROBE_AFTER_V2_BEFORE_V1`` if unset.
    - ``LOVENSE_BLE_DUAL_PROBE_LAST_V1_EXTRA`` — additional seconds **after** that pad, only
      before the final ``[V2→V1] Vibrate1`` step (default ``0.5``). Helps when the 4th
      probe write is dropped after three timed motor cycles.
    - ``LOVENSE_BLE_DUAL_PROBE_TAIL_COOLDOWN`` — idle seconds **after** the full dual probe
      (all four steps) and **before** ``preset_request`` (default ``0.85``). Reduces mistaking
      the next preset pulse for “vibration that started after the probe”.
    - ``LOVENSE_BLE_DUAL_PROBE_STOP_BEFORE_LAST_V1`` — if truthy, call :meth:`BleDirectHub.stop`
      for that toy (full UART stop burst) immediately before the final ``[V2→V1] Vibrate1``
      probe step, then wait ``LOVENSE_BLE_DUAL_PROBE_STOP_BEFORE_LAST_V1_PAUSE`` seconds
      (default ``0.3``). **Opt-in:** an extra stop can help a stuck firmware state, or make
      the last write flakier — try only if the 4th step stays silent.

    Toys with **both** ``Vibrate1`` and ``Vibrate2`` (e.g. Edge) skip those two in the
    generic per-feature loop and instead run a **dual order probe**: first
    ``Vibrate1`` → stop → ``Vibrate2`` → stop, then the same levels in **reverse**
    order (``Vibrate2`` first, then ``Vibrate1``) so you can tell a bad second GATT
    write from a ``Vibrate2``-specific issue (read ``ok:`` lines with
    ``dual probe``).
    """
    if scan_timeout is None:
        scan_timeout = float(os.environ.get("LOVENSE_BLE_SCAN_TIMEOUT", "15"))

    step_sec = float(os.environ.get("LOVENSE_BLE_STEP_SEC", "1.2"))
    inter_step = float(os.environ.get("LOVENSE_BLE_INTER_STEP_SEC", "0.2"))
    dual_probe_gap = max(
        inter_step,
        float(os.environ.get("LOVENSE_BLE_DUAL_PROBE_MIN_GAP", "0.35")),
    )
    dual_probe_pass_break = float(os.environ.get("LOVENSE_BLE_DUAL_PROBE_PASS_BREAK", "0.55"))
    _peer_pad = os.environ.get("LOVENSE_BLE_DUAL_PROBE_PEER_MOTOR_PAD")
    if _peer_pad is None:
        _peer_pad = os.environ.get("LOVENSE_BLE_DUAL_PROBE_AFTER_V2_BEFORE_V1", "0.5")
    dual_probe_peer_pad = float(_peer_pad)
    dual_probe_last_v1_extra = float(
        os.environ.get("LOVENSE_BLE_DUAL_PROBE_LAST_V1_EXTRA", "0.5"),
    )
    dual_probe_tail_cooldown = float(
        os.environ.get("LOVENSE_BLE_DUAL_PROBE_TAIL_COOLDOWN", "0.85"),
    )
    dual_probe_stop_before_last_v1 = _env_truthy("LOVENSE_BLE_DUAL_PROBE_STOP_BEFORE_LAST_V1")
    dual_probe_stop_before_last_v1_pause = float(
        os.environ.get("LOVENSE_BLE_DUAL_PROBE_STOP_BEFORE_LAST_V1_PAUSE", "0.3"),
    )
    pulse_preset_sec = min(3.0, max(1.0, step_sec + 0.8))
    pattern_sec = min(4.0, max(1.5, step_sec + 0.8))

    hub = BleDirectHub()
    try:
        log(f">>> BLE: scanning {scan_timeout:.0f}s for LVS-* advertisers…")
        ids = await hub.discover_and_connect(
            timeout=scan_timeout,
            name_prefix="LVS-",
            enrich_uart=True,
        )
        if not ids:
            log(
                ">>> BLE: no LVS-* devices found "
                "(disconnect Lovense app from toys, bring them close).",
            )
            return 0

        log(f">>> BLE: connected {len(ids)} toy(s): {', '.join(ids)}")

        gt = await hub.get_toys()
        assert gt.data is not None
        names = await hub.get_toys_name()
        log(
            f">>> BLE: get_toys / get_toys_name OK "
            f"({len(gt.data.toys)} row(s), names={names.data!r})",
        )

        await _try(
            "group Vibrate (all toys)",
            hub.function_request({Actions.VIBRATE: 5}, time=step_sec, toy_id=None),
            log,
        )
        await asyncio.sleep(inter_step)
        await asyncio.sleep(inter_step)

        for toy_row in gt.data.toys:
            tid = toy_row.id
            td = _toy_dict_for_features(toy_row)
            feats = features_for_toy(td)
            log(f">>> BLE: toy {tid!r} — features: {feats}")
            dual_vibrate_pair = "Vibrate1" in feats and "Vibrate2" in feats
            for fname in feats:
                act = _action_for_feature(fname)
                if act is None:
                    continue
                if dual_vibrate_pair and fname in ("Vibrate1", "Vibrate2"):
                    continue
                lvl = _level_for_feature(fname)
                await _try(
                    f"{tid}: {fname} @ {lvl} for {step_sec:.1f}s",
                    hub.function_request({act: lvl}, time=step_sec, toy_id=tid),
                    log,
                )
                await asyncio.sleep(inter_step)
                await asyncio.sleep(inter_step)

            if dual_vibrate_pair:
                lvl_v = _level_for_feature("Vibrate1")
                log(
                    f">>> BLE: toy {tid!r} — dual Vibrate1/Vibrate2 order probe "
                    f"(@ {lvl_v} each step; compare ok vs silence for 1st vs 2nd call)",
                )
                for forward in (True, False):
                    if not forward:
                        log(
                            f">>> BLE: toy {tid!r} — dual probe: {dual_probe_pass_break:.2f}s "
                            "pause before reversed pass (host/firmware recovery)",
                        )
                        await asyncio.sleep(dual_probe_pass_break)
                    order = ("Vibrate1", "Vibrate2") if forward else ("Vibrate2", "Vibrate1")
                    direction = "V1→V2" if forward else "V2→V1"
                    for fname in order:
                        if forward and fname == "Vibrate2":
                            log(
                                f">>> BLE: toy {tid!r} — dual probe: "
                                f"{dual_probe_peer_pad:.2f}s pause before [{direction}] Vibrate2",
                            )
                            await asyncio.sleep(dual_probe_peer_pad)
                        if not forward and fname == "Vibrate1":
                            log(
                                f">>> BLE: toy {tid!r} — dual probe: "
                                f"{dual_probe_peer_pad:.2f}s pause before [{direction}] Vibrate1",
                            )
                            await asyncio.sleep(dual_probe_peer_pad)
                            if dual_probe_last_v1_extra > 0:
                                log(
                                    f">>> BLE: toy {tid!r} — dual probe: "
                                    f"{dual_probe_last_v1_extra:.2f}s extra pause before "
                                    "final Vibrate1",
                                )
                                await asyncio.sleep(dual_probe_last_v1_extra)
                            if dual_probe_stop_before_last_v1:
                                await hub.stop(toy_id=tid)
                                if dual_probe_stop_before_last_v1_pause > 0:
                                    await asyncio.sleep(dual_probe_stop_before_last_v1_pause)
                                log(
                                    f">>> BLE: toy {tid!r} — dual probe: "
                                    "hub.stop() before final Vibrate1 "
                                    "(LOVENSE_BLE_DUAL_PROBE_STOP_BEFORE_LAST_V1)",
                                )
                        act = Actions(fname)
                        await _try(
                            (
                                f"{tid}: dual probe [{direction}] {fname} @ {lvl_v} "
                                f"for {step_sec:.1f}s"
                            ),
                            hub.function_request({act: lvl_v}, time=step_sec, toy_id=tid),
                            log,
                        )
                        await asyncio.sleep(dual_probe_gap)
                        await asyncio.sleep(dual_probe_gap)

                if dual_probe_tail_cooldown > 0:
                    await asyncio.sleep(dual_probe_tail_cooldown)
                    log(
                        f">>> BLE: toy {tid!r} — dual probe done; "
                        f"{dual_probe_tail_cooldown:.2f}s cooldown before preset",
                    )

            await _try(
                f"{tid}: preset pulse {pulse_preset_sec:.1f}s",
                hub.preset_request(Presets.PULSE, time=pulse_preset_sec, toy_id=tid),
                log,
            )
            await asyncio.sleep(inter_step)
            await asyncio.sleep(inter_step)

            await _try(
                f"{tid}: pattern [5,10,8] {pattern_sec:.1f}s",
                hub.pattern_request([5, 10, 8], interval=100, time=pattern_sec, toy_id=tid),
                log,
            )
            await asyncio.sleep(inter_step)
            await asyncio.sleep(inter_step)

            if "Depth" in feats or "Stroke" in feats:
                await _try(
                    f"{tid}: position 40",
                    hub.position_request(40, toy_id=tid),
                    log,
                )
                await asyncio.sleep(inter_step)
                await hub.stop(toy_id=tid)

        await _try(
            "set_vibration (each client)",
            asyncio.gather(*(hub.get_client(i).set_vibration(4) for i in ids)),
            log,
        )
        await asyncio.sleep(0.4)
        await hub.stop()

        log(">>> BLE: exercise finished, disconnecting…")
        return len(ids)
    finally:
        await hub.aclose()
