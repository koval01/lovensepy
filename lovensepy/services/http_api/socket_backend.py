"""
Socket API backend for :mod:`lovensepy.services.fastapi`.

Implements :class:`lovensepy.services.fastapi.backend.LovenseControlBackend` over
Lovense Socket API (WebSocket).

Design:
- Keep one long-lived SocketAPIClient connection (started in FastAPI lifespan).
- Parse:
  - `basicapi_update_device_info_tc` into a synthetic LAN-shaped `GetToysResponse`.
  - `basicapi_get_qrcode_tc` into in-memory QR info for HTTP endpoints.
- Commands:
  - Function/Stop are sent over Socket.IO websocket directly when local commands
    are not available.
  - Pattern/Preset are forwarded to the internally created `AsyncLANClient` when
    `use_local_commands=True` and local device info is available.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from lovensepy import (
    Actions,
    Presets,
    SocketAPIClient,
    build_websocket_url,
    get_socket_url,
    get_token,
)
from lovensepy._command_utils import clamp_function_actions
from lovensepy._models import CommandResponse, GetToysResponse
from lovensepy.socket_api.events import (
    BASICAPI_GET_QRCODE_TC,
    BASICAPI_UPDATE_APP_ONLINE_TC,
    BASICAPI_UPDATE_APP_STATUS_TC,
    BASICAPI_UPDATE_DEVICE_INFO_TC,
)

from .backend import LovenseControlBackend
from .config import ServiceConfig

_logger = logging.getLogger(__name__)


class SocketControlBackend(LovenseControlBackend):
    def __init__(self, cfg: ServiceConfig) -> None:
        self._cfg = cfg
        self._socket: SocketAPIClient | None = None
        self._runner_task: asyncio.Task[None] | None = None

        # Parsed state from events.
        self._toys_by_id: dict[str, dict[str, Any]] = {}
        self._toy_list_updated_at: float | None = None

        self._qr: dict[str, Any] = {}
        self._qr_updated_at: float | None = None

        self._app_online: bool | None = None
        self._app_status: int | None = None

        self._connected_event = asyncio.Event()
        self._disconnected_event = asyncio.Event()
        self._disconnected_event.set()

    @property
    def socket_io_connected(self) -> bool:
        return bool(self._socket and self._socket.is_socket_io_connected)

    @property
    def socket_client_connected(self) -> bool:
        # Underlying WsTransport connection state is private; use close/open events.
        return self.socket_io_connected or not self._disconnected_event.is_set()

    @property
    def qr_info(self) -> dict[str, Any]:
        return dict(self._qr)

    def status_info(self) -> dict[str, Any]:
        return {
            "socket_io_connected": self.socket_io_connected,
            "app_online": self._app_online,
            "app_status": self._app_status,
            "toy_ids": sorted(self._toys_by_id.keys()),
            "local_commands": bool(
                self._socket and getattr(self._socket, "_lan_client", None) is not None
            ),
        }

    def request_qr(self) -> None:
        if self._socket is None:
            return
        try:
            self._socket.send_event(
                "basicapi_get_qrcode_ts",
                {"ackId": str(self._cfg.socket_qr_ack_id)},
            )
        except Exception:  # pylint: disable=broad-exception-caught
            _logger.exception("Socket QR request failed")

    async def connect(self) -> None:
        if self._runner_task is not None:
            return

        if not (
            self._cfg.socket_developer_token and self._cfg.socket_uid and self._cfg.socket_platform
        ):
            raise ValueError("Socket credentials are required when enable_socket=true.")

        developer_token = str(self._cfg.socket_developer_token)
        uid = str(self._cfg.socket_uid)
        uname = self._cfg.socket_uname
        if uname is None:
            uname = f"user_{uid[:8]}"

        # `get_token()`/`get_socket_url()` are sync wrappers that call `run_sync_coro()`.
        # They fail inside an active asyncio loop, so run them in a worker thread.
        auth_token = await asyncio.to_thread(
            get_token, developer_token=developer_token, uid=uid, uname=uname
        )
        socket_info = await asyncio.to_thread(
            get_socket_url, auth_token, platform=str(self._cfg.socket_platform)
        )
        ws_url = build_websocket_url(socket_info, auth_token)

        async def on_connected() -> None:
            self._connected_event.set()
            if self._cfg.socket_auto_request_qr:
                self.request_qr()

        def on_event(event_name: str, payload: Any) -> None:
            try:
                if event_name == BASICAPI_GET_QRCODE_TC:
                    data = (payload or {}).get("data", {}) if isinstance(payload, dict) else {}
                    if isinstance(data, dict) and data:
                        self._qr = {
                            "qrcodeUrl": data.get("qrcodeUrl") or data.get("qrcode"),
                            "qrcode": data.get("qrcode"),
                            "ackId": data.get("ackId"),
                        }
                        self._qr_updated_at = asyncio.get_running_loop().time()
                elif event_name in (
                    BASICAPI_UPDATE_APP_ONLINE_TC,
                    BASICAPI_UPDATE_APP_STATUS_TC,
                ):
                    # Online/status shape differs; best-effort normalize.
                    if isinstance(payload, dict):
                        if "online" in payload:
                            self._app_online = bool(payload.get("online"))
                        if "status" in payload:
                            self._app_status = int(payload.get("status"))
                elif event_name == BASICAPI_UPDATE_DEVICE_INFO_TC:
                    # Payload usually includes toyList (list of devices).
                    toys = (payload or {}).get("toyList", []) if isinstance(payload, dict) else []
                    if not isinstance(toys, list):
                        return
                    next_map: dict[str, dict[str, Any]] = {}
                    for toy in toys:
                        if not isinstance(toy, dict):
                            continue
                        tid = toy.get("id")
                        if not tid:
                            continue
                        tid_s = str(tid)
                        connected = toy.get("connected", True)
                        if isinstance(connected, bool) and not connected:
                            # Keep only connected toys by default to match LAN behavior.
                            continue
                        # Normalize into keys expected by ToyInfo/GetToysResponse.
                        next_map[tid_s] = {
                            "id": tid_s,
                            "name": toy.get("name") or toy.get("nickname") or tid_s,
                            "nickName": toy.get("nickname"),
                            "toyType": toy.get("toyType") or toy.get("toy_type") or None,
                            "type": toy.get("toyType") or None,
                            "version": toy.get("hVersion") or toy.get("version") or None,
                            "battery": toy.get("battery"),
                            "status": "1" if connected else "0",
                            "shortFunctionNames": toy.get("shortFunctionNames"),
                            "fullFunctionNames": toy.get("fullFunctionNames"),
                        }
                    self._toys_by_id = next_map
                    self._toy_list_updated_at = asyncio.get_running_loop().time()
            except Exception:  # pylint: disable=broad-exception-caught
                _logger.exception("Socket event parse error for %s", event_name)

        # Non-blocking: connection + ping/recv loops in background.
        self._socket = SocketAPIClient(
            ws_url,
            use_local_commands=bool(self._cfg.socket_use_local_commands),
            app_name=self._cfg.app_name,
            on_socket_io_connected=on_connected,
            on_event=on_event,
        )

        # Use reconnect loop for 24/7-like behavior in the Windows exe.
        self._disconnected_event.clear()
        self._runner_task = self._socket.start_background(auto_reconnect=True, retry_delay=5.0)

    async def aclose(self) -> None:
        if self._socket is None:
            return
        try:
            self._socket.disconnect()
        finally:
            self._disconnected_event.set()

        if self._runner_task is not None:
            self._runner_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._runner_task

        self._socket = None
        self._runner_task = None

    def _require_local_client(self) -> Any:
        if not self._socket:
            raise ValueError("Socket client not initialized.")
        lan = getattr(self._socket, "_lan_client", None)
        if lan is None:
            raise ValueError(
                "Pattern/Preset require local command routing. "
                "Enable LOVENSE_SOCKET_USE_LOCAL_COMMANDS=1 and ensure the device "
                "provides local info."
            )
        return lan

    async def get_toys(
        self, timeout: float | None = None, *, query_battery: bool = True
    ) -> GetToysResponse:
        _ = timeout
        _ = query_battery  # Socket toys include battery fields on most devices.

        # Convert internal dict into ToyInfo rows via GetToysResponse validator.
        toy_rows: list[dict[str, Any]] = []
        for tid in sorted(self._toys_by_id):
            toy = dict(self._toys_by_id[tid])
            if toy.get("nickName") is None and toy.get("name") is not None:
                toy["nickName"] = toy.get("name")
            toy_rows.append(toy)
        return GetToysResponse.model_validate({"data": {"toys": toy_rows}})

    async def function_request(
        self,
        actions: dict[str | Actions, int | float],
        time: float = 0,
        loop_on_time: float | None = None,
        loop_off_time: float | None = None,
        toy_id: str | list[str] | None = None,
        stop_previous: bool | None = None,
        timeout: float | None = None,
        *,
        wait_for_completion: bool = True,
    ) -> CommandResponse:
        _ = timeout
        action_dict = clamp_function_actions(actions)
        action_str = ",".join(f"{k}:{v}" for k, v in action_dict.items())
        if self._socket is None:
            raise ValueError("Socket client not initialized.")

        # If local client exists we can use the same semantics as AsyncLANClient.
        lan = getattr(self._socket, "_lan_client", None)
        if lan is not None:
            resp = await lan.function_request(
                action_dict,
                time=time,
                loop_on_time=loop_on_time,
                loop_off_time=loop_off_time,
                toy_id=toy_id,
                stop_previous=stop_previous,
                wait_for_completion=wait_for_completion,
            )
            return resp

        # WebSocket path: use the socket's Function action string.
        try:
            stop_prev_int: int | None = None
            if stop_previous is not None:
                stop_prev_int = 1 if stop_previous else 0
            if wait_for_completion:
                await self._socket.send_command_await(
                    "Function",
                    action_str,
                    time_sec=time,
                    toy=toy_id,
                    loop_running_sec=loop_on_time,
                    loop_pause_sec=loop_off_time,
                    stop_previous=stop_prev_int,
                )
            else:
                self._socket.send_command(
                    "Function",
                    action_str,
                    time_sec=time,
                    toy=toy_id,
                    loop_running_sec=loop_on_time,
                    loop_pause_sec=loop_off_time,
                    stop_previous=stop_prev_int,
                )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ValueError(f"Socket Function command failed: {exc}") from exc

        return CommandResponse(code=200, type="OK", result=True, data={"transport": "socket"})

    async def stop(
        self, toy_id: str | list[str] | None = None, timeout: float | None = None
    ) -> CommandResponse:
        if self._socket is None:
            raise ValueError("Socket client not initialized.")

        lan = getattr(self._socket, "_lan_client", None)
        if lan is not None:
            resp = await lan.stop(toy_id, timeout=timeout)
            return resp

        try:
            await self._socket.send_command_await("Function", "Stop", time_sec=0, toy=toy_id)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ValueError(f"Socket stop failed: {exc}") from exc
        return CommandResponse(code=200, type="OK", result=True, data={"transport": "socket"})

    async def pattern_request(
        self,
        pattern: list[int],
        actions: list[str | Actions] | None = None,
        interval: int = 100,
        time: float = 0,
        toy_id: str | list[str] | None = None,
        timeout: float | None = None,
        *,
        wait_for_completion: bool = True,
    ) -> CommandResponse:
        # We only support it via local HTTPS forwarding (AsyncLANClient),
        # because SocketAPIClient action-string mapping is not implemented here.
        lan = self._require_local_client()
        resp = await lan.pattern_request(
            pattern,
            actions=actions,  # AsyncLANClient accepts list[str|Actions] per its signature.
            interval=interval,
            time=time,
            toy_id=toy_id,
            timeout=timeout,
            wait_for_completion=wait_for_completion,
        )
        return resp

    async def preset_request(
        self,
        name: str | Presets,
        time: float = 0,
        toy_id: str | list[str] | None = None,
        timeout: float | None = None,
        *,
        open_ended: bool = False,
        wait_for_completion: bool = True,
    ) -> CommandResponse:
        lan = self._require_local_client()
        resp = await lan.preset_request(
            name,
            time=time,
            toy_id=toy_id,
            timeout=timeout,
            open_ended=open_ended,
            wait_for_completion=wait_for_completion,
        )
        return resp
