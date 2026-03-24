"""
Standard API — By Server client.

Business logic: command building, payloads (token+uid), response handling.
Transport: HttpTransport (lovensepy.transport).

QR pairing: get_qr_code() for Step 2 of the flow. After user scans,
Lovense POSTs to your Callback URL (configured in dashboard) with uid.
"""

import hashlib
import json
import logging as py_logging
from typing import Any, TypeVar, overload

import aiohttp
from pydantic import BaseModel, ValidationError

from .._aiohttp_helpers import read_response_json, run_sync_coro, ssl_for_verify
from .._command_utils import (
    actions_to_rule_letters,
    clamp_function_actions,
    clamp_time_sec_in_payload,
)
from .._constants import SERVER_ERROR_CODES, Actions, Presets
from .._http_identity import default_http_headers
from .._models import CommandResponse, GetToyNameResponse, GetToysResponse
from ..exceptions import LovenseError, LovenseResponseParseError
from ..transport import HttpTransport

__all__ = ["ServerClient", "get_qr_code"]

SERVER_COMMAND_URL = "https://api.lovense-api.com/api/lan/v2/command"
GET_QR_CODE_URL = "https://api.lovense-api.com/api/lan/getQrCode"

_ResponseModelT = TypeVar("_ResponseModelT", bound=BaseModel)

_logger = py_logging.getLogger(__name__)


