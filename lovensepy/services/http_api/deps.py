"""FastAPI dependencies that expose the service runtime to route handlers."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi.exceptions import HTTPException
from fastapi.param_functions import Depends
from fastapi.requests import Request

from lovensepy.ble_direct.hub import BleDirectHub

from .access_gate import is_external_request
from .backend import LovenseControlBackend
from .errors import ensure_scheduler_open
from .runtime import ServiceRuntime
from .scheduler import ControlScheduler
from .socket_backend import SocketControlBackend

ViewerRole = Literal["host", "remote"]

_HOST_ONLY_DETAIL = (
    "This action is only available from the local network "
    "(localhost / LAN). Tunnel visitors can control toys, but cannot change "
    "settings, manage Bluetooth pairing, or operate the Cloudflare tunnel."
)


def get_runtime(request: Request) -> ServiceRuntime:
    runtime: ServiceRuntime | None = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="Service is not ready yet.")
    return runtime


Runtime = Annotated[ServiceRuntime, Depends(get_runtime)]


def get_scheduler(runtime: Runtime) -> ControlScheduler:
    return ensure_scheduler_open(runtime.scheduler)


Scheduler = Annotated[ControlScheduler, Depends(get_scheduler)]


def get_backend(runtime: Runtime) -> LovenseControlBackend:
    return runtime.backend


Backend = Annotated[LovenseControlBackend, Depends(get_backend)]


def viewer_role(request: Request) -> ViewerRole:
    """``host`` = LAN / loopback; ``remote`` = public tunnel / external IP."""
    return "remote" if is_external_request(request.scope, request.headers) else "host"


ViewerRoleDep = Annotated[ViewerRole, Depends(viewer_role)]


def require_local_network(request: Request) -> None:
    """Reject Cloudflare / public visitors from admin and setup endpoints."""
    if is_external_request(request.scope, request.headers):
        raise HTTPException(status_code=403, detail=_HOST_ONLY_DETAIL)


# Use as ``dependencies=[Depends(require_local_network)]`` on a router, or
# ``_: HostOnly`` on a single handler.
HostOnly = Annotated[None, Depends(require_local_network)]


def require_ble_hub(runtime: Runtime) -> BleDirectHub:
    """409 instead of 404 when BLE is off, so clients can tell "disabled" from "no route"."""
    if not runtime.cfg.enable_ble or runtime.ble_hub is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "BLE transport is disabled. Start with LOVENSE_SERVICE_MODE=ble|hybrid "
                "(or LOVENSE_ENABLE_BLE=1)."
            ),
        )
    return runtime.ble_hub


BleHub = Annotated[BleDirectHub, Depends(require_ble_hub)]


def require_socket_backend(runtime: Runtime) -> SocketControlBackend:
    if not runtime.cfg.enable_socket or runtime.socket_backend is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Socket API transport is disabled. Provide credentials via POST /config/socket "
                "or LOVENSE_DEV_TOKEN / LOVENSE_UID / LOVENSE_PLATFORM."
            ),
        )
    return runtime.socket_backend


SocketBackend = Annotated[SocketControlBackend, Depends(require_socket_backend)]
