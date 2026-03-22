"""
Parsers for ASCII lines returned on the Lovense BLE **RX** characteristic
(vendor UART-style framing, ``…;``).

The toy does **not** usually describe “this handle is vibrate” in plain text:
``DeviceType;`` returns a compact **model / firmware / BT** line; motor roles
follow from that model (see :mod:`lovensepy.ble_direct.uart_catalog`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "DeviceTypeFields",
    "parse_battery_percent",
    "parse_device_type_fields",
]


@dataclass(frozen=True)
class DeviceTypeFields:
    """Fields from a ``DeviceType;`` reply line (e.g. ``C:11:0082059AD3BD;``)."""

    model_letter: str
    firmware: str
    bt_addr_hex: str
    raw: str


def parse_device_type_fields(line: str) -> DeviceTypeFields:
    """Parse ``DeviceType`` response body (with or without trailing ``;``)."""
    s = line.strip().rstrip(";").strip()
    parts = s.split(":")
    if len(parts) != 3:
        raise ValueError(f"Unexpected DeviceType reply: {line!r}")
    return DeviceTypeFields(
        model_letter=parts[0].strip(),
        firmware=parts[1].strip(),
        bt_addr_hex=parts[2].strip(),
        raw=line.strip(),
    )


def parse_battery_percent(line: str) -> int:
    """Parse ``Battery;`` reply.

    Common forms: ``85;``, ``85``. Some firmware prefixes a short tag before the
    value (e.g. ``s92;`` — often interpreted as a *status* byte plus percent) or
    uses ``Name:NN``. RX lines are split on ``;``; if chunks merge oddly, you may
    still see a short non-numeric prefix before the digits.
    """
    s = line.strip().rstrip(";").strip()
    if not s:
        raise ValueError(f"Unexpected Battery reply: {line!r}")

    def _clamp_pct(n: int) -> int:
        return max(0, min(100, n))

    if re.fullmatch(r"\d+", s):
        return _clamp_pct(int(s))

    # Tag + digits (e.g. "s92" — short status/state prefix + percent)
    m = re.fullmatch(r"[A-Za-z]{1,12}(\d{1,3})", s)
    if m:
        return _clamp_pct(int(m.group(1)))

    # "Bat:92", "S: 92", etc.
    m = re.fullmatch(r"[A-Za-z]{1,12}[:=]\s*(\d{1,3})\s*", s)
    if m:
        return _clamp_pct(int(m.group(1)))

    # Any non-digit prefix + trailing percent (handles non-ASCII "s", odd tags, fragments)
    m = re.search(r"(\d{1,3})\s*$", s)
    if m:
        prefix = s[: m.start()]
        if prefix.strip() == "" or not any(ch.isdigit() for ch in prefix):
            return _clamp_pct(int(m.group(1)))

    raise ValueError(f"Unexpected Battery reply: {line!r}")
