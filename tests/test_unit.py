"""
Unit tests (no Lovense connection required).
"""

import tomllib
from pathlib import Path

from lovensepy import PRESET_BLE_PAT_INDEX, Actions, LANClient, Presets, ServerClient
from lovensepy._constants import ERROR_CODES, FUNCTION_RANGES


def test_actions_enum():
    """Actions has expected values."""
    assert Actions.VIBRATE == "Vibrate"
    assert Actions.STOP == "Stop"
    assert Actions.ALL == "All"


def test_presets_enum():
    """Presets has expected values."""
    assert Presets.PULSE == "pulse"
    assert Presets.WAVE == "wave"


def test_preset_ble_pat_index_default_slots():
    """BLE UART Pat slot map for the four Remote names (Connect-style indices)."""
    assert PRESET_BLE_PAT_INDEX["pulse"] == 1
    assert PRESET_BLE_PAT_INDEX["wave"] == 2
    assert PRESET_BLE_PAT_INDEX["fireworks"] == 3
    assert PRESET_BLE_PAT_INDEX["earthquake"] == 4


def test_error_codes():
    """Error codes dict is populated."""
    assert 200 in ERROR_CODES
    assert 400 in ERROR_CODES


def test_function_ranges():
    """Function ranges have min/max for known actions."""
    assert "Vibrate" in FUNCTION_RANGES
    assert FUNCTION_RANGES["Vibrate"] == (0, 20)
    assert FUNCTION_RANGES["Pump"] == (0, 3)


def test_lan_client_creation():
    """LANClient creates with correct endpoint."""
    c = LANClient("Test", "192.168.1.1", port=20011)
    assert "192.168.1.1" in c.api_endpoint
    assert "20011" in c.api_endpoint
    assert c._transport.headers.get("X-platform") == "Test"
    assert "User-Agent" in c._transport.headers


def test_lan_client_https():
    """LANClient with use_https uses lovense.club domain."""
    c = LANClient("Test", "192.168.1.1", use_https=True)
    assert "lovense.club" in c.api_endpoint
    assert c.api_endpoint.startswith("https://")


def test_server_client_creation():
    """ServerClient creates with token and uid, uses HttpTransport."""
    c = ServerClient("token", "uid123")
    assert c.developer_token == "token"
    assert c.uid == "uid123"
    assert "lovense-api.com" in c.api_endpoint
    assert "User-Agent" in c._transport.headers
    assert "lovensepy/" in c._transport.headers["User-Agent"]
    assert "github.com/koval01/lovensepy" in c._transport.headers["User-Agent"]


def test_server_pattern_request_matches_lan_overloads():
    """Server pattern_request accepts list form (LAN-style) or rule+strength strings."""
    from unittest.mock import patch

    c = ServerClient("t", "u")
    ok = {"code": 200, "type": "OK", "result": True}
    with patch.object(c, "send_command", return_value=ok) as m:
        c.pattern_request([5, 10], time=4, toy_id="ab")
    p1 = m.call_args_list[0][0][0]
    assert p1["command"] == "Pattern"
    assert p1["strength"] == "5;10"
    assert p1["timeSec"] == 4
    assert p1["toy"] == "ab"

    m.reset_mock()
    with patch.object(c, "send_command", return_value=ok) as m:
        c.pattern_request("V:1;F:;S:200#", "1;2;3", time=1)
    p2 = m.call_args_list[0][0][0]
    assert p2["rule"] == "V:1;F:;S:200#"
    assert p2["strength"] == "1;2;3"


def test_lan_client_decode_response():
    """decode_response handles None and dict."""
    c = LANClient("Test", "127.0.0.1")
    assert "No response" in c.decode_response(None)
    s = c.decode_response({"code": 200, "type": "OK"})
    assert "200" in s or "OK" in s


def test_features_for_toy():
    """features_for_toy returns correct features for toy types."""
    from lovensepy import features_for_toy, stop_actions

    edge = {"toyType": "edge", "name": "Edge"}
    assert features_for_toy(edge) == ["Vibrate1", "Vibrate2"]
    assert stop_actions(edge) == {"Vibrate1": 0, "Vibrate2": 0}

    nora = {"toyType": "nora"}
    assert "Vibrate" in features_for_toy(nora)
    assert "Rotate" in features_for_toy(nora)

    gush = {"toyType": "gush", "name": "Gush"}
    assert features_for_toy(gush) == ["Vibrate"]


def test_sync_pattern_player_creation():
    """SyncPatternPlayer creates with client and toys."""
    from lovensepy import SyncPatternPlayer

    c = LANClient("Test", "127.0.0.1")
    toys = {"t1": {"toyType": "edge", "name": "Edge"}}
    player = SyncPatternPlayer(c, toys)
    assert player.features("t1") == ["Vibrate1", "Vibrate2"]


def test_lovense_https_fingerprint():
    """LOVENSE_HTTPS_FINGERPRINT is set and has valid SHA-256 format."""
    from lovensepy.security import LOVENSE_HTTPS_FINGERPRINT

    fp = LOVENSE_HTTPS_FINGERPRINT.replace(":", "")
    assert len(fp) == 64
    assert all(c in "0123456789ABCDEF" for c in fp)


def test_http_identity_user_agent_matches_pyproject_version():
    """User-Agent includes the same version string as pyproject.toml."""
    from lovensepy._http_identity import (
        default_http_headers,
        merge_http_headers,
        user_agent_string,
    )

    root = Path(__file__).resolve().parent.parent
    with (root / "pyproject.toml").open("rb") as fp:
        expected_ver = tomllib.load(fp)["project"]["version"]

    ua = user_agent_string()
    assert f"lovensepy/{expected_ver}" in ua
    assert "github.com/koval01/lovensepy" in ua
    assert "git@koval-dev.org" in ua

    assert default_http_headers() == {"User-Agent": ua}

    merged = merge_http_headers({"X-platform": "MyApp", "User-Agent": "custom-ua"})
    assert merged["User-Agent"] == "custom-ua"
    assert merged["X-platform"] == "MyApp"


def test_package_version_export():
    """Top-level __version__ matches pyproject when installed or from source."""
    import lovensepy

    root = Path(__file__).resolve().parent.parent
    with (root / "pyproject.toml").open("rb") as fp:
        expected_ver = tomllib.load(fp)["project"]["version"]

    assert lovensepy.__version__ == expected_ver
