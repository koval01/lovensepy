"""
Lovense BLE UART vocabulary (``…;`` command strings and stop bursts).

Per–toy-type **feature name** defaults live in :mod:`lovensepy.toy_type_defaults`;
this module maps those names to UART payloads. Command strings use ASCII ``…;``
framing on many Lovense BLE peripherals. This is **not** a published stable
contract; tables are maintained to match :mod:`lovensepy._constants` and field use.

TX characteristic discovery stays in :mod:`lovensepy.ble_direct.client` (flex
``????0002-…-4bd4-bbd5-a6920e4c5653``). This module does **not** depend on bleak.
"""

from __future__ import annotations

from typing import Final

from lovensepy.toy_type_defaults import default_features_for_toy_type

# Canonical feature names align with :data:`lovensepy._constants.FUNCTION_RANGES`.
_FEATURE_STOP_UART: dict[str, tuple[str, ...]] = {
    "Vibrate": ("Vibrate:0;",),
    "Vibrate1": ("Vibrate1:0;",),
    "Vibrate2": ("Vibrate2:0;",),
    "Vibrate3": ("Vibrate3:0;",),
    "Rotate": ("Rotate:0;",),
    "Pump": ("Air:Level:0;",),
    "Thrusting": ("Thrusting:0;",),
    "Fingering": ("Finger:0;",),
    "Suction": ("Suction:0;", "suck:0;"),
    "Depth": ("Depth:0;",),
    "Oscillate": ("Slap:0;", "Oscillate:0;"),
    "Position": ("Position:0;", "FSetSite:0;"),
    "Bumping": ("Bumping:0;",),
}

# Ordered blast for link-loss / “stop everything we know” (harmless if ignored).
DEFAULT_FULL_STOP_COMMANDS: Final[tuple[str, ...]] = (
    "Vibrate:0;",
    "Vibrate1:0;",
    "Vibrate2:0;",
    "Vibrate3:0;",
    "Rotate:0;",
    "Rotate:False:0;",
    "Air:Level:0;",
    "Thrusting:0;",
    "Finger:0;",
    "Suction:0;",
    "suck:0;",
    "Depth:0;",
    "Slap:0;",
    "Oscillate:0;",
    "Position:0;",
    "FSetSite:0;",
    "Bumping:0;",
    "Squirt:0;",
)


def ble_uart_features_for_toy_type(toy_type: str | None) -> tuple[str, ...]:
    """BLE-stable alias for :func:`~lovensepy.toy_type_defaults.default_features_for_toy_type`."""
    return default_features_for_toy_type(toy_type)


def ble_stop_command_strings_for_features(features: tuple[str, ...] | list[str]) -> list[str]:
    """UART stop strings for the given feature set (deduped, stable order)."""
    seen: set[str] = set()
    out: list[str] = []
    for feat in features:
        for cmd in _FEATURE_STOP_UART.get(feat, ()):
            if cmd not in seen:
                seen.add(cmd)
                out.append(cmd)
    return out


def ble_stop_command_strings_for_toy_type(toy_type: str | None) -> list[str]:
    """Stop strings implied by :func:`ble_uart_features_for_toy_type`."""
    return ble_stop_command_strings_for_features(ble_uart_features_for_toy_type(toy_type))


def default_full_stop_payloads() -> tuple[bytes, ...]:
    """UTF-8 payloads for a best-effort “mute all channels” burst."""
    return tuple(s.encode("utf-8") for s in DEFAULT_FULL_STOP_COMMANDS)


__all__ = [
    "DEFAULT_FULL_STOP_COMMANDS",
    "ble_stop_command_strings_for_features",
    "ble_stop_command_strings_for_toy_type",
    "ble_uart_features_for_toy_type",
    "default_full_stop_payloads",
]
