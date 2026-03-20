"""
Tests for Standard API — local (LAN Game Mode).

Run: LOVENSE_LAN_IP=... LOVENSE_LAN_PORT=20011 pytest tests/test_local.py -v -s
"""

import os

import pytest

from lovensepy import (
    Actions,
    LANClient,
    Presets,
    SyncPatternPlayer,
)
from tests.conftest import requires_lan
from tests.helpers.lan_scenarios import (
    build_lan_client_from_env,
    parse_lan_toys,
    run_lan_function_demo,
    run_sync_pattern_player_demo,
)
from tests.helpers.test_utils import assert_has_code, call_or_skip


def _log(msg: str) -> None:
    print(msg, flush=True)


@requires_lan
class TestLANClient:
    """LAN client tests. Requires LOVENSE_LAN_IP."""

    @pytest.fixture
    def client(self):
        ip = os.environ["LOVENSE_LAN_IP"]
        port = int(os.environ.get("LOVENSE_LAN_PORT", "20011"))
        return LANClient("lovensepy_test", ip, port=port)

    def test_get_toys(self, client):
        """API should return toys info (or empty if none connected)."""
        resp = call_or_skip(client.get_toys)
        assert_has_code(resp)
        assert resp.type is not None

    def test_get_toys_name(self, client):
        """API should return toy names."""
        resp = call_or_skip(client.get_toys_name)
        assert_has_code(resp)
        assert resp.type is not None

    def test_function_and_stop(self, client):
        """Send function then stop."""
        function_resp = call_or_skip(lambda: client.function_request({Actions.ALL: 2}, time=2))
        stop_resp = call_or_skip(client.stop)
        assert_has_code(function_resp)
        assert_has_code(stop_resp)

    def test_preset_request(self, client):
        """Send preset for short duration."""
        resp = call_or_skip(lambda: client.preset_request(Presets.PULSE, time=2))
        assert_has_code(resp)

    def test_pattern_request(self, client):
        """Send pattern."""
        resp = call_or_skip(lambda: client.pattern_request([5, 10, 15], time=2))
        assert_has_code(resp)

    def test_decode_response(self, client):
        """decode_response formats response string."""
        resp = call_or_skip(client.get_toys)
        s = client.decode_response(resp)
        assert isinstance(s, str)
        assert len(s) > 0


@requires_lan
def test_full_flow():
    """
    Full LAN flow: get toys, per-motor sine wave, combos (2 motors, 2 toys, all).
    Like Socket API test but via HTTP.
    """
    ip = os.environ["LOVENSE_LAN_IP"]
    port = int(os.environ.get("LOVENSE_LAN_PORT", "20011"))
    client = LANClient("lovensepy_test", ip, port=port)

    resp = call_or_skip(client.get_toys)
    toys = parse_lan_toys(resp)
    assert toys, "No toys — connect toys to Lovense Remote Game Mode"

    run_lan_function_demo(client, toys, log_fn=_log)


@requires_lan
def test_sync_pattern_player_flow():
    """
    LAN + SyncPatternPlayer flow: get toys, run per-motor waves and combos, stop all.
    """
    client = build_lan_client_from_env("lovensepy_local_only")
    resp = call_or_skip(client.get_toys)
    toys = parse_lan_toys(resp)
    assert toys, "No toys — connect toys to Lovense Remote, enable Game Mode, same LAN"

    player = SyncPatternPlayer(client, toys)
    run_sync_pattern_player_demo(player, toys, log_fn=_log)
