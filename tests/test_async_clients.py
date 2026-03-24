import asyncio
import inspect

import pytest

from lovensepy import Actions, AsyncLANClient, AsyncServerClient, LovenseAsyncControlClient
from lovensepy.standard import async_lan as async_lan_module
from lovensepy.transport import async_http as async_http_module
from lovensepy.transport.async_http import AsyncHttpTransport


def test_lovense_async_control_client_isinstance():
    assert issubclass(AsyncLANClient, LovenseAsyncControlClient)
    assert issubclass(AsyncServerClient, LovenseAsyncControlClient)
    pytest.importorskip("bleak", reason="ble_direct needs bleak")
    from lovensepy.ble_direct.client import BleDirectClient
    from lovensepy.ble_direct.hub import BleDirectHub

    assert issubclass(BleDirectClient, LovenseAsyncControlClient)
    assert issubclass(BleDirectHub, LovenseAsyncControlClient)


def test_async_server_accepts_scheduler_kwargs():
    sig = inspect.signature(AsyncServerClient.function_request)
    assert "wait_for_completion" in sig.parameters
    assert sig.parameters["wait_for_completion"].kind == inspect.Parameter.KEYWORD_ONLY


async def test_async_server_function_request_wait_for_completion_no_typeerror(monkeypatch):
    client = AsyncServerClient("tok", "uid1")

    async def fake_send_command(payload, timeout=None):  # type: ignore[no-untyped-def]
        return {"code": 200, "type": "OK", "result": True, "data": {}}

    monkeypatch.setattr(client, "send_command", fake_send_command)

    await client.function_request(
        {Actions.VIBRATE: 3},
        time=0,
        toy_id="t1",
        wait_for_completion=False,
    )


def test_async_lan_context_manager_closes_transport():
    async def _runner():
        client = AsyncLANClient("TestBot", "127.0.0.1", port=20011)
        closed = {"called": False}

        async def fake_aclose():
            closed["called"] = True

        client._transport.aclose = fake_aclose  # type: ignore[method-assign]

        async with client:
            pass

        assert closed["called"] is True

    asyncio.run(_runner())


def test_async_lan_method_timeout_override_propagates():
    async def _runner():
        client = AsyncLANClient("TestBot", "127.0.0.1", port=20011, timeout=9.0)
        seen_timeout: list[float | None] = []

        async def fake_send_command(payload, timeout=None):  # type: ignore[no-untyped-def]
            seen_timeout.append(timeout)
            return {"code": 200, "type": "OK"}

        client.send_command = fake_send_command  # type: ignore[method-assign]

        await client.function_request({Actions.VIBRATE: 5}, timeout=1.5)
        assert seen_timeout[-1] == 1.5

        await client.function_request({Actions.VIBRATE: 5})
        assert seen_timeout[-1] is None

    asyncio.run(_runner())


def test_async_lan_fingerprint_verification_is_serialized(monkeypatch):
    async def _runner():
        client = AsyncLANClient(
            "TestBot",
            "127.0.0.1",
            use_https=True,
            verify_ssl=False,
        )
        calls = {"count": 0}

        def fake_verify(host, port, fingerprint, timeout):  # type: ignore[no-untyped-def]
            calls["count"] += 1
            # Sleep to make races likely if lock is missing.
            import time

            time.sleep(0.03)
            return True

        monkeypatch.setattr(async_lan_module, "verify_cert_fingerprint", fake_verify)

        results = await asyncio.gather(*(client._ensure_fingerprint_verified() for _ in range(10)))
        assert all(results)
        assert calls["count"] == 1

    asyncio.run(_runner())


def test_async_http_transport_reuses_clients_and_closes(monkeypatch):
    async def _runner():
        class FakePostCM:
            status = 200

            async def __aenter__(self):  # type: ignore[no-untyped-def]
                return self

            async def __aexit__(self, *args):  # type: ignore[no-untyped-def]
                return None

            async def json(self):  # type: ignore[no-untyped-def]
                return {}

        class FakeClientSession:
            def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                self.closed = False

            def post(self, url, **kwargs):  # type: ignore[no-untyped-def]
                return FakePostCM()

            async def close(self):  # type: ignore[no-untyped-def]
                self.closed = True

        monkeypatch.setattr(async_http_module.aiohttp, "ClientSession", FakeClientSession)

        transport = AsyncHttpTransport("http://127.0.0.1:20011/command", timeout=2.0)
        session_a = transport._get_session(True)
        session_b = transport._get_session(True)
        session_c = transport._get_session(False)

        assert session_a is session_b
        assert session_a is not session_c
        assert len(transport._sessions) == 2

        await transport.aclose()
        assert transport._sessions == {}

    asyncio.run(_runner())
