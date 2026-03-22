"""Configuration for :mod:`lovensepy.services.fastapi` (LAN + BLE HTTP server)."""

from __future__ import annotations

import os
from typing import Any, Literal

from pydantic import BaseModel, Field

ServiceMode = Literal["lan", "ble"]


def _ble_scan_prefix_from_env() -> str | None:
    raw = os.environ.get("LOVENSE_BLE_SCAN_PREFIX")
    if raw is None:
        return "LVS-"
    s = raw.strip()
    return None if s == "" else s


class ServiceConfig(BaseModel):
    mode: ServiceMode = Field(
        default="lan",
        description="Transport: lan (Game Mode) or ble (direct BLE hub).",
    )
    lan_ip: str | None = Field(
        default=None,
        min_length=7,
        description="Game Mode host when mode=lan.",
    )
    lan_port: int = Field(default=20011, ge=1, le=65535)
    app_name: str = Field(default="lovensepy_service", min_length=1)
    session_max_sec: float = Field(
        default=60.0,
        ge=1.0,
        le=86400.0,
        description="Preset/pattern time=0: server /tasks tracker length in seconds.",
    )
    allowed_toy_ids: list[str] = Field(
        default_factory=list,
        description="Optional extra toy ids for OpenAPI enum (LOVENSE_TOY_IDS).",
    )
    ble_scan_timeout: float = Field(default=8.0, ge=0.5, le=120.0)
    ble_scan_name_prefix: str | None = Field(default="LVS-")
    ble_advertisement_monitor: bool = Field(
        default=False,
        description="If true (BLE mode), run optional background RSSI/advertisement callbacks.",
    )
    ble_monitor_interval_sec: float = Field(
        default=2.0,
        ge=0.5,
        le=60.0,
        description="When advertisement monitor is on, periodic passive scan interval.",
    )
    ble_preset_uart_keyword: str = Field(
        default="Preset",
        description=(
            "BLE mode: UART prefix for built-in presets: Preset (public UART docs) or Pat "
            "(Lovense Connect). Override with env LOVENSEPY_BLE_PRESET_UART."
        ),
    )
    ble_preset_emulate_pattern: bool = Field(
        default=False,
        description=(
            "BLE mode: if true, pulse/wave/fireworks/earthquake use pattern stepping instead of "
            "UART Pat/Preset (for toys that ignore preset UART lines)."
        ),
    )

    @classmethod
    def from_env(cls) -> ServiceConfig:
        mode_raw = (os.environ.get("LOVENSE_SERVICE_MODE") or "lan").strip().lower()
        if mode_raw not in ("lan", "ble"):
            raise ValueError("LOVENSE_SERVICE_MODE must be 'lan' or 'ble'.")
        mode: ServiceMode = mode_raw  # type: ignore[assignment]
        raw_toys = os.environ.get("LOVENSE_TOY_IDS", "")
        allowed_toy_ids = [item.strip() for item in raw_toys.split(",") if item.strip()]
        monitor_raw = os.environ.get("LOVENSE_BLE_ADVERT_MONITOR", "").strip().lower()
        advertisement_monitor = monitor_raw in ("1", "true", "yes", "on")
        ble_uart_raw = (os.environ.get("LOVENSEPY_BLE_PRESET_UART") or "Preset").strip()
        emulate_raw = os.environ.get("LOVENSEPY_BLE_PRESET_EMULATE_PATTERN", "").strip().lower()
        ble_preset_emulate_pattern = emulate_raw in ("1", "true", "yes", "on")
        return cls(
            mode=mode,
            lan_ip=os.environ.get("LOVENSE_LAN_IP"),
            lan_port=int(os.environ.get("LOVENSE_LAN_PORT", "20011")),
            app_name=os.environ.get("LOVENSE_APP_NAME", "lovensepy_service"),
            session_max_sec=float(os.environ.get("LOVENSE_SESSION_MAX_SEC", "60")),
            allowed_toy_ids=allowed_toy_ids,
            ble_scan_timeout=float(os.environ.get("LOVENSE_BLE_SCAN_TIMEOUT", "8")),
            ble_scan_name_prefix=_ble_scan_prefix_from_env(),
            ble_advertisement_monitor=advertisement_monitor,
            ble_monitor_interval_sec=float(
                os.environ.get("LOVENSE_BLE_ADVERT_MONITOR_INTERVAL", "2")
            ),
            ble_preset_uart_keyword=ble_uart_raw,
            ble_preset_emulate_pattern=ble_preset_emulate_pattern,
        )

    def validate_for_mode(self) -> None:
        if self.mode == "lan":
            if not (self.lan_ip or "").strip():
                raise ValueError(
                    "Set LOVENSE_LAN_IP when LOVENSE_SERVICE_MODE=lan (or pass lan_ip)."
                )

    def ble_scan_prefix_or_none(self) -> str | None:
        p = self.ble_scan_name_prefix
        if p is None:
            return None
        s = str(p).strip()
        return s if s else None

    def ble_connect_client_kwargs(self) -> dict[str, Any]:
        """Keyword args merged into BleDirectClient for ``POST /ble/connect``.

        See :class:`~lovensepy.ble_direct.client.BleDirectClient`.
        """
        raw = (self.ble_preset_uart_keyword or "Preset").strip().lower()
        kw = "Preset" if raw == "preset" else "Pat"
        out: dict[str, Any] = {"ble_preset_uart_keyword": kw}
        if self.ble_preset_emulate_pattern:
            out["ble_preset_emulate_with_pattern"] = True
        return out
