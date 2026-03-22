"""
Lovense API constants: actions, presets, error codes, feature ranges.
"""

from enum import StrEnum

__all__ = [
    "Actions",
    "Presets",
    "PRESET_BLE_PAT_INDEX",
    "ERROR_CODES",
    "FUNCTION_RANGES",
]


class Actions(StrEnum):
    """Lovense function actions for toy control."""

    VIBRATE = "Vibrate"
    VIBRATE1 = "Vibrate1"
    VIBRATE2 = "Vibrate2"
    VIBRATE3 = "Vibrate3"
    ROTATE = "Rotate"
    PUMP = "Pump"
    THRUSTING = "Thrusting"
    FINGERING = "Fingering"
    SUCTION = "Suction"
    DEPTH = "Depth"
    STROKE = "Stroke"
    OSCILLATE = "Oscillate"
    ALL = "All"
    STOP = "Stop"


class Presets(StrEnum):
    """Built-in preset patterns in Lovense Remote app."""

    PULSE = "pulse"
    WAVE = "wave"
    FIREWORKS = "fireworks"
    EARTHQUAKE = "earthquake"


# UART ``Pat:{n};`` indices for the four Remote presets (Lovense Connect sends ``Pat`` with an
# integer, not ``Pat:pulse``). Some developer docs call this slot ``Preset:{n};`` — firmware
# varies; indices may differ by toy generation.
PRESET_BLE_PAT_INDEX: dict[str, int] = {
    Presets.PULSE.value: 1,
    Presets.WAVE.value: 2,
    Presets.FIREWORKS.value: 3,
    Presets.EARTHQUAKE.value: 4,
}


# Max levels per feature type (Lovense API convention)
FUNCTION_RANGES: dict[str, tuple[int, int]] = {
    "Vibrate": (0, 20),
    "Vibrate1": (0, 20),
    "Vibrate2": (0, 20),
    "Vibrate3": (0, 20),
    "Rotate": (0, 20),
    "Pump": (0, 3),
    "Thrusting": (0, 20),
    "Fingering": (0, 20),
    "Suction": (0, 20),
    "Depth": (0, 3),
    "Stroke": (0, 100),
    "Oscillate": (0, 20),
    "All": (0, 20),
}

# Standard API error codes (LAN / command responses)
ERROR_CODES: dict[int, str] = {
    200: "OK",
    400: "Invalid Command",
    401: "Toy Not Found",
    402: "Toy Not Connected",
    403: "Toy Doesn't Support This Command",
    404: "Invalid Parameter",
    500: "HTTP server not started or disabled",
    506: "Server Error. Restart Lovense Connect.",
}

# Server API error codes
SERVER_ERROR_CODES: dict[int, str] = {
    200: "Success",
    400: "Invalid command",
    404: "Invalid Parameter",
    501: "Invalid token",
    502: "You do not have permission to use this API",
    503: "Invalid User ID",
    507: "Lovense APP is offline",
}
