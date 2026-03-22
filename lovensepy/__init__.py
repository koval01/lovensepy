"""
lovensepy — Python Lovense API client.

Supports:
- Standard API LAN (Game Mode)
- Standard API Server
- Standard Socket API
- Toy Events API
- Home Assistant MQTT bridge (optional ``paho-mqtt``)
- Direct BLE (optional ``bleak`` via ``lovensepy[ble]``); ``BleDirectHub`` (async) or
  ``BleDirectHubSync`` (LANClient-like scripts)

Raw methods: function_request, send_command for custom logic.
High-level: SyncPatternPlayer, AsyncPatternPlayer for ready-made patterns.
"""

from typing import Any

from ._constants import PRESET_BLE_PAT_INDEX, Actions, Presets
from ._http_identity import package_version
from .exceptions import (
    LovenseAuthError,
    LovenseBLEError,
    LovenseDeviceOfflineError,
    LovenseError,
    LovenseNetworkError,
    LovenseResponseParseError,
    LovenseTimeoutError,
)
from .patterns import AsyncPatternPlayer, SyncPatternPlayer
from .socket_api import (
    SocketAPIClient,
    build_websocket_url,
    get_socket_url,
    get_token,
)
from .standard import (
    AsyncLANClient,
    AsyncServerClient,
    LANClient,
    LovenseAsyncControlClient,
    ServerClient,
    get_qr_code,
)
from .toy_events import ToyEventsClient
from .toy_utils import features_for_toy, stop_actions

__version__ = package_version()


def __getattr__(name: str) -> Any:
    if name == "HAMqttBridge":
        from lovensepy.integrations.mqtt.ha_bridge import (  # pylint: disable=import-outside-toplevel
            HAMqttBridge,
        )

        return HAMqttBridge
    if name == "BleDirectClient":
        from lovensepy.ble_direct import (  # pylint: disable=import-outside-toplevel
            BleDirectClient as _BleDirectClient,
        )

        return _BleDirectClient
    if name == "BleDirectHub":
        from lovensepy.ble_direct import (  # pylint: disable=import-outside-toplevel
            BleDirectHub as _BleDirectHub,
        )

        return _BleDirectHub
    if name == "BleDirectHubSync":
        from lovensepy.ble_direct import (  # pylint: disable=import-outside-toplevel
            BleDirectHubSync as _BleDirectHubSync,
        )

        return _BleDirectHubSync
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "__version__",
    "Actions",
    "Presets",
    "PRESET_BLE_PAT_INDEX",
    "LANClient",
    "AsyncLANClient",
    "LovenseAsyncControlClient",
    "ServerClient",
    "AsyncServerClient",
    "get_qr_code",
    "get_token",
    "get_socket_url",
    "build_websocket_url",
    "SocketAPIClient",
    "ToyEventsClient",
    "SyncPatternPlayer",
    "AsyncPatternPlayer",
    "features_for_toy",
    "stop_actions",
    "LovenseError",
    "LovenseNetworkError",
    "LovenseAuthError",
    "LovenseDeviceOfflineError",
    "LovenseTimeoutError",
    "LovenseResponseParseError",
    "LovenseBLEError",
    "HAMqttBridge",  # pylint: disable=undefined-all-variable
    "BleDirectClient",  # pylint: disable=undefined-all-variable
    "BleDirectHub",  # pylint: disable=undefined-all-variable
    "BleDirectHubSync",  # pylint: disable=undefined-all-variable
]
