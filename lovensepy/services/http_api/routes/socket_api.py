"""Lovense Socket API (cloud) status and pairing QR."""

from __future__ import annotations

from typing import Any

from fastapi.param_functions import Depends
from fastapi.routing import APIRouter

from ..deps import Runtime, SocketBackend, require_local_network

router = APIRouter(
    prefix="/socket",
    tags=["socket"],
    dependencies=[Depends(require_local_network)],
)


@router.get(
    "/status",
    summary="Socket.IO session and app state",
    description="Returns HTTP 409 when the Socket transport is disabled.",
)
async def socket_status(backend: SocketBackend) -> dict[str, Any]:
    return backend.status_info()


@router.get(
    "/qr",
    summary="Pairing QR handed out by Lovense",
    description=(
        "The user scans this with the Lovense app to link their toys to this service. "
        "Empty until the cloud answers `basicapi_get_qrcode_tc` — poll or watch `/ws`."
    ),
)
async def socket_qr(backend: SocketBackend) -> dict[str, Any]:
    return backend.qr_info


@router.post("/qr/request", summary="Ask Lovense for a fresh pairing QR")
async def socket_qr_request(runtime: Runtime, backend: SocketBackend) -> dict[str, Any]:
    backend.request_qr()
    runtime.bump()
    return {"type": "OK"}
