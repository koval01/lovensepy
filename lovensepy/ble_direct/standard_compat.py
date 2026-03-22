"""
Map Standard API (LAN) semantics to Lovense UART strings for :class:`BleDirectClient`.

This module is internal; callers use :class:`~lovensepy.ble_direct.client.BleDirectClient`
methods mirroring :class:`~lovensepy.standard.async_lan.AsyncLANClient`.
"""

from __future__ import annotations

import re

from .._constants import FUNCTION_RANGES, Actions
from .uart_catalog import ble_uart_features_for_toy_type

__all__ = [
    "ble_clamp_actions",
    "ble_actions_to_uart_strings",
    "parse_pattern_rule_and_strength",
]


def ble_clamp_actions(actions: dict[str | Actions, int | float]) -> dict[str, int | float]:
    """Clamp action values to API ranges (same rules as LAN)."""
    result: dict[str, int | float] = {}
    for action, value in actions.items():
        key = str(action)
        if key in FUNCTION_RANGES:
            lo, hi = FUNCTION_RANGES[key]
            result[key] = int(max(lo, min(hi, float(value))))
        else:
            result[key] = value
    return result


def _one_uart_for_feature(name: str, n: int) -> str:
    """Single UART line for a feature key (names aligned with ``FUNCTION_RANGES``)."""
    match name:
        case "Vibrate":
            return f"Vibrate:{n};"
        case "Vibrate1":
            return f"Vibrate1:{n};"
        case "Vibrate2":
            return f"Vibrate2:{n};"
        case "Vibrate3":
            return f"Vibrate3:{n};"
        case "Rotate":
            return f"Rotate:{n};"
        case "Pump":
            return f"Air:Level:{n};"
        case "Thrusting":
            return f"Thrusting:{n};"
        case "Fingering":
            return f"Finger:{n};"
        case "Suction":
            return f"Suction:{n};"
        case "Depth":
            return f"Depth:{n};"
        case "Oscillate":
            return f"Slap:{n};"
        case _:
            raise ValueError(f"Unsupported feature for BLE UART mapping: {name!r}")


def ble_actions_to_uart_strings(
    clamped: dict[str, int | float],
    *,
    toy_type_hint: str | None,
) -> list[str]:
    """Turn a clamped Function action dict into ordered UART command strings."""
    if str(Actions.STOP) in clamped:
        raise ValueError("Stop must be handled before mapping to UART")

    feats_hint = ble_uart_features_for_toy_type(toy_type_hint)
    dual_vibrate = "Vibrate1" in feats_hint and "Vibrate2" in feats_hint

    out: list[str] = []

    # Both channels: usually two GATT writes (one UART line each). Some firmware / BLE stacks
    # effectively apply only one write per “tick”; a companion ``VibrateX:0;`` line can then
    # prevent the non-zero channel from taking effect (raw ``Vibrate2:n;`` alone often works).
    # So: full stop (0,0) and both motors non-zero → two lines; if exactly one channel is
    # non-zero → **only that channel’s line** in this list. :class:`~lovensepy.ble_direct.client.BleDirectClient`
    # may still send the peer ``…:0;`` in a **separate** preceding GATT write (see
    # ``dual_single_channel_prime_peer_zero``).
    if dual_vibrate and "Vibrate1" in clamped and "Vibrate2" in clamped:
        v1 = int(clamped["Vibrate1"])
        v2 = int(clamped["Vibrate2"])
        if v1 == 0 and v2 == 0:
            out.append(_one_uart_for_feature("Vibrate1", 0))
            out.append(_one_uart_for_feature("Vibrate2", 0))
            return out
        if v1 != 0 and v2 != 0:
            out.append(_one_uart_for_feature("Vibrate1", v1))
            out.append(_one_uart_for_feature("Vibrate2", v2))
            return out
        if v1 != 0:
            out.append(_one_uart_for_feature("Vibrate1", v1))
        else:
            out.append(_one_uart_for_feature("Vibrate2", v2))
        return out

    for key, raw in clamped.items():
        name = str(key)
        n = int(raw)

        if name == "All":
            for feat in feats_hint:
                lo, hi = FUNCTION_RANGES.get(feat, (0, 20))
                nv = int(max(lo, min(hi, n)))
                out.append(_one_uart_for_feature(feat, nv))
            continue

        if name == "Stroke":
            raise ValueError(
                "Stroke is not mapped to UART in this build (device-specific SetStroke); "
                "use LAN / Remote or a raw :meth:`~lovensepy.ble_direct.client.BleDirectClient.send_uart_command`."
            )

        # Callers without :meth:`~lovensepy.ble_direct.client.BleDirectClient._coerce_dual_vibrate_actions`
        # get a single UART line (no sibling zero) — same single-write rationale as above.
        if dual_vibrate:
            if name == "Vibrate1" and "Vibrate2" not in clamped:
                out.append(_one_uart_for_feature("Vibrate1", n))
                continue
            if name == "Vibrate2" and "Vibrate1" not in clamped:
                out.append(_one_uart_for_feature("Vibrate2", n))
                continue

        out.append(_one_uart_for_feature(name, n))

    return out


_RE_RULE_S = re.compile(r"S:(\d+)#")
_RE_RULE_F = re.compile(r"F:([^;#]*)")


def parse_pattern_rule_and_strength(
    rule: str,
    strength: str,
) -> tuple[list[int], int, str]:
    """Parse Pattern ``rule`` + ``strength`` like the LAN API (single-channel list)."""
    m = _RE_RULE_S.search(rule)
    interval = int(m.group(1)) if m else 100
    interval = min(max(interval, 100), 1000)

    m2 = _RE_RULE_F.search(rule)
    f_part = (m2.group(1) or "").strip() if m2 else ""

    parts = [p.strip() for p in strength.split(";") if p.strip()]
    steps: list[int] = []
    for p in parts[:50]:
        try:
            v = int(float(p))
        except ValueError:
            continue
        steps.append(min(max(0, v), 20))
    return steps, interval, f_part


def pattern_rule_first_letter_to_feature(rule_letters: str) -> str:
    """Pick one motor feature from F: letters (``v`` → Vibrate, …)."""
    s = (rule_letters or "").strip().lower().lstrip(",").split(",")[0].strip()
    mapping = {
        "v": "Vibrate",
        "r": "Rotate",
        "p": "Pump",
        "t": "Thrusting",
        "f": "Fingering",
        "s": "Suction",
        "d": "Depth",
        "o": "Oscillate",
        "st": "Stroke",
    }
    if not s:
        return "Vibrate"
    feat = mapping.get(s[:2] if s.startswith("st") else s[0])
    if feat == "Stroke":
        raise ValueError("Pattern step for Stroke is not supported over BLE UART mapping")
    return feat or "Vibrate"
