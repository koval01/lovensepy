"""
Async Standard API — By Server client.

Async counterpart of :class:`lovensepy.standard.server.ServerClient` using
``httpx.AsyncClient`` via :class:`lovensepy.transport.async_http.AsyncHttpTransport`.
"""

from __future__ import annotations

import json
import logging as py_logging
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from .._constants import FUNCTION_RANGES, SERVER_ERROR_CODES, Actions, Presets
from .._models import CommandResponse, GetToyNameResponse, GetToysResponse, PatternV2Action
from ..exceptions import LovenseError, LovenseResponseParseError
from ..transport import AsyncHttpTransport
from .async_base import LovenseAsyncControlClient

__all__ = ["AsyncServerClient"]

SERVER_COMMAND_URL = "https://api.lovense-api.com/api/lan/v2/command"

_ResponseModelT = TypeVar("_ResponseModelT", bound=BaseModel)

_logger = py_logging.getLogger(__name__)


def _action_letter_pattern(action: str | Actions) -> str:
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


def _actions_to_rule_letters(actions: list[str | Actions] | None) -> str:
    if not actions or Actions.ALL in actions:
        return ""
    letters: list[str] = []
    valid = {"v", "r", "p", "t", "f", "s", "d", "o", "st"}
    for a in actions:
        letter = _action_letter_pattern(a)
        if letter and letter in valid and letter not in letters:
            letters.append(letter)
    return ",".join(letters) if letters else ""


class AsyncServerClient(LovenseAsyncControlClient):
    """Standard API Server client (async)."""

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

        self._transport = AsyncHttpTransport(
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

    async def aclose(self) -> None:
        """Close underlying HTTP sessions."""
        await self._transport.aclose()

    async def __aenter__(self) -> AsyncServerClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        await self.aclose()
        return False

    async def send_command(
        self,
        command_data: dict[str, Any],
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Send command to Lovense server API."""
        timeout = timeout or self.timeout
        cmd = dict(command_data)

        # Clamp timeSec for non-zero values (API constraint, same as LAN)
        if (ts := cmd.get("timeSec")) is not None and ts != 0:
            cmd["timeSec"] = max(1.0, min(float(ts), 6000.0))

        payload = {**self._base_payload(), **cmd}
        self.last_command = payload

        data = await self._transport.post(payload, timeout=timeout)
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
        """Send Function command."""
        _ = wait_for_completion  # BLE-only; HTTP returns when the call completes.
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

    async def get_toys(
        self,
        timeout: float | None = None,
        *,
        query_battery: bool = True,
    ) -> GetToysResponse:
        """Get toys for this ``uid`` (same command as :class:`AsyncLANClient`)."""
        _ = query_battery
        return self._validate_response(
            await self.send_command({"command": "GetToys"}, timeout=timeout),
            GetToysResponse,
        )

    async def get_toys_name(self, timeout: float | None = None) -> GetToyNameResponse:
        """Get toy display names."""
        return self._validate_response(
            await self.send_command({"command": "GetToyName"}, timeout=timeout),
            GetToyNameResponse,
        )

    async def stop(
        self, toy_id: str | list[str] | None = None, timeout: float | None = None
    ) -> CommandResponse:
        """Stop all toys."""
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
        """Send Pattern with raw ``strength`` and ``rule`` strings."""
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
        """Pattern from a strength list (like LAN) or raw ``rule`` + ``strength`` strings."""
        if isinstance(pattern, list):
            if actions is not None and not isinstance(actions, list):
                raise TypeError(
                    "pattern_request([levels], actions=...) — `actions` must be a list or None"
                )
            act_list = actions or [Actions.ALL]
            pat = pattern[:50]
            pat = [min(max(0, n), 20) for n in pat]
            interval_clamped = min(max(interval, 100), 1000)
            letters = _actions_to_rule_letters(act_list)
            rule = (
                f"V:1;F:{letters};S:{interval_clamped}#"
                if letters
                else f"V:1;F:;S:{interval_clamped}#"
            )
            strength = ";".join(map(str, pat))
            return await self.pattern_request_raw(
                strength,
                rule,
                time=time,
                toy_id=toy_id,
                timeout=timeout,
                wait_for_completion=wait_for_completion,
            )
        if isinstance(pattern, str):
            if not isinstance(actions, str):
                raise TypeError(
                    "pattern_request(rule, strength, ...) requires `strength` as second "
                    "positional argument"
                )
            return await self.pattern_request_raw(
                actions,
                pattern,
                time=time,
                toy_id=toy_id,
                timeout=timeout,
                wait_for_completion=wait_for_completion,
            )
        raise TypeError("pattern_request first argument must be a list of levels or a rule string")

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
        """Send Preset command."""
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
        """Position command for supported hardware (same JSON as :class:`AsyncLANClient`)."""
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
        payload: dict[str, Any] = {"command": "PatternV2", "type": "Stop", "apiVer": 1}
        if toy_id is not None:
            payload["toy"] = toy_id
        return self._validate_response(
            await self.send_command(payload, timeout=timeout), CommandResponse
        )

    async def pattern_v2_sync_time(self, timeout: float | None = None) -> CommandResponse:
        return self._validate_response(
            await self.send_command(
                {"command": "PatternV2", "type": "SyncTime", "apiVer": 1},
                timeout=timeout,
            ),
            CommandResponse,
        )

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
        """Async context manager: auto-stop on exit."""

        def __init__(
            self,
            client: AsyncServerClient,
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
    ) -> AsyncServerClient._PlayContextManager:
        """Async: start a Function command on enter and stop on exit."""
        return AsyncServerClient._PlayContextManager(
            self,
            actions,
            time=time,
            loop_on_time=loop_on_time,
            loop_off_time=loop_off_time,
            toy_id=toy_id,
            stop_previous=stop_previous,
            timeout=timeout,
        )
