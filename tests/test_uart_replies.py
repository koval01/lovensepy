import pytest

from lovensepy.ble_direct.uart_replies import parse_battery_percent, parse_device_type_fields


def test_parse_battery():
    assert parse_battery_percent("85;") == 85
    assert parse_battery_percent("100") == 100


def test_parse_battery_tag_prefix():
    assert parse_battery_percent("s92;") == 92
    assert parse_battery_percent("S92") == 92
    assert parse_battery_percent("soc075;") == 75


def test_parse_battery_non_ascii_prefix():
    # Fullwidth Latin "s" (U+FF53) + 92 — still one trailing percent run
    assert parse_battery_percent("\uff5392;") == 92


def test_parse_battery_label_colon():
    assert parse_battery_percent("Bat:88;") == 88
    assert parse_battery_percent("S: 12") == 12


def test_parse_battery_rejects_gibberish():
    with pytest.raises(ValueError, match="Unexpected Battery"):
        parse_battery_percent("nope")


def test_parse_device_type():
    d = parse_device_type_fields("C:11:0082059AD3BD;")
    assert d.model_letter == "C"
    assert d.firmware == "11"
    assert d.bt_addr_hex == "0082059AD3BD"
