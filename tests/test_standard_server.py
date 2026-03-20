"""
Tests for Standard API — server.

Run: LOVENSE_DEV_TOKEN=... LOVENSE_UID=... pytest tests/test_standard_server.py -v

With QR pairing: LOVENSE_QR_PAIRING=1 LOVENSE_CALLBACK_PORT=8765
(use ngrok, set Callback URL in Dashboard).
"""

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from lovensepy import Actions, Presets, ServerClient, get_qr_code
from lovensepy.toy_utils import features_for_toy
from tests.conftest import requires_socket
from tests.helpers.test_utils import assert_has_code, call_or_skip, is_success_response

# Shared state for callback receiver
_callback_received: dict | None = None


class _LovenseCallbackHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        global _callback_received
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length else b""
        try:
            data = json.loads(body.decode()) if body else {}
        except json.JSONDecodeError:
            data = {}
        _callback_received = data
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def log_message(self, format, *args):
        pass


def _run_pairing(
    developer_token: str, uid: str, port: int, timeout: float = 120.0
) -> tuple[str | None, dict]:
    """Get QR, start callback server, wait for Lovense POST. Returns (uid, toys) from callback."""
    global _callback_received
    _callback_received = None

    qr_data = get_qr_code(developer_token, uid, uname=f"lovensepy_test_{uid[:8]}")
    qr_url = qr_data.get("qr", "")
    code = qr_data.get("code", "")

    print(f"\n>>> SCAN QR with Lovense Remote: {qr_url}")
    if code:
        print(f">>> Or enter code in Lovense Connect: {code}")
    print(">>> Callback URL in Lovense Dashboard must point to this server (use ngrok)")
    print(f">>> Waiting up to {timeout:.0f}s for callback...\n")

    server = HTTPServer(("", port), _LovenseCallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and _callback_received is None:
        time.sleep(0.5)
    server.shutdown()
    thread.join(timeout=2)

    if _callback_received and "uid" in _callback_received:
        toys = _callback_received.get("toys") or {}
        if isinstance(toys, dict):
            toys = {
                tid: dict(t) if isinstance(t, dict) else {"name": str(t), "id": tid}
                for tid, t in toys.items()
            }
        else:
            toys = {}
        return _callback_received["uid"], toys
    return None, {}


@requires_socket
class TestServerClient:
    """Server client tests. Requires LOVENSE_DEV_TOKEN and LOVENSE_UID (or QR pairing)."""

    @pytest.fixture(scope="class")
    def paired_data(self):
        """Session-scoped: run pairing once, reuse (uid, toys) for all tests."""
        token = os.environ["LOVENSE_DEV_TOKEN"]
        uid = os.environ.get("LOVENSE_UID")
        qr_pairing = os.environ.get("LOVENSE_QR_PAIRING", "").lower() in ("1", "true", "yes")

        if qr_pairing:
            port = int(os.environ.get("LOVENSE_CALLBACK_PORT", "8765"))
            test_uid = uid or "lovensepy_test_" + str(int(time.time()))
            paired_uid, toys = _run_pairing(token, test_uid, port)
            if paired_uid:
                return paired_uid, toys
            if uid:
                return uid, {}
            pytest.skip(
                "QR pairing: no callback received. Set LOVENSE_UID or ensure ngrok + callback URL."
            )
        if not uid:
            pytest.skip(
                "LOVENSE_UID required when not using LOVENSE_QR_PAIRING "
                "(uid from your QR pairing callback)"
            )
        return uid, {}

    @pytest.fixture
    def paired_uid(self, paired_data):
        return paired_data[0]

    @pytest.fixture
    def paired_toys(self, paired_data):
        return paired_data[1]

    @pytest.fixture
    def client(self, paired_uid):
        token = os.environ["LOVENSE_DEV_TOKEN"]
        return ServerClient(token, paired_uid)

    def test_function_request(self, client):
        """Send vibrate command to toys (like LAN/Socket). With paired uid, toys respond."""
        resp = call_or_skip(lambda: client.function_request({Actions.VIBRATE: 5}, time=3))
        assert_has_code(resp)
        if is_success_response(resp):
            print("  -> Vibrate:5 for 3s delivered to toys")
        elif resp.code == 503:
            print("  -> 503: uid not paired (scan QR with LOVENSE_QR_PAIRING=1)")

    def test_stop(self, client):
        """Send stop to all toys."""
        resp = call_or_skip(client.stop)
        assert_has_code(resp)
        if is_success_response(resp):
            print("  -> Stop delivered")

    def test_control_flow(self, client):
        """Full control flow: vibrate → preset → stop (like Socket/LAN tests)."""
        resp = call_or_skip(lambda: client.function_request({Actions.VIBRATE: 10}, time=3))
        if not is_success_response(resp):
            pytest.skip(f"Need paired uid: {getattr(resp, 'message', None) or resp}")
        print("  -> Vibrate:10 for 3s OK")

        resp = call_or_skip(lambda: client.preset_request(Presets.PULSE, time=2))
        assert is_success_response(resp), f"Preset failed: {resp}"
        print("  -> Preset pulse 2s OK")

        resp = call_or_skip(client.stop)
        assert is_success_response(resp), f"Stop failed: {resp}"
        print("  -> Stop OK")

    def test_control_all_toys(self, client, paired_toys):
        """Control each toy and each motor (like Socket API full flow). Requires QR pairing."""
        if not paired_toys:
            pytest.skip("No toys from callback — use LOVENSE_QR_PAIRING=1 and scan QR")
        toys = paired_toys
        DURATION_SEC = 2.0

        print(f"\n>>> Controlling {len(toys)} toy(s), each motor:")
        for tid, t in toys.items():
            name = t.get("name") or t.get("nickName") or tid
            feats = features_for_toy(t)
            print(f"    {name} ({tid}): {feats}")
            for feat in feats:
                action = {feat: 12}
                resp = call_or_skip(lambda: client.function_request(action, time=DURATION_SEC, toy_id=tid))
                if is_success_response(resp):
                    print(f"      -> {feat}:12 for {DURATION_SEC}s OK")
                else:
                    print(f"      -> {feat} failed: {resp}")
                time.sleep(0.3)
            client.stop(toy_id=tid)
            time.sleep(0.2)

        client.stop()
        print("  -> All stopped")
