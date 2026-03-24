"""Shared aiohttp utilities for sync/async HTTP clients."""

from __future__ import annotations

import asyncio
import ssl
from collections.abc import Coroutine
from typing import Any

import aiohttp

_SYNC_HTTP_MSG = (
    "Cannot run synchronous HTTP from an active event loop; use "
    "AsyncHttpTransport or async clients instead."
)


def run_sync_coro[T](coro: Coroutine[Any, Any, T]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError(_SYNC_HTTP_MSG)


def ssl_for_verify(verify: bool) -> bool | ssl.SSLContext:
    if verify:
        return True
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


async def read_response_json(resp: aiohttp.ClientResponse) -> Any:
    """
    Decode JSON from an aiohttp response without enforcing ``application/json``.

    Lovense LAN ``/command`` often returns JSON with ``text/plain`` or other
    MIME types. :meth:`aiohttp.ClientResponse.json` defaults to requiring
    ``application/json`` and raises :exc:`aiohttp.ContentTypeError` otherwise.
    """
    return await resp.json(content_type=None)
