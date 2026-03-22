"""
Default motor feature names when GetToys omits ``fullFunctionNames`` / ``shortFunctionNames``.

This is **not** BLE-specific: :func:`features_for_toy` uses it as a LAN-side fallback.
Direct BLE builds UART stop strings from the same names via
:mod:`lovensepy.ble_direct.uart_catalog` so command hints stay aligned with API vocabulary.
"""

from __future__ import annotations

__all__ = ["default_features_for_toy_type"]

# Lowercase ``toyType`` / API-style names and common aliases.
_FEATURES_BY_TOY_TYPE: dict[str, tuple[str, ...]] = {
    # Dual vibrate
    "edge": ("Vibrate1", "Vibrate2"),
    "diamo": ("Vibrate1", "Vibrate2"),
    "dolce": ("Vibrate1", "Vibrate2"),
    "gemini": ("Vibrate1", "Vibrate2"),
    # Nora / Max families (vibrate + rotate + pump)
    "nora": ("Vibrate", "Rotate"),
    "max": ("Vibrate", "Pump"),
    # Gush: LAN GetToys exposes a single vibrate function; do not infer a second motor.
    "gush": ("Vibrate",),
    # Osci: oscillate/slap channel alongside vibrate
    "osci": ("Vibrate", "Oscillate"),
    # Strokers / suction-masturbator class
    "vulse": ("Vibrate", "Suction"),
    "calor": ("Vibrate", "Oscillate"),
    "flexer": ("Vibrate", "Oscillate"),
    # Thrusting hardware with auxiliary vibrate
    "gravity": ("Thrusting", "Vibrate"),
    "solace": ("Vibrate", "Thrusting", "Depth"),
    "solacepro": ("Vibrate", "Thrusting", "Depth"),
    "solace pro": ("Vibrate", "Thrusting", "Depth"),
    "mini": ("Thrusting",),
    "xmachine": ("Thrusting",),
    # Lapis: main + third vibrate channel
    "lapis": ("Vibrate", "Vibrate3"),
    # Default single-motor toys (explicit for discoverability)
    "lush": ("Vibrate",),
    "hush": ("Vibrate",),
    "domi": ("Vibrate",),
    "ferri": ("Vibrate",),
    "ambi": ("Vibrate",),
    "ridge": ("Vibrate",),
    "mission": ("Vibrate",),
    "hyphy": ("Vibrate",),
    "exomoon": ("Vibrate",),
    "tenera": ("Vibrate",),
    "spinel": ("Vibrate",),
}


def default_features_for_toy_type(toy_type: str | None) -> tuple[str, ...]:
    """Return default feature names for a Lovense ``toyType`` / app ``type`` string.

    Used when the LAN API does not list functions. Unknown or empty types fall back
    to ``("Vibrate",)``. Matching is case-insensitive; spaces are stripped for
    dictionary lookup, with a few substring checks for compound names.
    """
    raw = str(toy_type or "").strip().lower()
    if not raw:
        return ("Vibrate",)
    compact = raw.replace(" ", "")
    if compact in _FEATURES_BY_TOY_TYPE:
        return _FEATURES_BY_TOY_TYPE[compact]
    if raw in _FEATURES_BY_TOY_TYPE:
        return _FEATURES_BY_TOY_TYPE[raw]
    if "solace" in compact:
        return _FEATURES_BY_TOY_TYPE["solace"]
    if "gemini" in compact:
        return _FEATURES_BY_TOY_TYPE["gemini"]
    if "dolce" in compact or "quke" in compact:
        return _FEATURES_BY_TOY_TYPE["dolce"]
    return ("Vibrate",)
