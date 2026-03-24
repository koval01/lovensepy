"""
Async HTTP transport: POST JSON to Lovense command endpoint.

This mirrors :class:`lovensepy.transport.http.HttpTransport` but uses
:class:`aiohttp.ClientSession` so LAN/Server clients can be used without blocking an
event loop.
"""

from __future__ import annotations

import json
import logging as py_logging
import threading
from typing import Any

import aiohttp

from .._aiohttp_helpers import read_response_json, ssl_for_verify
from .._http_identity import merge_http_headers
from ..exceptions import (
    LovenseAuthError,
    LovenseDeviceOfflineError,
    LovenseNetworkError,
    LovenseResponseParseError,
    LovenseTimeoutError,
)

__all__ = ["AsyncHttpTransport"]

_logger = py_logging.getLogger(__name__)


class AsyncHttpTransport:
    """HTTP client for Lovense command API (async)."""

    def __init__(
        self,
        endpoint: str,
        headers: dict[str, str] | None = None,
        timeout: float = 10.0,
        verify: bool = True,
    ) -> None:
        self.endpoint = endpoint
        self.headers = merge_http_headers(headers)
        self.timeout = timeout
        self.verify = verify
        self._sessions: dict[bool, aiohttp.ClientSession] = {}
        self._clients_lock = threading.Lock()

    def _get_session(self, verify: bool) -> aiohttp.ClientSession:
        with self._clients_lock:
            session = self._sessions.get(verify)
            if session is None:
                connector = aiohttp.TCPConnector(ssl=ssl_for_verify(verify))
                session = aiohttp.ClientSession(connector=connector, headers=self.headers)
                self._sessions[verify] = session
            return session

    async def aclose(self) -> None:
        """Close all underlying HTTP sessions."""
        for session in self._sessions.values():
            await session.close()
        self._sessions.clear()

    async def post(
        self,
        payload: dict[str, Any],
        timeout: float | None = None,
        verify: bool | None = None,
    ) -> dict[str, Any]:
        """
        POST JSON payload to endpoint. Raises typed Lovense errors.
        """
        timeout = timeout or self.timeout
        verify = verify if verify is not None else self.verify

        _logger.debug("HTTP payload: %s", payload)

        session = self._get_session(verify)
        client_timeout = aiohttp.ClientTimeout(total=timeout)

        try:
            async with session.post(
                self.endpoint,
                json=payload,
                timeout=client_timeout,
            ) as resp:
                status = resp.status
                try:
                    data = await read_response_json(resp)
                except (json.JSONDecodeError, ValueError, aiohttp.ContentTypeError) as e:
                    raise LovenseResponseParseError(
                        f"Failed to decode JSON response from {self.endpoint}",
                        endpoint=self.endpoint,
                        payload=payload,
                    ) from e
        except aiohttp.ClientConnectorError as e:
            _logger.debug("HTTP connect error: %s", e)
            raise LovenseDeviceOfflineError(
                f"Failed to connect to {self.endpoint}",
                endpoint=self.endpoint,
                payload=payload,
            ) from e
        except (TimeoutError, aiohttp.ServerTimeoutError) as e:
            _logger.debug("HTTP timeout: %s", e)
            raise LovenseTimeoutError(
                f"Timed out while calling {self.endpoint}",
                endpoint=self.endpoint,
                payload=payload,
            ) from e
        except aiohttp.ClientError as e:
            _logger.debug("HTTP request error: %s", e)
            raise LovenseNetworkError(
                f"HTTP request failed for {self.endpoint}",
                endpoint=self.endpoint,
                payload=payload,
            ) from e

        if status != 200:
            if status in (401, 403):
                raise LovenseAuthError(
                    f"Authentication failed (HTTP {status}) for {self.endpoint}",
                    endpoint=self.endpoint,
                    payload=payload,
                )
            _logger.debug("HTTP non-200 status: %s", status)
            raise LovenseNetworkError(
                f"Non-200 response (HTTP {status}) for {self.endpoint}",
                endpoint=self.endpoint,
                payload=payload,
            )

        return data
