"""
Standard API — LAN (Game Mode) client.

Lovense Remote App > Discover > Game Mode > Enable LAN
Use Local IP and Port from the app.

Architecture:
- Business logic: command building, payloads, response parsing (this module)
- Transport: HTTP client (lovensepy.transport)
- Security: certificate fingerprint verification (lovensepy.security)
"""

import json
import logging as py_logging
from typing import Any, TypeVar
from urllib.parse import urlparse

from pydantic import BaseModel, ValidationError

from .._command_utils import (
    actions_to_rule_letters,
    clamp_function_actions,
    clamp_time_sec_in_payload,
    parse_nested_json,
)
from .._constants import ERROR_CODES, Actions, Presets
from .._models import (
    CommandResponse,
    GetToyNameResponse,
    GetToysResponse,
    PatternV2Action,
)
from .._utils import ip_to_domain
from ..exceptions import LovenseAuthError, LovenseError, LovenseResponseParseError
from ..security import LOVENSE_HTTPS_FINGERPRINT, verify_cert_fingerprint
from ..transport import HttpTransport

__all__ = ["LANClient", "LOVENSE_HTTPS_FINGERPRINT"]

_ResponseModelT = TypeVar("_ResponseModelT", bound=BaseModel)

_logger = py_logging.getLogger(__name__)


