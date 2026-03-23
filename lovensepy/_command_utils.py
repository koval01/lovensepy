"""
Shared command-shaping helpers used by LAN/Server/BLE clients.
"""

from __future__ import annotations

import json
from typing import Any

from ._constants import FUNCTION_RANGES, Actions

_PATTERN_ACTION_MAP: dict[str, str] = {
    "vibrate": "v",
    "vibrate1": "v",
    "vibrate2": "v",
    "vibrate3": "v",
    "rotate": "r",
    "pump": "p",
    "thrusting": "t",
    "fingering": "f",
    "suction": "s",
    "depth": "d",
    "oscillate": "o",
    "stroke": "st",
}

_VALID_PATTERN_LETTERS = frozenset(_PATTERN_ACTION_MAP.values())


def parse_nested_json(data: str | dict | list) -> dict[str, Any] | list | str:
    """Recursively parse nested JSON strings into dict/list structures."""
    if isinstance(data, str):
        try:
            return json.loads(data)
        except ValueError:
            return data
    if isinstance(data, dict):
        return {k: parse_nested_json(v) for k, v in data.items()}
    if isinstance(data, list):
        return [parse_nested_json(item) for item in data]
    return data


def clamp_nonzero_time_sec(value: Any) -> float:
    """Clamp non-zero ``timeSec`` to Lovense API bounds."""
    return max(1.0, min(float(value), 6000.0))


def clamp_time_sec_in_payload(command_data: dict[str, Any]) -> dict[str, Any]:
    """Copy payload and clamp ``timeSec`` only when non-zero."""
    cmd = dict(command_data)
    ts = cmd.get("timeSec")
    if ts is not None and ts != 0:
        cmd["timeSec"] = clamp_nonzero_time_sec(ts)
    return cmd


def action_to_pattern_letter(action: str | Actions) -> str:
    """Map action to pattern-rule token (v,r,p,t,f,s,d,o,st)."""
    if isinstance(action, Actions):
        action = str(action)
    normalized = str(action).strip().lower()
    return _PATTERN_ACTION_MAP.get(normalized, normalized[0] if normalized else "")


def actions_to_rule_letters(actions: list[str | Actions] | None) -> str:
    """Convert actions list to unique comma-separated pattern letters."""
    if not actions or Actions.ALL in actions:
        return ""
    letters: list[str] = []
    for action in actions:
        letter = action_to_pattern_letter(action)
        if letter and letter in _VALID_PATTERN_LETTERS and letter not in letters:
            letters.append(letter)
    return ",".join(letters) if letters else ""


def clamp_function_actions(
    actions: dict[str | Actions, int | float],
) -> dict[str, int | float]:
    """Clamp function action values to API ranges."""
    result: dict[str, int | float] = {}
    for action, value in actions.items():
        key = str(action)
        if key in FUNCTION_RANGES:
            lo, hi = FUNCTION_RANGES[key]
            result[key] = int(max(lo, min(hi, value)))
        else:
            result[key] = value
    return result
