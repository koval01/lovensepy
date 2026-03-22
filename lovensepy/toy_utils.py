"""
Toy utilities: feature detection, stop actions.

Use with toy dict from GetToys / basicapi_update_device_info_tc.
"""

from typing import Any

from lovensepy.toy_type_defaults import default_features_for_toy_type

__all__ = ["features_for_toy", "stop_actions"]

SHORT_TO_FULL: dict[str, str] = {
    "v": "Vibrate",
    "v1": "Vibrate1",
    "v2": "Vibrate2",
    "r": "Rotate",
    "p": "Pump",
    "t": "Thrusting",
    "f": "Fingering",
    "s": "Suction",
    "d": "Depth",
    "st": "Stroke",
    "o": "Oscillate",
}
KNOWN_FEATURES = frozenset(SHORT_TO_FULL.values())


def _normalize_feature_name(name: str) -> str:
    """Normalize API feature tokens into canonical feature names.

    Lovense API sometimes returns short tokens like 'v'/'v1'/'r'. For longer
    names (e.g. 'Vibrate', 'Vibrate1') we keep them as-is.
    """
    n = name.strip()
    if len(n) <= 3:
        return SHORT_TO_FULL.get(n.lower(), n)
    return n


def features_for_toy(toy: dict[str, Any]) -> list[str]:
    """
    Get ordered list of features (Vibrate1, Vibrate2, Rotate, etc.) for toy.

    Uses API shortFunctionNames/fullFunctionNames when available; otherwise
    :func:`lovensepy.toy_type_defaults.default_features_for_toy_type` by ``toyType``.
    Edge/Diamo: API often returns only 'v'/'Vibrate' — override to Vibrate1, Vibrate2.
    """
    if toy is None:
        raise TypeError("toy must not be None")
    toy_type = (toy.get("toyType") or toy.get("name") or "").lower()
    full = toy.get("fullFunctionNames") or []
    short = toy.get("shortFunctionNames") or []
    seen: set[str] = set()
    result: list[str] = []
    # Prefer explicit API function names, but normalize short tokens when
    # Lovense returns only abbreviations.
    for name in full + short:
        if not isinstance(name, str):
            continue
        mapped = _normalize_feature_name(name)
        if mapped in KNOWN_FEATURES and mapped not in seen:
            seen.add(mapped)
            result.append(mapped)
    if result:
        # Edge/Diamo API quirk: sometimes returns only 'v'/'Vibrate' even
        # though the device has two vibrate motors.
        if ("edge" in toy_type or "diamo" in toy_type) and result == ["Vibrate"]:
            return ["Vibrate1", "Vibrate2"]
        return result
    return list(default_features_for_toy_type(toy_type))


def stop_actions(toy: dict[str, Any]) -> dict[str, int]:
    """Build actions dict to stop all motors: {Vibrate1: 0, Vibrate2: 0, ...}."""
    feats = features_for_toy(toy)
    return {f: 0 for f in feats}