def get_qr_code(
    developer_token: str,
    uid: str,
    uname: str | None = None,
    utoken: str | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """
    Get QR code for Standard API Server pairing (Step 2).

    User scans QR with Lovense Remote; Lovense POSTs to your Callback URL
    (configured in developer dashboard) with uid and toy info.

    Args:
        developer_token: From Lovense developer dashboard
        uid: User ID on your application
        uname: User nickname (optional)
        utoken: MD5(uid + salt) for verification (optional). If omitted, uses MD5(uid).
        timeout: Request timeout

    Returns:
        dict with "qr" (image URL), "code" (6-char code for Remote)

    Raises:
        ValueError: If API rejects the request
        aiohttp.ClientError: On network or HTTP errors

    Security note:
        When utoken is omitted, the library uses MD5(uid) as required by the API.
        MD5 is cryptographically weak. For applications where verification matters,
        pass a proper utoken computed as MD5(uid + salt) with your own secret salt.
    """
    payload: dict[str, Any] = {
        "token": developer_token,
        "uid": uid,
        "v": 2,
    }
    if uname is not None:
        payload["uname"] = uname
    if utoken is not None:
        payload["utoken"] = utoken
    else:
        payload["utoken"] = hashlib.md5(uid.encode(), usedforsecurity=False).hexdigest()

    form = {k: str(v) for k, v in payload.items()}

    async def _fetch() -> dict[str, Any]:
        client_timeout = aiohttp.ClientTimeout(total=timeout)
        connector = aiohttp.TCPConnector(ssl=ssl_for_verify(True))
        async with aiohttp.ClientSession(
            connector=connector,
            headers=default_http_headers(),
        ) as session:
            async with session.post(
                GET_QR_CODE_URL,
                data=form,
                timeout=client_timeout,
            ) as resp:
                resp.raise_for_status()
                return await read_response_json(resp)

    data = run_sync_coro(_fetch())
    if data.get("code") != 0 and not data.get("result"):
        raise ValueError(data.get("message", "Failed to get QR code"))
    if not data.get("data"):
        raise ValueError("No QR data in response")
    return data["data"]


class ServerClient:
    """
    Standard API Server client.

    Sends commands via Lovense cloud (HttpTransport). Requires developer token
    and uid from QR code pairing flow.
    """

    def __init__(
        self,
        developer_token: str,
        uid: str,
        timeout: float = 10.0,
    ) -> None:
        self.developer_token = developer_token
        self.uid = uid
        self.timeout = timeout
        self.last_command: dict[str, Any] | None = None
        self.error_codes = SERVER_ERROR_CODES
        self.actions = Actions
        self.presets = Presets

        self._transport = HttpTransport(
            endpoint=SERVER_COMMAND_URL,
            headers={},
            timeout=timeout,
            verify=True,
        )

    @property
    def api_endpoint(self) -> str:
        """Endpoint URL for consistency with LANClient."""
        return self._transport.endpoint

    def _base_payload(self) -> dict[str, Any]:
        return {"token": self.developer_token, "uid": self.uid}

    def send_command(
        self,
        command_data: dict[str, Any],
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Send command to Lovense server API."""
        timeout = timeout or self.timeout
        cmd = clamp_time_sec_in_payload(command_data)

        payload = {**self._base_payload(), **cmd}
        self.last_command = payload

        data = self._transport.post(payload, timeout=timeout)

        _logger.debug(self.decode_response(data))
        return data

    def _validate_response(
        self,
        data: dict[str, Any],
        model: type[_ResponseModelT],
    ) -> _ResponseModelT:
        """Validate a raw command response into a strict Pydantic model."""
        try:
            return model.model_validate(data)
        except ValidationError as e:
            raise LovenseResponseParseError(
                "Failed to validate Lovense API response",
                endpoint=self._transport.endpoint,
                payload=data,
            ) from e

    def _clamp_actions(self, actions: dict[str | Actions, int | float]) -> dict[str, int | float]:
        return clamp_function_actions(actions)

    def function_request(
        self,
        actions: dict[str | Actions, int | float],
        time: float = 0,
        loop_on_time: float | None = None,
        loop_off_time: float | None = None,
        toy_id: str | list[str] | None = None,
        stop_previous: bool | None = None,
    ) -> CommandResponse:
        """Send Function command."""
        clamped = self._clamp_actions(actions)
        action_str = ",".join(f"{k}:{v}" for k, v in clamped.items())
        payload: dict[str, Any] = {
            "command": "Function",
            "action": action_str,
            "timeSec": time,
            "apiVer": 1,
        }
        if loop_on_time is not None:
            payload["loopRunningSec"] = max(loop_on_time, 1)
        if loop_off_time is not None:
            payload["loopPauseSec"] = max(loop_off_time, 1)
        if toy_id is not None:
            payload["toy"] = toy_id
        if stop_previous is not None:
            payload["stopPrevious"] = 1 if stop_previous else 0
        return self._validate_response(self.send_command(payload), CommandResponse)

    def get_toys(self, timeout: float | None = None) -> GetToysResponse:
        """Get toys for this ``uid`` (same command as :class:`LANClient`)."""
        return self._validate_response(
            self.send_command({"command": "GetToys"}, timeout=timeout),
            GetToysResponse,
        )

    def get_toys_name(self, timeout: float | None = None) -> GetToyNameResponse:
        """Get toy display names (same command as :class:`LANClient`)."""
        return self._validate_response(
            self.send_command({"command": "GetToyName"}, timeout=timeout),
            GetToyNameResponse,
        )

    def stop(self, toy_id: str | list[str] | None = None) -> CommandResponse:
        """Stop all toys."""
        payload: dict[str, Any] = {
            "command": "Function",
            "action": "Stop",
            "timeSec": 0,
            "apiVer": 1,
        }
        if toy_id is not None:
            payload["toy"] = toy_id
        return self._validate_response(self.send_command(payload), CommandResponse)

    def pattern_request_raw(
        self,
        strength: str,
        rule: str = "V:1;F:;S:100#",
        time: float = 0,
        toy_id: str | list[str] | None = None,
    ) -> CommandResponse:
        """Send Pattern with raw ``strength`` and ``rule`` strings (same as :class:`LANClient`)."""
        payload: dict[str, Any] = {
            "command": "Pattern",
            "rule": rule,
            "strength": strength,
            "timeSec": time,
            "apiVer": 2,
        }
        if toy_id is not None:
            payload["toy"] = toy_id
        return self._validate_response(self.send_command(payload), CommandResponse)

    @overload
    def pattern_request(
        self,
        pattern: list[int],
        actions: list[str | Actions] | None = None,
        *,
        interval: int = 100,
        time: float = 0,
        toy_id: str | list[str] | None = None,
    ) -> CommandResponse: ...

    @overload
    def pattern_request(
        self,
        rule: str,
        strength: str,
        *,
        time: float = 0,
        toy_id: str | list[str] | None = None,
    ) -> CommandResponse: ...

    def pattern_request(
        self,
        arg1: list[int] | str,
        arg2: list[str | Actions] | str | None = None,
        *,
        interval: int = 100,
        time: float = 0,
        toy_id: str | list[str] | None = None,
    ) -> CommandResponse:
        """Pattern from a strength list (like LAN) or raw ``rule`` + ``strength`` strings."""
        if isinstance(arg1, list):
            if arg2 is not None and not isinstance(arg2, list):
                raise TypeError(
                    "pattern_request([levels], actions=...) — `actions` must be a list or None"
                )
            actions = arg2
            actions = actions or [Actions.ALL]
            pattern = arg1[:50]
            pattern = [min(max(0, n), 20) for n in pattern]
            interval_clamped = min(max(interval, 100), 1000)
            letters = actions_to_rule_letters(actions)
            rule = (
                f"V:1;F:{letters};S:{interval_clamped}#"
                if letters
                else f"V:1;F:;S:{interval_clamped}#"
            )
            strength = ";".join(map(str, pattern))
            return self.pattern_request_raw(strength, rule, time=time, toy_id=toy_id)
        if isinstance(arg1, str):
            if not isinstance(arg2, str):
                raise TypeError(
                    "pattern_request(rule, strength, ...) requires `strength` as second "
                    "positional argument"
                )
            return self.pattern_request_raw(arg2, arg1, time=time, toy_id=toy_id)
        raise TypeError("pattern_request first argument must be a list of levels or a rule string")

    def preset_request(
        self,
        name: str | Presets,
        time: float = 0,
        toy_id: str | list[str] | None = None,
    ) -> CommandResponse:
        """Send Preset command."""
        payload: dict[str, Any] = {
            "command": "Preset",
            "name": str(name),
            "timeSec": time,
            "apiVer": 1,
        }
        if toy_id is not None:
            payload["toy"] = toy_id
        return self._validate_response(self.send_command(payload), CommandResponse)

    def decode_response(self, response: dict[str, Any] | BaseModel | None) -> str:
        """Format response as human-readable string."""
        if response is None:
            return "No response received from the server."
        if isinstance(response, BaseModel):
            response = response.model_dump()
        code = response.get("code")
        msg = self.error_codes.get(code, "Unknown") if isinstance(code, int) else str(code)
        out = f"Server response: code={code}, {msg}\n"
        if (data := response.get("data")) is not None:
            out += f"Data: {json.dumps(data, indent=2)}"
        return out

    class _PlayContextManager:
        """Context manager: start a function command and auto-stop on exit."""

        def __init__(
            self,
            client: "ServerClient",
            actions: dict[str | Actions, int | float],
            *,
            time: float,
            loop_on_time: float | None,
            loop_off_time: float | None,
            toy_id: str | list[str] | None,
            stop_previous: bool | None,
        ) -> None:
            self._client = client
            self._actions = actions
            self._time = time
            self._loop_on_time = loop_on_time
            self._loop_off_time = loop_off_time
            self._toy_id = toy_id
            self._stop_previous = stop_previous
            self._response: CommandResponse | None = None

        def __enter__(self) -> CommandResponse:
            self._response = self._client.function_request(
                self._actions,
                time=self._time,
                loop_on_time=self._loop_on_time,
                loop_off_time=self._loop_off_time,
                toy_id=self._toy_id,
                stop_previous=self._stop_previous,
            )
            return self._response

        def __exit__(self, exc_type, exc, tb) -> bool:
            try:
                self._client.stop(self._toy_id)
            except LovenseError:
                if exc_type is None:
                    raise
            return False

    def play(
        self,
        actions: dict[str | Actions, int | float],
        *,
        time: float = 0,
        loop_on_time: float | None = None,
        loop_off_time: float | None = None,
        toy_id: str | list[str] | None = None,
        stop_previous: bool | None = None,
    ) -> "ServerClient._PlayContextManager":
        """Send a Function command on enter and stop the toy(s) on exit."""
        return ServerClient._PlayContextManager(
            self,
            actions,
            time=time,
            loop_on_time=loop_on_time,
            loop_off_time=loop_off_time,
            toy_id=toy_id,
            stop_previous=stop_previous,
        )
