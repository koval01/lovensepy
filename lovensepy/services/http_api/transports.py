"""Transport wiring: turn a :class:`ServiceConfig` into control backends."""

from __future__ import annotations

from dataclasses import dataclass

from lovensepy.ble_direct.hub import BleDirectHub
from lovensepy.standard.async_lan import AsyncLANClient

from .backend import LovenseControlBackend
from .config import ServiceConfig
from .multi_backend import CompositeLovenseControlBackend
from .socket_backend import SocketControlBackend


@dataclass(slots=True)
class Transports:
    """Backends built for one configuration snapshot."""

    backend: LovenseControlBackend
    ble_hub: BleDirectHub | None
    socket_backend: SocketControlBackend | None


def effective_config(cfg: ServiceConfig) -> ServiceConfig:
    """Disable transports whose prerequisites are missing so the service still starts.

    Lets the executable run with no environment at all: LAN waits for an IP
    (``POST /config/lan-ip``), Socket waits for credentials (``POST /config/socket``),
    and BLE needs nothing but a Bluetooth radio.
    """
    enable_lan = bool(cfg.enable_lan and (cfg.lan_ip or "").strip())
    enable_socket = bool(
        cfg.enable_socket
        and (cfg.socket_developer_token or "").strip()
        and (cfg.socket_uid or "").strip()
        and (cfg.socket_platform or "").strip()
    )
    return cfg.model_copy(
        update={
            "enable_lan": enable_lan,
            "enable_ble": bool(cfg.enable_ble),
            "enable_socket": enable_socket,
        }
    )


def build_transports(
    cfg: ServiceConfig,
    *,
    ble_hub: BleDirectHub | None = None,
    socket_backend: SocketControlBackend | None = None,
) -> Transports:
    """Create (or reuse) transports for ``cfg``.

    Existing ``ble_hub`` / ``socket_backend`` instances are reused so a configuration
    change does not drop live BLE links or the Socket API session.
    """
    parts: dict[str, LovenseControlBackend] = {}

    if cfg.enable_lan:
        parts["lan"] = AsyncLANClient(
            cfg.app_name,
            str(cfg.lan_ip).strip(),
            port=cfg.lan_port,
        )

    hub = ble_hub
    if cfg.enable_ble:
        hub = hub or BleDirectHub()
        parts["ble"] = hub

    socket = socket_backend
    if cfg.enable_socket:
        socket = socket or SocketControlBackend(cfg)
        parts["socket"] = socket

    if len(parts) == 1:
        backend = next(iter(parts.values()))
    else:
        backend = CompositeLovenseControlBackend(parts)

    return Transports(backend=backend, ble_hub=hub, socket_backend=socket)
