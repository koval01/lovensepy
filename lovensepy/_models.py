"""
Pydantic models for Lovense API requests and responses.
"""

import json
from typing import Any

from pydantic import BaseModel, Field, field_validator

__all__ = [
    "ToyInfo",
    "GetToysData",
    "GetToysResponse",
    "GetToyNameResponse",
    "CommandResponse",
    "FunctionPayload",
    "PatternPayload",
    "PatternV2Action",
    "PatternV2SetupPayload",
    "PatternV2PlayPayload",
    "PatternV2InitPlayPayload",
    "PatternV2StopPayload",
    "PresetPayload",
    "PositionPayload",
]


class ToyInfo(BaseModel):
    """Single toy info from GetToys response."""

    id: str
    name: str
    status: str | None = None
    version: str | None = None
    battery: int | None = None
    nickName: str | None = None
    shortFunctionNames: list[str] | None = None
    fullFunctionNames: list[str] | None = None
    toyType: str | None = None
    type: str | None = None

    model_config = {"extra": "allow"}


class GetToysData(BaseModel):
    """Normalized GetToys response data.

    Lovense devices sometimes respond with different shapes (dict/list/etc.);
    this model normalizes them into a list of typed `ToyInfo` objects.
    """

    toys: list[ToyInfo]

    model_config = {"extra": "allow"}


class GetToysResponse(BaseModel):
    """Response from GetToys command."""

    code: int = 200
    type: str = "OK"
    data: GetToysData | None = None

    @field_validator("data", mode="before")
    @classmethod
    def _parse_data(cls, v: Any) -> Any:
        if v is None:
            return None

        # `LANClient` already recursively parses JSON strings, but accept raw strings too.
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except json.JSONDecodeError:
                return None

        # Response shapes observed in the wild:
        # - {"toys": {<id>: <toyDict>, ...}}
        # - {<id>: <toyDict>, ...}
        # - [{"id": "...", ...}, ...]
        extras: dict[str, Any] = {}
        toys_raw: Any = v

        if isinstance(v, dict) and "toys" in v:
            extras = {k: val for k, val in v.items() if k != "toys"}
            toys_raw = v.get("toys")
        elif isinstance(v, dict):
            toys_raw = v

        toys: list[ToyInfo] = []

        if isinstance(toys_raw, dict):
            for tid, t in toys_raw.items():
                if not isinstance(t, dict):
                    continue
                toy_dict = dict(t)
                toy_dict.setdefault("id", toy_dict.get("id") or str(tid))
                toy_dict["id"] = str(toy_dict["id"])
                if not toy_dict.get("name") and toy_dict.get("nickName"):
                    toy_dict["name"] = toy_dict["nickName"]
                toy_dict.setdefault("name", toy_dict["id"])
                toys.append(ToyInfo.model_validate(toy_dict))
        elif isinstance(toys_raw, list):
            for t in toys_raw:
                if not isinstance(t, dict):
                    continue
                if t.get("id") is None:
                    continue
                toy_dict = dict(t)
                toy_dict["id"] = str(toy_dict["id"])
                if not toy_dict.get("name") and toy_dict.get("nickName"):
                    toy_dict["name"] = toy_dict["nickName"]
                toy_dict.setdefault("name", toy_dict["id"])
                toys.append(ToyInfo.model_validate(toy_dict))

        if not toys and isinstance(v, dict) and "toys" in v and isinstance(v["toys"], dict):
            # Defensive fallback for nested toys dicts that might have different keys.
            return {"toys": [], **extras}

        return {"toys": toys, **extras}


class GetToyNameResponse(BaseModel):
    """Response from GetToyName command."""

    code: int = 200
    type: str = "OK"
    data: list[str] | None = None


class CommandResponse(BaseModel):
    """Generic command response."""

    code: int = 200
    type: str = "OK"
    result: bool | None = None
    message: str | None = None
    data: dict[str, Any] | None = None

    model_config = {"extra": "allow"}


# --- Request payloads (for building commands) ---


class FunctionPayload(BaseModel):
    """Payload for Function command."""

    command: str = "Function"
    action: str
    timeSec: float = 0
    apiVer: int = 1
    toy: str | list[str] | None = None
    loopRunningSec: float | None = None
    loopPauseSec: float | None = None
    stopPrevious: int | None = None


class PatternPayload(BaseModel):
    """Payload for Pattern command."""

    command: str = "Pattern"
    rule: str
    strength: str
    timeSec: float = 0
    apiVer: int = 2
    toy: str | list[str] | None = None


class PatternV2Action(BaseModel):
    """Single action for PatternV2 (ts, pos)."""

    ts: int  # timestamp in ms
    pos: int = Field(..., ge=0, le=100)  # position 0-100


class PatternV2SetupPayload(BaseModel):
    """Payload for PatternV2 Setup."""

    command: str = "PatternV2"
    type: str = "Setup"
    actions: list[PatternV2Action]
    apiVer: int = 1


class PatternV2PlayPayload(BaseModel):
    """Payload for PatternV2 Play."""

    command: str = "PatternV2"
    type: str = "Play"
    apiVer: int = 1
    toy: str | list[str] | None = None
    startTime: int | None = None
    offsetTime: int | None = None
    timeMs: float | None = None


class PatternV2InitPlayPayload(BaseModel):
    """Payload for PatternV2 InitPlay (setup + play in one)."""

    command: str = "PatternV2"
    type: str = "InitPlay"
    actions: list[PatternV2Action]
    apiVer: int = 1
    toy: str | list[str] | None = None
    startTime: int | None = None
    offsetTime: int | None = None
    stopPrevious: int = 0


class PatternV2StopPayload(BaseModel):
    """Payload for PatternV2 Stop."""

    command: str = "PatternV2"
    type: str = "Stop"
    apiVer: int = 1
    toy: str | list[str] | None = None


class PresetPayload(BaseModel):
    """Payload for Preset command."""

    command: str = "Preset"
    name: str
    timeSec: float = 0
    apiVer: int = 1
    toy: str | list[str] | None = None


class PositionPayload(BaseModel):
    """Payload for Position command (Solace Pro). Value 0-100 as string."""

    command: str = "Position"
    value: str  # "0" to "100"
    apiVer: int = 1
    toy: str | list[str] | None = None
