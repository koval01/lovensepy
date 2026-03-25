"""Configuration for :mod:`lovensepy.services.fastapi` (LAN + BLE HTTP server)."""

from __future__ import annotations

import os
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

ServiceMode = Literal["lan", "ble", "socket", "hybrid"]


def _parse_bool_env(raw: str | None, *, default: bool) -> bool:
    if raw is None:
        return default
    s = raw.strip().lower()
    if s in ("", "0", "false", "no", "off"):
        return False
    if s in ("1", "true", "yes", "on"):
        return True
    return default


def _ble_scan_prefix_from_env() -> str | None:
    raw = os.environ.get("LOVENSE_BLE_SCAN_PREFIX")
    if raw is None:
        return "LVS-"
    s = raw.strip()
    return None if s == "" else s


class ServiceConfig(BaseModel):
    mode: ServiceMode = Field(
        default="lan",
        description=(
            "Transport mode: lan (Game Mode), ble (direct BLE hub), "
            "socket (Lovense Socket API), hybrid (all enabled)."
        ),
    )
    enable_lan: bool = Field(
        default=True,
        description="If true, create LAN backend (AsyncLANClient).",
    )
    enable_ble: bool = Field(
        default=False,
        description="If true, create BLE backend (BleDirectHub).",
    )
    enable_socket: bool = Field(
        default=False,
        description="If true, create Socket API backend (SocketAPIClient).",
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
        description=(
            "If true (BLE mode), periodic background scans merge into GET /ble/advertisements. "
            "With ServiceConfig.from_env(), defaults on in ble mode unless "
            "LOVENSE_BLE_ADVERT_MONITOR is 0/false/off."
        ),
    )
    ble_monitor_interval_sec: float = Field(
        default=10.0,
        ge=0.5,
        le=120.0,
        description=(
            "When advertisement monitor is on, seconds between scan rounds "
            "(after each scan finishes)."
        ),
    )
    ble_preset_uart_keyword: str = Field(
        default="Preset",
        description=(
            "BLE mode: UART prefix for built-in presets — Preset (public UART docs) or Pat "
            "(same default keyword as BleDirectClient). "
            "Override with env LOVENSEPY_BLE_PRESET_UART."
        ),
    )
    ble_preset_emulate_pattern: bool = Field(
        default=False,
        description=(
            "BLE mode: if true, pulse/wave/fireworks/earthquake use pattern stepping instead of "
            "UART Pat/Preset (for toys that ignore preset UART lines)."
        ),
    )

    # --- Lovense Socket API (cloud) pairing + control ---
    socket_developer_token: str | None = Field(
        default=None,
        description=(
            "Lovense developer token (LOVENSE_DEV_TOKEN). Required when enable_socket=true."
        ),
    )
    socket_uid: str | None = Field(
        default=None,
        description="Lovense app user uid (LOVENSE_UID). Required when enable_socket=true.",
    )
    socket_platform: str | None = Field(
        default=None,
        description=(
            "Lovense developer dashboard platform/website name (LOVENSE_PLATFORM). "
            "Required when enable_socket=true."
        ),
    )
    socket_uname: str | None = Field(
        default=None,
        description="Optional user nickname for token issuance (LOVENSE_SOCKET_UNAME).",
    )
    socket_use_local_commands: bool = Field(
        default=True,
        description=(
            "When Socket API provides local device info, send toy commands via local HTTPS "
            "(preferred for Pattern/Preset compatibility)."
        ),
    )
    socket_auto_request_qr: bool = Field(
        default=True,
        description="If true, automatically send basicapi_get_qrcode_ts once Socket.IO is ready.",
    )
    socket_qr_ack_id: str = Field(
        default="1",
        description=(
            "ackId passed with basicapi_get_qrcode_ts and expected back in basicapi_get_qrcode_tc."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _apply_enable_defaults(cls, data: Any) -> Any:
        # Allow ServiceConfig(mode="ble") style construction used in tests.
        if not isinstance(data, dict):
            return data
        mode_raw = str(data.get("mode") or "lan").strip().lower()
        if "enable_lan" not in data:
            data["enable_lan"] = mode_raw in ("lan", "hybrid")
        if "enable_ble" not in data:
            data["enable_ble"] = mode_raw in ("ble", "hybrid")
        if "enable_socket" not in data:
            data["enable_socket"] = mode_raw in ("socket", "hybrid")
        return data

    @classmethod
    def from_env(cls) -> ServiceConfig:
        mode_raw = (os.environ.get("LOVENSE_SERVICE_MODE") or "lan").strip().lower()
        if mode_raw not in ("lan", "ble", "socket", "hybrid"):
            raise ValueError("LOVENSE_SERVICE_MODE must be 'lan', 'ble', 'socket', or 'hybrid'.")
        mode: ServiceMode = mode_raw  # type: ignore[assignment]

        enable_lan_default = mode_raw in ("lan", "hybrid")
        enable_ble_default = mode_raw in ("ble", "hybrid")
        enable_socket_default = mode_raw in ("socket", "hybrid")

        enable_lan = _parse_bool_env(
            os.environ.get("LOVENSE_ENABLE_LAN"), default=enable_lan_default
        )
        enable_ble = _parse_bool_env(
            os.environ.get("LOVENSE_ENABLE_BLE"), default=enable_ble_default
        )
        enable_socket = _parse_bool_env(
            os.environ.get("LOVENSE_ENABLE_SOCKET"), default=enable_socket_default
        )

        raw_toys = os.environ.get("LOVENSE_TOY_IDS", "")
        allowed_toy_ids = [item.strip() for item in raw_toys.split(",") if item.strip()]

        monitor_raw = os.environ.get("LOVENSE_BLE_ADVERT_MONITOR")
        if monitor_raw is None:
            advertisement_monitor = enable_ble and mode_raw in ("ble", "hybrid")
        else:
            advertisement_monitor = _parse_bool_env(monitor_raw, default=enable_ble)

        ble_uart_raw = (os.environ.get("LOVENSEPY_BLE_PRESET_UART") or "Preset").strip()
        emulate_raw = os.environ.get("LOVENSEPY_BLE_PRESET_EMULATE_PATTERN", "").strip().lower()
        ble_preset_emulate_pattern = emulate_raw in ("1", "true", "yes", "on")

        socket_developer_token = os.environ.get("LOVENSE_DEV_TOKEN")
        socket_uid = os.environ.get("LOVENSE_UID")
        socket_platform = os.environ.get("LOVENSE_PLATFORM")
        socket_uname = os.environ.get("LOVENSE_SOCKET_UNAME")
        socket_auto_request_qr = _parse_bool_env(
            os.environ.get("LOVENSE_SOCKET_AUTO_REQUEST_QR"), default=True
        )
        socket_use_local_commands = _parse_bool_env(
            os.environ.get("LOVENSE_SOCKET_USE_LOCAL_COMMANDS"),
            default=True,
        )
        socket_qr_ack_id = (os.environ.get("LOVENSE_SOCKET_QR_ACK_ID") or "1").strip() or "1"

        return cls(
            mode=mode,
            enable_lan=enable_lan,
            enable_ble=enable_ble,
            enable_socket=enable_socket,
            lan_ip=os.environ.get("LOVENSE_LAN_IP"),
            lan_port=int(os.environ.get("LOVENSE_LAN_PORT", "20011")),
            app_name=os.environ.get("LOVENSE_APP_NAME", "lovensepy_service"),
            session_max_sec=float(os.environ.get("LOVENSE_SESSION_MAX_SEC", "60")),
            allowed_toy_ids=allowed_toy_ids,
            ble_scan_timeout=float(os.environ.get("LOVENSE_BLE_SCAN_TIMEOUT", "8")),
            ble_scan_name_prefix=_ble_scan_prefix_from_env(),
            ble_advertisement_monitor=advertisement_monitor,
            ble_monitor_interval_sec=float(
                os.environ.get("LOVENSE_BLE_ADVERT_MONITOR_INTERVAL", "10")
            ),
            ble_preset_uart_keyword=ble_uart_raw,
            ble_preset_emulate_pattern=ble_preset_emulate_pattern,
            socket_developer_token=socket_developer_token,
            socket_uid=socket_uid,
            socket_platform=socket_platform,
            socket_uname=socket_uname,
            socket_use_local_commands=socket_use_local_commands,
            socket_auto_request_qr=socket_auto_request_qr,
            socket_qr_ack_id=socket_qr_ack_id,
        )

    def validate_for_mode(self) -> None:
        if self.enable_lan:
            if not (self.lan_ip or "").strip():
                raise ValueError(
                    "Set LOVENSE_LAN_IP when LOVENSE_ENABLE_LAN=1 "
                    "(or LOVENSE_SERVICE_MODE includes LAN)."
                )

        if self.enable_socket:
            missing: list[str] = []
            if not (self.socket_developer_token or "").strip():
                missing.append("LOVENSE_DEV_TOKEN")
            if not (self.socket_uid or "").strip():
                missing.append("LOVENSE_UID")
            if not (self.socket_platform or "").strip():
                missing.append("LOVENSE_PLATFORM")
            if missing:
                raise ValueError(
                    "Set Socket API credentials when LOVENSE_ENABLE_SOCKET=1: " + ", ".join(missing)
                )

        if not (self.enable_lan or self.enable_ble or self.enable_socket):
            raise ValueError(
                "No transports are enabled. Set LOVENSE_ENABLE_LAN/LOVENSE_ENABLE_BLE/"
                "LOVENSE_ENABLE_SOCKET or LOVENSE_SERVICE_MODE accordingly."
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
        from lovensepy.ble_direct.client import ble_preset_connect_kwargs

        return ble_preset_connect_kwargs(
            uart_keyword_raw=self.ble_preset_uart_keyword,
            emulate_pattern=self.ble_preset_emulate_pattern,
        )
