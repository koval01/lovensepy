"""UART catalog (Connect-derived) — no radio."""

from lovensepy.ble_direct.uart_catalog import (
    ble_stop_command_strings_for_toy_type,
    ble_uart_features_for_toy_type,
    default_full_stop_payloads,
)


def test_default_full_stop_nonempty():
    p = default_full_stop_payloads()
    assert len(p) >= 10
    assert b"Vibrate:0;" in p


def test_edge_dual_vibrate_features():
    assert ble_uart_features_for_toy_type("edge") == ("Vibrate1", "Vibrate2")


def test_lapis_vibrate3():
    assert "Vibrate3" in ble_uart_features_for_toy_type("lapis")


def test_solace_family_substring():
    assert "Thrusting" in ble_uart_features_for_toy_type("solace pro")


def test_gush_fallback_matches_vibrate_only_api():
    """
    When GetToys omits function lists, fallback must not add Oscillate — LAN API
    only exposes Vibrate for Gush (second channel was a mistaken UART guess).
    """
    assert ble_uart_features_for_toy_type("gush") == ("Vibrate",)
    cmds = ble_stop_command_strings_for_toy_type("gush")
    assert cmds == ["Vibrate:0;"]
