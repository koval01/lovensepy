"""Direct BLE control (optional ``bleak``)."""

from .client import (
    DEFAULT_DUAL_SINGLE_CHANNEL_PRIME_DELAY_S,
    DEFAULT_POST_TIMED_FUNCTION_SILENCE_COOLDOWN_S,
    DEFAULT_UART_INTER_COMMAND_DELAY_S,
    DEFAULT_UART_RX_UUIDS,
    DEFAULT_UART_TX_UUIDS,
    BleDirectClient,
    LovenseBleAdvertisement,
    build_vibrate_command,
    discover_uart_rx_notify,
    discover_writable_uart_tx,
    scan_lovense_ble_advertisements,
    scan_lovense_ble_devices,
)
from .hub import BleDirectHub, make_ble_toy_id
from .sync_hub import BleDirectHubSync, ble_sync_default_timeout, run_ble_coroutine
from .uart_catalog import (
    DEFAULT_FULL_STOP_COMMANDS,
    ble_stop_command_strings_for_toy_type,
    ble_uart_features_for_toy_type,
    default_full_stop_payloads,
)
from .uart_replies import DeviceTypeFields, parse_battery_percent, parse_device_type_fields

__all__ = [
    "BleDirectHub",
    "make_ble_toy_id",
    "BleDirectHubSync",
    "BleDirectClient",
    "ble_sync_default_timeout",
    "run_ble_coroutine",
    "DEFAULT_FULL_STOP_COMMANDS",
    "DEFAULT_DUAL_SINGLE_CHANNEL_PRIME_DELAY_S",
    "DEFAULT_POST_TIMED_FUNCTION_SILENCE_COOLDOWN_S",
    "DEFAULT_UART_INTER_COMMAND_DELAY_S",
    "DEFAULT_UART_RX_UUIDS",
    "DEFAULT_UART_TX_UUIDS",
    "DeviceTypeFields",
    "ble_stop_command_strings_for_toy_type",
    "ble_uart_features_for_toy_type",
    "build_vibrate_command",
    "default_full_stop_payloads",
    "discover_uart_rx_notify",
    "discover_writable_uart_tx",
    "parse_battery_percent",
    "parse_device_type_fields",
    "LovenseBleAdvertisement",
    "scan_lovense_ble_advertisements",
    "scan_lovense_ble_devices",
]
