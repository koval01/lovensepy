import asyncio

from fastapi.testclient import TestClient

from lovensepy import Actions
from lovensepy._models import CommandResponse, GetToysResponse
from lovensepy.services.fastapi.app import create_app
from lovensepy.services.fastapi.config import ServiceConfig


def _toy_row(toy_id: str, *, toy_type: str = "lush", name: str | None = None) -> dict:
    return {"id": toy_id, "name": name or toy_id, "toyType": toy_type, "nickName": name or toy_id}


def test_socket_backend_get_toys_reads_internal_state():
    cfg = ServiceConfig(
        mode="socket",
        socket_developer_token="dev",
        socket_uid="u1",
        socket_platform="platform",
        app_name="test",
    )

    from lovensepy.services.fastapi.socket_backend import SocketControlBackend

    backend = SocketControlBackend(cfg)
    backend._toys_by_id = {"t1": _toy_row("t1")}  # type: ignore[attr-defined]

    resp = asyncio.run(backend.get_toys())
    assert resp.data is not None
    assert len(resp.data.toys) == 1
    assert resp.data.toys[0].id == "t1"


def test_socket_backend_function_request_uses_local_client_when_available():
    cfg = ServiceConfig(
        mode="socket",
        socket_developer_token="dev",
        socket_uid="u1",
        socket_platform="platform",
        app_name="test",
    )

    from lovensepy.services.fastapi.socket_backend import SocketControlBackend

    backend = SocketControlBackend(cfg)

    class _Lan:
        def __init__(self) -> None:
            self.called: dict | None = None

        async def function_request(
            self,
            actions,
            time,
            loop_on_time,
            loop_off_time,
            toy_id,
            stop_previous,
            timeout=None,
            *,
            wait_for_completion=True,
        ):
            self.called = {
                "actions": actions,
                "time": time,
                "toy_id": toy_id,
                "stop_previous": stop_previous,
                "wait_for_completion": wait_for_completion,
            }
            return CommandResponse(code=200, type="OK", result=True, data={"transport": "lan"})

    class _Socket:
        is_socket_io_connected = True

        def __init__(self) -> None:
            self._lan_client = _Lan()

        async def send_command_await(self, *args, **kwargs):
            raise AssertionError("Should not call websocket when local client exists")

    backend._socket = _Socket()  # type: ignore[attr-defined]

    resp = asyncio.run(
        backend.function_request(
            actions={Actions.VIBRATE: 5},
            time=0,
            toy_id="t1",
            stop_previous=False,
            wait_for_completion=True,
        )
    )
    assert resp.data is not None
    assert resp.data.get("transport") == "lan"


def test_socket_backend_function_request_builds_action_for_websocket():
    cfg = ServiceConfig(
        mode="socket",
        socket_developer_token="dev",
        socket_uid="u1",
        socket_platform="platform",
        app_name="test",
    )

    from lovensepy.services.fastapi.socket_backend import SocketControlBackend

    backend = SocketControlBackend(cfg)

    class _Socket:
        def __init__(self) -> None:
            self._lan_client = None
            self.sent: dict | None = None
            self.is_socket_io_connected = True

        async def send_command_await(
            self, command, action, *, time_sec, toy, loop_running_sec, loop_pause_sec, stop_previous
        ):
            self.sent = {
                "command": command,
                "action": action,
                "toy": toy,
                "loop_running_sec": loop_running_sec,
                "loop_pause_sec": loop_pause_sec,
                "stop_previous": stop_previous,
            }

    backend._socket = _Socket()  # type: ignore[attr-defined]

    asyncio.run(
        backend.function_request(
            actions={Actions.VIBRATE: 5},
            time=0,
            toy_id="t1",
            stop_previous=None,
            wait_for_completion=True,
        )
    )

    assert backend._socket.sent is not None  # type: ignore[attr-defined]
    assert backend._socket.sent["command"] == "Function"  # type: ignore[attr-defined]
    assert backend._socket.sent["action"] == "Vibrate:5"  # type: ignore[attr-defined]


def test_composite_backend_routes_by_toy_id():
    from lovensepy.services.fastapi.multi_backend import CompositeLovenseControlBackend

    class _Backend:
        def __init__(self, name: str, toy_id: str) -> None:
            self.name = name
            self.toy_id = toy_id
            self.calls: list = []

        async def get_toys(self, timeout=None, *, query_battery=True):
            return GetToysResponse.model_validate({"data": {"toys": [_toy_row(self.toy_id)]}})

        async def function_request(self, *args, toy_id=None, **kwargs):
            self.calls.append({"toy_id": toy_id, "args": args, "kwargs": kwargs})
            return CommandResponse(code=200, type="OK", result=True, data={"backend": self.name})

        async def stop(self, toy_id=None, timeout=None):
            self.calls.append({"stop_toy_id": toy_id})
            return CommandResponse(code=200, type="OK", result=True, data={"backend": self.name})

        async def pattern_request(self, *args, toy_id=None, **kwargs):
            self.calls.append({"pattern_toy_id": toy_id})
            return CommandResponse(code=200, type="OK", result=True, data={"backend": self.name})

        async def preset_request(self, *args, toy_id=None, **kwargs):
            self.calls.append({"preset_toy_id": toy_id})
            return CommandResponse(code=200, type="OK", result=True, data={"backend": self.name})

    lan = _Backend("lan", "t1")
    sock = _Backend("socket", "t2")
    comp = CompositeLovenseControlBackend({"lan": lan, "socket": sock})

    asyncio.run(
        comp.function_request(
            actions={Actions.VIBRATE: 5},
            time=0,
            toy_id="t1",
            stop_previous=False,
            wait_for_completion=True,
        )
    )

    assert len(lan.calls) == 1
    assert len(sock.calls) == 0


def test_fastapi_socket_endpoints(monkeypatch):
    # Avoid real websocket connection by swapping SocketControlBackend.
    import lovensepy.services.http_api.app as http_app_module

    class _FakeSocketBackend:
        def __init__(self, cfg: ServiceConfig) -> None:
            self._qr = {"qrcodeUrl": "http://qr", "qrcode": "raw"}
            self._toys = {"t1": _toy_row("t1")}

        async def connect(self) -> None:
            return

        async def aclose(self) -> None:
            return

        async def get_toys(self, timeout=None, *, query_battery=True) -> GetToysResponse:
            return GetToysResponse.model_validate({"data": {"toys": list(self._toys.values())}})

        def status_info(self) -> dict:
            return {"socket_io_connected": False, "toy_ids": ["t1"]}

        @property
        def qr_info(self) -> dict:
            return dict(self._qr)

        def request_qr(self) -> None:
            return

    monkeypatch.setattr(http_app_module, "SocketControlBackend", _FakeSocketBackend)

    cfg = ServiceConfig(
        mode="socket",
        socket_developer_token="dev",
        socket_uid="u1",
        socket_platform="platform",
        app_name="test",
    )
    app = create_app(cfg)
    with TestClient(app) as client:
        s = client.get("/socket/status").json()
        assert s["toy_ids"] == ["t1"]

        q = client.get("/socket/qr").json()
        assert q["qrcodeUrl"] == "http://qr"
