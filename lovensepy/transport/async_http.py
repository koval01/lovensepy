"""
Async HTTP transport: POST JSON to Lovense command endpoint.

This mirrors :class:`lovensepy.transport.http.HttpTransport` but uses
``httpx.AsyncClient`` so LAN/Server clients can be used without blocking an
event loop.
"""

from __future__ import annotations

import json
import logging as py_logging
import threading
from typing import Any

import httpx

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
        self._clients: dict[bool, httpx.AsyncClient] = {}
        self._clients_lock = threading.Lock()

    def _get_client(self, verify: bool) -> httpx.AsyncClient:
        with self._clients_lock:
            client = self._clients.get(verify)
            if client is None:
                client = httpx.AsyncClient(verify=verify, timeout=self.timeout)
                self._clients[verify] = client
            return client

    async def aclose(self) -> None:
        """Close all underlying HTTP sessions."""
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()

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

        try:
            client = self._get_client(verify)
            resp = await client.post(
                self.endpoint,
                json=payload,
                headers=self.headers,
                timeout=timeout,
            )
        except httpx.ConnectError as e:
            _logger.debug("HTTP connect error: %s", e)
            raise LovenseDeviceOfflineError(
                f"Failed to connect to {self.endpoint}",
                endpoint=self.endpoint,
                payload=payload,
            ) from e
        except httpx.TimeoutException as e:
            _logger.debug("HTTP timeout: %s", e)
            raise LovenseTimeoutError(
                f"Timed out while calling {self.endpoint}",
                endpoint=self.endpoint,
                payload=payload,
            ) from e
        except httpx.HTTPError as e:
            _logger.debug("HTTP request error: %s", e)
            raise LovenseNetworkError(
                f"HTTP request failed for {self.endpoint}",
                endpoint=self.endpoint,
                payload=payload,
            ) from e

        if resp.status_code != 200:
            if resp.status_code in (401, 403):
                raise LovenseAuthError(
                    f"Authentication failed (HTTP {resp.status_code}) for {self.endpoint}",
                    endpoint=self.endpoint,
                    payload=payload,
                )
            _logger.debug("HTTP non-200 status: %s", resp.status_code)
            raise LovenseNetworkError(
                f"Non-200 response (HTTP {resp.status_code}) for {self.endpoint}",
                endpoint=self.endpoint,
                payload=payload,
            )

        try:
            return resp.json()
        except (json.JSONDecodeError, ValueError) as e:
            raise LovenseResponseParseError(
                f"Failed to decode JSON response from {self.endpoint}",
                endpoint=self.endpoint,
                payload=payload,
            ) from e