class LANClient:
    """
    Standard API LAN (Game Mode) client.

    Business logic: command building, payloads, response parsing.
    Uses HttpTransport for network, security module for cert verification.
    """

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

        self._transport = HttpTransport(
            endpoint=endpoint,
            headers={"X-platform": app_name},
            timeout=timeout,
            verify=verify_ssl,
        )
        self._fingerprint_verified: set[tuple[str, int]] = set()

    @property
    def api_endpoint(self) -> str:
        """Endpoint URL for backward compatibility."""
        return self._transport.endpoint

    def _ensure_fingerprint_verified(self) -> bool:
        """For HTTPS with verify_ssl=False: verify cert fingerprint before request."""
        if self._verify_ssl:
            return True
        parsed = urlparse(self._transport.endpoint)
        if parsed.scheme != "https":
            return True
        host, port = parsed.hostname, parsed.port or 443
        if (host, port) in self._fingerprint_verified:
            return True
        if not verify_cert_fingerprint(host, port, LOVENSE_HTTPS_FINGERPRINT, self.timeout):
            return False
        self._fingerprint_verified.add((host, port))
        return True

    @classmethod
    def from_device_info(
        cls,
        app_name: str,
        domain: str,
        https_port: int = 30011,
        **kwargs: Any,
    ) -> "LANClient":
        """Create client from Socket API device info (basicapi_update_device_info_tc)."""
        return cls(app_name, domain=domain, ssl_port=https_port, **kwargs)

    def send_command(
        self,
        command_data: dict[str, Any],
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Send a JSON command to the app. Business logic: clamp timeSec, delegate to transport."""
        timeout = timeout or self.timeout
        cmd = clamp_time_sec_in_payload(command_data)

        self.last_command = cmd

        # Security: fingerprint verification when verify_ssl=False
        verify = self._verify_ssl
        if not verify:
            if not self._ensure_fingerprint_verified():
                _logger.warning("Certificate fingerprint mismatch")
                raise LovenseAuthError(
                    "Certificate fingerprint mismatch; refusing to send command to the endpoint",
                    endpoint=self._transport.endpoint,
                    payload=cmd,
                )

        data = self._transport.post(cmd, timeout=timeout, verify=verify)

        parsed = parse_nested_json(data)
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
        return clamp_function_actions(actions)

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

    def function_request(
        self,
        actions: dict[str | Actions, int | float],
        time: float = 0,
        loop_on_time: float | None = None,
        loop_off_time: float | None = None,
        toy_id: str | list[str] | None = None,
        stop_previous: bool | None = None,
    ) -> CommandResponse:
        """Send a Function command."""
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

    def stop(self, toy_id: str | list[str] | None = None) -> CommandResponse:
        """Stop all toy functions."""
        payload: dict[str, Any] = {
            "command": "Function",
            "action": "Stop",
            "timeSec": 0,
            "apiVer": 1,
        }
        if toy_id is not None:
            payload["toy"] = toy_id
        return self._validate_response(self.send_command(payload), CommandResponse)

    class _PlayContextManager:
        """Context manager: start a function command and auto-stop on exit."""

        def __init__(
            self,
            client: "LANClient",
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
                # Don't mask the original exception raised inside the block.
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
    ) -> "LANClient._PlayContextManager":
        """Send a Function command on enter and stop the toy(s) on exit.

        Example:
            with client.play({Actions.VIBRATE: 10}, time=5):
                ...
        """
        return LANClient._PlayContextManager(
            self,
            actions,
            time=time,
            loop_on_time=loop_on_time,
            loop_off_time=loop_off_time,
            toy_id=toy_id,
            stop_previous=stop_previous,
        )

    def _actions_to_rule_letters(self, actions: list[str | Actions] | None) -> str:
        """Convert actions to F:... rule part. Empty = all functions."""
        return actions_to_rule_letters(actions)

    def pattern_request_raw(
        self,
        strength: str,
        rule: str = "V:1;F:;S:100#",
        time: float = 0,
        toy_id: str | list[str] | None = None,
    ) -> CommandResponse:
        """Send a Pattern command with raw rule and strength strings."""
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

    def pattern_request(
        self,
        pattern: list[int],
        actions: list[str | Actions] | None = None,
        interval: int = 100,
        time: float = 0,
        toy_id: str | list[str] | None = None,
    ) -> CommandResponse:
        """Send a Pattern command with list of strengths."""
        actions = actions or [Actions.ALL]
        pattern = pattern[:50]
        pattern = [min(max(0, n), 20) for n in pattern]
        interval = min(max(interval, 100), 1000)

        letters = self._actions_to_rule_letters(actions)
        rule = f"V:1;F:{letters};S:{interval}#" if letters else f"V:1;F:;S:{interval}#"
        strength = ";".join(map(str, pattern))
        return self.pattern_request_raw(strength, rule, time, toy_id)

    def preset_request(
        self,
        name: str | Presets,
        time: float = 0,
        toy_id: str | list[str] | None = None,
    ) -> CommandResponse:
        """Send a Preset command."""
        payload: dict[str, Any] = {
            "command": "Preset",
            "name": str(name),
            "timeSec": time,
            "apiVer": 1,
        }
        if toy_id is not None:
            payload["toy"] = toy_id
        return self._validate_response(self.send_command(payload), CommandResponse)

    def position_request(
        self,
        value: int,
        toy_id: str | list[str] | None = None,
    ) -> CommandResponse:
        """Position command for Solace Pro (0-100)."""
        payload: dict[str, Any] = {
            "command": "Position",
            "value": str(max(0, min(100, value))),
            "apiVer": 1,
        }
        if toy_id is not None:
            payload["toy"] = toy_id
        return self._validate_response(self.send_command(payload), CommandResponse)

    def pattern_v2_setup(
        self,
        actions: list[dict[str, int]],
    ) -> CommandResponse:
        """PatternV2 Setup: define pattern actions.

        Each action dict must have 'ts' (timestamp ms) and 'pos' (0-100).
        """
        acts = self._parse_pattern_v2_actions(actions)
        payload = {
            "command": "PatternV2",
            "type": "Setup",
            "actions": [a.model_dump() for a in acts],
            "apiVer": 1,
        }
        return self._validate_response(self.send_command(payload), CommandResponse)

    def pattern_v2_play(
        self,
        toy_id: str | list[str] | None = None,
        start_time: int | None = None,
        offset_time: int | None = None,
        time_ms: float | None = None,
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
        return self._validate_response(self.send_command(payload), CommandResponse)

    def pattern_v2_init_play(
        self,
        actions: list[dict[str, int]],
        toy_id: str | list[str] | None = None,
        start_time: int | None = None,
        offset_time: int | None = None,
        stop_previous: int = 0,
    ) -> CommandResponse:
        """PatternV2 InitPlay: setup and play in one call.

        Each action dict must have 'ts' (timestamp ms) and 'pos' (0-100).
        """
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
        return self._validate_response(self.send_command(payload), CommandResponse)

    def pattern_v2_stop(
        self,
        toy_id: str | list[str] | None = None,
    ) -> CommandResponse:
        """PatternV2 Stop."""
        payload: dict[str, Any] = {"command": "PatternV2", "type": "Stop", "apiVer": 1}
        if toy_id is not None:
            payload["toy"] = toy_id
        return self._validate_response(self.send_command(payload), CommandResponse)

    def pattern_v2_sync_time(self) -> CommandResponse:
        """PatternV2 SyncTime: get server time for offset calculation."""
        return self._validate_response(
            self.send_command({"command": "PatternV2", "type": "SyncTime", "apiVer": 1}),
            CommandResponse,
        )

    def get_toys(self) -> GetToysResponse:
        """Get connected toys info."""
        return self._validate_response(self.send_command({"command": "GetToys"}), GetToysResponse)

    def get_toys_name(self) -> GetToyNameResponse:
        """Get connected toy names."""
        return self._validate_response(
            self.send_command({"command": "GetToyName"}), GetToyNameResponse
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
