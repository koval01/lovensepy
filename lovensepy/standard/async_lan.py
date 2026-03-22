"""
Async Standard API — LAN (Game Mode) client.

This mirrors :class:`lovensepy.standard.lan.LANClient` but performs HTTP calls
using ``httpx.AsyncClient`` via :class:`lovensepy.transport.async_http.AsyncHttpTransport`.
"""

from __future__ import annotations

import asyncio
import json
import logging as py_logging
from typing import Any, TypeVar
from urllib.parse import urlparse

from pydantic import BaseModel, ValidationError

from .._constants import ERROR_CODES, FUNCTION_RANGES, Actions, Presets
from .._models import (
    CommandResponse,
    GetToyNameResponse,
    GetToysResponse,
    PatternV2Action,
)
from .._utils import ip_to_domain
from ..exceptions import LovenseAuthError, LovenseError, LovenseResponseParseError
from ..security import LOVENSE_HTTPS_FINGERPRINT, verify_cert_fingerprint
from ..transport import AsyncHttpTransport
from .async_base import LovenseAsyncControlClient

__all__ = ["AsyncLANClient", "LOVENSE_HTTPS_FINGERPRINT"]

_ResponseModelT = TypeVar("_ResponseModelT", bound=BaseModel)

_logger = py_logging.getLogger(__name__)


