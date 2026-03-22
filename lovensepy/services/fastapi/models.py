"""Pydantic request/response models for the FastAPI service."""

from __future__ import annotations

import json
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator

from lovensepy import Actions, Presets
from lovensepy._constants import FUNCTION_RANGES


class PatternTemplate(StrEnum):
    SOFT = "soft"
    WAVE = "wave"
    STAIRS = "stairs"


PATTERN_TEMPLATES: dict[PatternTemplate, list[int]] = {
    PatternTemplate.SOFT: [3, 5, 7, 5],
    PatternTemplate.WAVE: [2, 6, 10, 14, 10, 6],
    PatternTemplate.STAIRS: [3, 6, 9, 12, 15, 18],
}


def pattern_session_signature(
    pattern: list[int],
    *,
    interval: int,
    actions: list[Actions] | None,
    template: PatternTemplate | None,
) -> str:
    act = ",".join(sorted(str(a) for a in (actions or [])))
    if template is not None:
        return f"t:{template}|i:{interval}|a:{act}"
    return f"p:{json.dumps(pattern, separators=(',', ':'))}|i:{interval}|a:{act}"


class FunctionCommand(BaseModel):
    actions: dict[Actions, float] = Field(
        ...,
        description="Per-function levels, e.g. {'Vibrate1': 10}. Each key is scheduled separately.",
    )
    time: float = Field(
        default=0,
        ge=0,
        description="Seconds to hold each listed function (0 = until stopped via API).",
    )
    loop_on_time: float | None = Field(default=None, ge=1)
    loop_off_time: float | None = Field(default=None, ge=1)
    toy_id: str = Field(..., min_length=1, description="Target toy id.")
    stop_previous: bool = Field(
        default=False,
        description="If true, cancel every active slot on this toy before applying this command.",
    )

    @field_validator("actions")
    @classmethod
    def validate_actions(cls, value: dict[Actions, float]) -> dict[Actions, float]:
        if not value:
            raise ValueError("actions must not be empty")
        for action, level in value.items():
            min_level, max_level = FUNCTION_RANGES.get(str(action), (0, 20))
            if level < min_level or level > max_level:
                raise ValueError(
                    f"Invalid level for {action}: {level}. Allowed range: {min_level}..{max_level}"
                )
        return value


class PresetCommand(BaseModel):
    name: Presets = Field(..., description="Preset name from Lovense app.")
    time: float = Field(
        default=0,
        ge=0,
        description=(
            "Sent to Lovense as-is. If 0, /tasks tracker still expires after session_max_sec."
        ),
    )
    toy_id: str | None = Field(default=None, description="Target toy id.")


class PatternCommand(BaseModel):
    pattern: list[int] | None = Field(
        default=None, description="Strength sequence values in range 0..20."
    )
    template: PatternTemplate | None = Field(
        default=None,
        description="Predefined pattern template.",
    )
    actions: list[Actions] | None = Field(
        default=None,
        description="Optional action list, e.g. ['Vibrate'] or ['All'].",
    )
    interval: int = Field(default=100, ge=100, le=1000)
    time: float = Field(
        default=0,
        ge=0,
        description=(
            "Sent to Lovense as-is. If 0, server /tasks tracker expires after session_max_sec."
        ),
    )
    toy_id: str | None = Field(default=None, description="Target toy id.")

    @model_validator(mode="after")
    def validate_pattern(self) -> PatternCommand:
        if self.pattern is None and self.template is None:
            raise ValueError("Provide either 'pattern' or 'template'.")
        if self.pattern is not None and self.template is not None:
            raise ValueError("Use only one: 'pattern' or 'template'.")
        if self.pattern is not None:
            pat = self.pattern
            if not pat:
                raise ValueError("pattern must not be empty")
            if len(pat) > 50:
                raise ValueError("pattern must have at most 50 values")
            for value in list(pat):
                if value < 0 or value > 20:
                    raise ValueError("pattern values must be within 0..20")
        return self


class StopToyBody(BaseModel):
    toy_id: str = Field(..., min_length=1)


def _reject_stop_feature_all_or_stop(value: Actions) -> Actions:
    if value == Actions.ALL:
        raise ValueError("To stop every function on a toy, use POST /command/stop/toy.")
    if value == Actions.STOP:
        raise ValueError("Use /command/stop/toy or /command/stop/all.")
    return value


class StopFeatureBody(BaseModel):
    toy_id: str = Field(..., min_length=1)
    feature: Actions = Field(..., description="Function / motor to zero out on the device.")

    @field_validator("feature")
    @classmethod
    def reject_all_alias(cls, value: Actions) -> Actions:
        return _reject_stop_feature_all_or_stop(value)


class StopToysBatchBody(BaseModel):
    toy_ids: list[str] = Field(
        ...,
        min_length=1,
        description="Stop each toy (device + local slots).",
    )


class StopFeatureBatchItem(BaseModel):
    toy_id: str = Field(..., min_length=1)
    feature: Actions = Field(...)

    @field_validator("feature")
    @classmethod
    def reject_all_alias(cls, value: Actions) -> Actions:
        return _reject_stop_feature_all_or_stop(value)


class StopFeaturesBatchBody(BaseModel):
    items: list[StopFeatureBatchItem] = Field(..., min_length=1)


class BleConnectBody(BaseModel):
    address: str = Field(..., min_length=1, description="BLE address from scan.")
    toy_id: str | None = Field(
        default=None,
        description="Stable id for API; if omitted, derived from address and name.",
    )
    name: str | None = Field(default=None, description="Advertised name (e.g. LVS-…).")
    toy_type: str | None = Field(
        default=None,
        description="Type slug for UART routing (often inferred from LVS- name).",
    )
    replace: bool = Field(
        default=False,
        description="Replace existing registration with same toy_id.",
    )
