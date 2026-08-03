"""Toy inventory and active scheduler rows."""

from __future__ import annotations

from typing import Any

from fastapi.exceptions import HTTPException
from fastapi.param_functions import Query
from fastapi.routing import APIRouter

from lovensepy import LovenseError

from ..deps import Backend, Scheduler
from ..util import as_dict

router = APIRouter(tags=["toys"])


@router.get(
    "/toys",
    summary="Toy list (GetToys shape)",
    description=(
        "Live call to the active transport(s) — never cached (see `GET /state` for the "
        "cached view used by dashboards).\n\n"
        "In **ble** mode each toy's ``nickName`` is resolved from packaged ToyConfig "
        "(firmware-aware rules, then flat map, then UART detail fallback). Dry-run the "
        "resolver with **POST /ble/branding/resolve**."
    ),
)
async def get_toys(
    backend: Backend,
    battery: bool = Query(
        default=True,
        description="Query battery per toy. On BLE this costs one UART round-trip per device.",
    ),
) -> dict[str, Any]:
    try:
        response = await backend.get_toys(query_battery=battery)
        return as_dict(response)
    except LovenseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/tasks",
    summary="Active scheduler rows",
    response_description=(
        "Each item includes started_at (UTC ISO-8601) and started_monotonic_sec "
        "(time.monotonic() snapshot for remaining_sec math). "
        "kind=function_loop rows track POST /command/function with "
        "loop_on_time / loop_off_time."
    ),
)
async def list_tasks(scheduler: Scheduler) -> dict[str, Any]:
    return {"tasks": await scheduler.list_tasks()}