def _parse_json(data: str | dict | list) -> dict[str, Any] | list | str:
    """Recursively parse nested JSON strings into dicts."""
    if isinstance(data, str):
        try:
            return json.loads(data)
        except ValueError:
            return data
    if isinstance(data, dict):
        return {k: _parse_json(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_parse_json(item) for item in data]
    return data


def _action_letter(action: str | Actions) -> str:
    """Map action to pattern rule letter. v,r,p,t,f,s,d,o,st."""
    if isinstance(action, Actions):
        action = str(action)
    action = str(action).strip().lower()
    mapping = {
        "vibrate": "v",
        "vibrate1": "v",
        "vibrate2": "v",
        "vibrate3": "v",
        "rotate": "r",
        "pump": "p",
        "thrusting": "t",
        "fingering": "f",
        "suction": "s",
        "depth": "d",
        "oscillate": "o",
        "stroke": "st",
    }
    return mapping.get(action, action[0] if action else "")


class AsyncLANClient(LovenseAsyncControlClient):
    """Standard API LAN (Game Mode) async client."""

    def __init__(
        self,
        app_name: str,
        local_ip: str | None = None,
        *,
        domain: str | None = None,
        port: int = 20011,
        ssl_port: int = 30011,
        use_https: bool = False,
        verify_ssl: bool = True,
        timeout: float = 10.0,
    ) -> None:
        self.app_name = app_name
        self.timeout = timeout
        self.last_command: dict[str, Any] | None = None

        # Build endpoint URL
        if domain is not None and not str(domain).strip():
            raise ValueError("domain must not be empty when provided")
        if domain:
            endpoint = f"https://{domain}:{ssl_port}/command"
        elif use_https and local_ip:
            if not verify_ssl:
                endpoint = f"https://{local_ip}:{ssl_port}/command"
            else:
                endpoint = f"https://{ip_to_domain(local_ip)}:{ssl_port}/command"
        elif local_ip:
            endpoint = f"http://{local_ip}:{port}/command"
        else:
            raise ValueError("Provide local_ip or domain")

        self._verify_ssl = verify_ssl
        self.actions = Actions
        self.presets = Presets
        self.error_codes = ERROR_CODES

        self._transport = AsyncHttpTransport(
            endpoint=endpoint,
            headers={"X-platform": app_name},
            timeout=timeout,
            verify=verify_ssl,
        )
        self._fingerprint_verified: set[tuple[str, int]] = set()
        self._fingerprint_lock = asyncio.Lock()

    @property
    def api_endpoint(self) -> str:
        """Endpoint URL for backward compatibility."""
        return self._transport.endpoint

    async def _ensure_fingerprint_verified(self, timeout: float | None = None) -> bool:
        """For HTTPS with verify_ssl=False: verify cert fingerprint before request."""
        if self._verify_ssl:
            return True
        parsed = urlparse(self._transport.endpoint)
        if parsed.scheme != "https":
            return True
        host, port = parsed.hostname, parsed.port or 443
        if host is None:
            return False
        verify_timeout = self.timeout if timeout is None else timeout

        async with self._fingerprint_lock:
            if (host, port) in self._fingerprint_verified:
                return True
            ok = await asyncio.to_thread(
                verify_cert_fingerprint,
                host,
                port,
                LOVENSE_HTTPS_FINGERPRINT,
                verify_timeout,
            )
            if not ok:
                return False
            self._fingerprint_verified.add((host, port))
            return True

    async def aclose(self) -> None:
        """Close underlying HTTP sessions."""
        await self._transport.aclose()

    async def __aenter__(self) -> AsyncLANClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        await self.aclose()
        return False

    @classmethod
    def from_device_info(
        cls,
        app_name: str,
        domain: str,
        https_port: int = 30011,
        **kwargs: Any,
    ) -> AsyncLANClient:
        """Create client from Socket API device info (basicapi_update_device_info_tc)."""
        return cls(app_name, domain=domain, ssl_port=https_port, **kwargs)

    def _parse_command_payload(self, command_data: dict[str, Any]) -> dict[str, Any]:
        """Clamp timeSec for non-zero values (API constraint) and copy."""
        cmd = dict(command_data)
        if (ts := cmd.get("timeSec")) is not None and ts != 0:
            cmd["timeSec"] = max(1.0, min(float(ts), 6000.0))
        return cmd

    async def send_command(
        self,
        command_data: dict[str, Any],
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Send a JSON command to the app. Returns parsed JSON dict."""
        timeout = self.timeout if timeout is None else timeout
        cmd = self._parse_command_payload(command_data)
        self.last_command = cmd

        # Security: fingerprint verification when verify_ssl=False
        verify = self._verify_ssl
        if not verify:
            if not await self._ensure_fingerprint_verified(timeout):
                raise LovenseAuthError(
                    "Certificate fingerprint mismatch; refusing to send command to the endpoint",
                    endpoint=self._transport.endpoint,
                    payload=cmd,
                )

        data = await self._transport.post(cmd, timeout=timeout, verify=verify)
        parsed = _parse_json(data)
        _logger.debug(self.decode_response(parsed))
        return parsed if isinstance(parsed, dict) else {"data": parsed}

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
        """Clamp action values to API ranges."""
        result: dict[str, int | float] = {}
        for action, value in actions.items():
            key = str(action)
            if key in FUNCTION_RANGES:
                lo, hi = FUNCTION_RANGES[key]
                result[key] = int(max(lo, min(hi, value)))
            else:
                result[key] = value
        return result

    def _parse_pattern_v2_actions(self, actions: list[dict[str, int]]) -> list[PatternV2Action]:
        """Parse and validate PatternV2 action dicts. Raises ValueError on invalid input."""
        result: list[PatternV2Action] = []
        for i, a in enumerate(actions):
            if not isinstance(a, dict):
                raise ValueError(
                    f"actions[{i}] must be a dict with 'ts' and 'pos' keys, got {type(a).__name__}"
                )
            if "ts" not in a:
                raise ValueError(f"actions[{i}] missing required key 'ts'")
            if "pos" not in a:
                raise ValueError(f"actions[{i}] missing required key 'pos'")
            try:
                result.append(PatternV2Action(ts=a["ts"], pos=a["pos"]))
            except Exception as e:
                raise ValueError(
                    f"actions[{i}] invalid (ts and pos must be int, pos 0-100): {e}"
                ) from e
        return result

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
        """Send a Function command."""
        _ = wait_for_completion  # BLE-only; LAN returns when the HTTP call completes.
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

        return self._validate_response(
            await self.send_command(payload, timeout=timeout), CommandResponse
        )

    async def stop(
        self, toy_id: str | list[str] | None = None, timeout: float | None = None
    ) -> CommandResponse:
        """Stop all toy functions."""
        payload: dict[str, Any] = {
            "command": "Function",
            "action": "Stop",
            "timeSec": 0,
            "apiVer": 1,
        }
        if toy_id is not None:
            payload["toy"] = toy_id
        return self._validate_response(
            await self.send_command(payload, timeout=timeout), CommandResponse
        )

    def _actions_to_rule_letters(self, actions: list[str | Actions] | None) -> str:
        """Convert actions to F:... rule part. Empty = all functions."""
        if not actions or Actions.ALL in actions:
            return ""
        letters = []
        valid = {"v", "r", "p", "t", "f", "s", "d", "o", "st"}
        for a in actions:
            letter = _action_letter(a)
            if letter and letter in valid and letter not in letters:
                letters.append(letter)
        return ",".join(letters) if letters else ""

    async def pattern_request_raw(
        self,
        strength: str,
        rule: str = "V:1;F:;S:100#",
        time: float = 0,
        toy_id: str | list[str] | None = None,
        timeout: float | None = None,
        *,
        wait_for_completion: bool = True,
    ) -> CommandResponse:
        """Send a Pattern command with raw rule and strength strings."""
        _ = wait_for_completion
        payload: dict[str, Any] = {
            "command": "Pattern",
            "rule": rule,
            "strength": strength,
            "timeSec": time,
            "apiVer": 2,
        }
        if toy_id is not None:
            payload["toy"] = toy_id
        return self._validate_response(
            await self.send_command(payload, timeout=timeout), CommandResponse
        )

    async def pattern_request(
        self,
        pattern: list[int] | str,
        actions: list[str | Actions] | str | None = None,
        interval: int = 100,
        time: float = 0,
        toy_id: str | list[str] | None = None,
        timeout: float | None = None,
        *,
        wait_for_completion: bool = True,
    ) -> CommandResponse:
        """Send a Pattern command with list of strengths."""
        if isinstance(pattern, str):
            raise TypeError(
                "AsyncLANClient.pattern_request expects a list of levels; "
                "for raw rule/strength strings use pattern_request_raw(strength, rule, ...)."
            )
        if actions is not None and not isinstance(actions, list):
            raise TypeError(
                "pattern_request([levels], actions=...) — `actions` must be a list or None"
            )
        actions = actions or [Actions.ALL]
        pattern = pattern[:50]
        pattern = [min(max(0, n), 20) for n in pattern]
        interval = min(max(interval, 100), 1000)

        letters = self._actions_to_rule_letters(actions)
        rule = f"V:1;F:{letters};S:{interval}#" if letters else f"V:1;F:;S:{interval}#"
        strength = ";".join(map(str, pattern))
        return await self.pattern_request_raw(
            strength, rule, time, toy_id, timeout=timeout, wait_for_completion=wait_for_completion
        )

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
        """Send a Preset command."""
        _ = wait_for_completion
        payload: dict[str, Any] = {
            "command": "Preset",
            "name": str(name),
            "timeSec": time,
            "apiVer": 1,
        }
        if open_ended:
            payload["openEnded"] = 1
        if toy_id is not None:
            payload["toy"] = toy_id
        return self._validate_response(
            await self.send_command(payload, timeout=timeout), CommandResponse
        )

    async def position_request(
        self,
        value: int,
        toy_id: str | list[str] | None = None,
        timeout: float | None = None,
    ) -> CommandResponse:
        """Position command for Solace Pro (0-100)."""
        payload: dict[str, Any] = {
            "command": "Position",
            "value": str(max(0, min(100, value))),
            "apiVer": 1,
        }
        if toy_id is not None:
            payload["toy"] = toy_id
        return self._validate_response(
            await self.send_command(payload, timeout=timeout), CommandResponse
        )

    async def pattern_v2_setup(
        self,
        actions: list[dict[str, int]],
        timeout: float | None = None,
    ) -> CommandResponse:
        """PatternV2 Setup: define pattern actions."""
        acts = self._parse_pattern_v2_actions(actions)
        payload = {
            "command": "PatternV2",
            "type": "Setup",
            "actions": [a.model_dump() for a in acts],
            "apiVer": 1,
        }
        return self._validate_response(
            await self.send_command(payload, timeout=timeout), CommandResponse
        )

    async def pattern_v2_play(
        self,
        toy_id: str | list[str] | None = None,
        start_time: int | None = None,
        offset_time: int | None = None,
        time_ms: float | None = None,
        timeout: float | None = None,
    ) -> CommandResponse:
        """PatternV2 Play: play predefined pattern."""
        payload: dict[str, Any] = {"command": "PatternV2", "type": "Play", "apiVer": 1}
        if toy_id is not None:
            payload["toy"] = toy_id
        if start_time is not None:
            payload["startTime"] = start_time
        if offset_time is not None:
            payload["offsetTime"] = offset_time
        if time_ms is not None:
            payload["timeMs"] = time_ms
        return self._validate_response(
            await self.send_command(payload, timeout=timeout), CommandResponse
        )

    async def pattern_v2_init_play(
        self,
        actions: list[dict[str, int]],
        toy_id: str | list[str] | None = None,
        start_time: int | None = None,
        offset_time: int | None = None,
        stop_previous: int = 0,
        timeout: float | None = None,
    ) -> CommandResponse:
        """PatternV2 InitPlay: setup and play in one call."""
        acts = self._parse_pattern_v2_actions(actions)
        payload: dict[str, Any] = {
            "command": "PatternV2",
            "type": "InitPlay",
            "actions": [a.model_dump() for a in acts],
            "apiVer": 1,
            "stopPrevious": stop_previous,
        }
        if toy_id is not None:
            payload["toy"] = toy_id
        if start_time is not None:
            payload["startTime"] = start_time
        if offset_time is not None:
            payload["offsetTime"] = offset_time
        return self._validate_response(
            await self.send_command(payload, timeout=timeout), CommandResponse
        )

    async def pattern_v2_stop(
        self,
        toy_id: str | list[str] | None = None,
        timeout: float | None = None,
    ) -> CommandResponse:
        """PatternV2 Stop."""
        payload: dict[str, Any] = {"command": "PatternV2", "type": "Stop", "apiVer": 1}
        if toy_id is not None:
            payload["toy"] = toy_id
        return self._validate_response(
            await self.send_command(payload, timeout=timeout), CommandResponse
        )

    async def pattern_v2_sync_time(self, timeout: float | None = None) -> CommandResponse:
        """PatternV2 SyncTime: get server time for offset calculation."""
        return self._validate_response(
            await self.send_command(
                {"command": "PatternV2", "type": "SyncTime", "apiVer": 1},
                timeout=timeout,
            ),
            CommandResponse,
        )

    async def get_toys(
        self,
        timeout: float | None = None,
        *,
        query_battery: bool = True,
    ) -> GetToysResponse:
        """Get connected toys info."""
        _ = query_battery  # LAN HTTP has no per-toy UART query; BLE hub uses this flag.
        return self._validate_response(
            await self.send_command({"command": "GetToys"}, timeout=timeout), GetToysResponse
        )

    async def get_toys_name(self, timeout: float | None = None) -> GetToyNameResponse:
        """Get connected toy names."""
        return self._validate_response(
            await self.send_command({"command": "GetToyName"}, timeout=timeout), GetToyNameResponse
        )

    def decode_response(self, response: dict[str, Any] | BaseModel | None) -> str:
        """Format response as human-readable string."""
        if response is None:
            return "No response received from the app."
        if isinstance(response, BaseModel):
            response = response.model_dump()
        rtype = response.get("type", "Not Response")
        code = response.get("code")
        msg = (
            self.error_codes.get(code, "Unknown Error")
            if isinstance(code, int)
            else f"Unknown code {code}"
        )
        out = f"Response from the app: {rtype}\nResponse from the toy: {msg}, {code}\n"
        if (data := response.get("data")) is not None:
            out += f"Data: {json.dumps(data, indent=4)}"
        return out

    class _PlayContextManager:
        """Async context manager: auto-stop on exit."""

        def __init__(
            self,
            client: AsyncLANClient,
            actions: dict[str | Actions, int | float],
            *,
            time: float,
            loop_on_time: float | None,
            loop_off_time: float | None,
            toy_id: str | list[str] | None,
            stop_previous: bool | None,
            timeout: float | None,
        ) -> None:
            self._client = client
            self._actions = actions
            self._time = time
            self._loop_on_time = loop_on_time
            self._loop_off_time = loop_off_time
            self._toy_id = toy_id
            self._stop_previous = stop_previous
            self._timeout = timeout
            self._response: CommandResponse | None = None

        async def __aenter__(self) -> CommandResponse:
            self._response = await self._client.function_request(
                self._actions,
                time=self._time,
                loop_on_time=self._loop_on_time,
                loop_off_time=self._loop_off_time,
                toy_id=self._toy_id,
                stop_previous=self._stop_previous,
                timeout=self._timeout,
            )
            return self._response

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            try:
                await self._client.stop(self._toy_id, timeout=self._timeout)
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
        timeout: float | None = None,
    ) -> AsyncLANClient._PlayContextManager:
        """Async: start a Function command on enter and stop on exit."""
        return AsyncLANClient._PlayContextManager(
            self,
            actions,
            time=time,
            loop_on_time=loop_on_time,
            loop_off_time=loop_off_time,
            toy_id=toy_id,
            stop_previous=stop_previous,
            timeout=timeout,
        )
