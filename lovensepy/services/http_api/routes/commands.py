"""Control commands: function levels, presets, patterns and stops."""

from __future__ import annotations

from typing import Any

from fastapi.exceptions import HTTPException
from fastapi.routing import APIRouter

from lovensepy import LovenseError

from ..deps import Runtime, Scheduler
from ..errors import raise_api_error
from ..models import (
    PATTERN_TEMPLATES,
    FunctionCommand,
    PatternCommand,
    PatternTemplate,
    PresetCommand,
    StopFeatureBody,
    StopFeaturesBatchBody,
    StopToyBody,
    StopToysBatchBody,
    pattern_session_signature,
)
from ..util import as_dict

router = APIRouter(prefix="/command", tags=["commands"])


@router.post(
    "/function",
    summary="Set motor levels",
    description=(
        "Each action key is scheduled independently, so two clients can hold different "
        "motors of the same toy. `time=0` holds until stopped; `loop_on_time` / "
        "`loop_off_time` delegate pulsing to the device."
    ),
)
async def function_command(
    runtime: Runtime, scheduler: Scheduler, payload: FunctionCommand
) -> dict[str, Any]:
    try:
        result = await scheduler.schedule_function(
            payload.toy_id,
            payload.actions,
            payload.time,
            stop_previous=payload.stop_previous,
            loop_on_time=payload.loop_on_time,
            loop_off_time=payload.loop_off_time,
        )
    except Exception as exc:
        raise_api_error(exc)
    runtime.bump()
    return result


@router.post(
    "/preset",
    summary="Play a built-in preset",
    description=(
        "Re-posting the same preset for the same toy extends the running session instead "
        "of restarting it."
    ),
)
async def preset_command(
    runtime: Runtime, scheduler: Scheduler, payload: PresetCommand
) -> dict[str, Any]:
    backend = runtime.backend
    preset_name = str(payload.name)

    existing = await scheduler.find_matching_preset_session(payload.toy_id, preset_name)
    if existing:
        try:
            extended = await scheduler.extend_session(existing, float(payload.time))
        except Exception as exc:
            raise_api_error(exc, value_error_status=404)
        runtime.bump()
        return extended

    if payload.toy_id:
        await scheduler.cancel_every_slot_for_toy(payload.toy_id)
    else:
        await scheduler.cancel_all_slots()

    try:
        response = as_dict(
            await backend.preset_request(
                payload.name,
                time=payload.time,
                toy_id=payload.toy_id,
                wait_for_completion=False,
            )
        )
    except Exception as exc:
        raise_api_error(exc)

    try:
        response["scheduler_task_id"] = await scheduler.track_session(
            kind="preset",
            toy_id=payload.toy_id,
            duration=float(payload.time),
            detail={"preset": preset_name},
        )
        response["renewed"] = False
        response["lovense_resent"] = True
    except Exception as exc:
        if isinstance(exc, RuntimeError) and str(exc) == "scheduler_closed":
            return response
        raise_api_error(exc)
    runtime.bump()
    return response


@router.post(
    "/pattern",
    summary="Play a level sequence",
    description=(
        "Provide either `pattern` (0..20 levels, max 50 steps) or a `template`. Re-posting "
        "an identical pattern for the same toy extends the running session."
    ),
)
async def pattern_command(
    runtime: Runtime, scheduler: Scheduler, payload: PatternCommand
) -> dict[str, Any]:
    backend = runtime.backend
    pattern = (
        payload.pattern
        if payload.pattern is not None
        else PATTERN_TEMPLATES[payload.template or PatternTemplate.SOFT]
    )
    signature = pattern_session_signature(
        pattern,
        interval=payload.interval,
        actions=payload.actions,
        template=payload.template,
    )

    existing = await scheduler.find_matching_pattern_session(payload.toy_id, signature)
    if existing:
        try:
            extended = await scheduler.extend_session(existing, float(payload.time))
        except Exception as exc:
            raise_api_error(exc, value_error_status=404)
        runtime.bump()
        return extended

    if payload.toy_id:
        await scheduler.cancel_every_slot_for_toy(payload.toy_id)
    else:
        await scheduler.cancel_all_slots()

    try:
        response = as_dict(
            await backend.pattern_request(
                pattern,
                actions=[str(action) for action in payload.actions] if payload.actions else None,
                interval=payload.interval,
                time=payload.time,
                toy_id=payload.toy_id,
                wait_for_completion=False,
            )
        )
    except Exception as exc:
        raise_api_error(exc)

    detail: dict[str, Any] = {
        "interval": payload.interval,
        "pattern_length": len(pattern),
        "pattern_preview": pattern[:16],
        "pattern_session_key": signature,
        "pattern_data": list(pattern),
        "pattern_actions": [str(a) for a in payload.actions] if payload.actions else None,
    }
    if payload.template is not None:
        detail["template"] = str(payload.template)

    try:
        response["scheduler_task_id"] = await scheduler.track_session(
            kind="pattern",
            toy_id=payload.toy_id,
            duration=float(payload.time),
            detail=detail,
        )
        response["renewed"] = False
        response["lovense_resent"] = True
    except Exception as exc:
        if isinstance(exc, RuntimeError) and str(exc) == "scheduler_closed":
            return response
        raise_api_error(exc)
    runtime.bump()
    return response


@router.post("/stop/all", summary="Stop every toy and clear all sessions")
async def stop_all(runtime: Runtime, scheduler: Scheduler) -> dict[str, Any]:
    try:
        result = await scheduler.stop_all()
    except LovenseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    runtime.bump()
    return result


@router.post("/stop/toy", summary="Stop one toy")
async def stop_toy(runtime: Runtime, scheduler: Scheduler, payload: StopToyBody) -> dict[str, Any]:
    try:
        result = await scheduler.stop_toy(payload.toy_id)
    except LovenseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    runtime.bump()
    return result


@router.post("/stop/feature", summary="Zero one motor, keep the others running")
async def stop_feature(
    runtime: Runtime, scheduler: Scheduler, payload: StopFeatureBody
) -> dict[str, Any]:
    try:
        result = await scheduler.stop_feature(payload.toy_id, payload.feature)
    except LovenseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    runtime.bump()
    return result


@router.post("/stop/toys/batch", summary="Stop several toys")
async def stop_toys_batch(
    runtime: Runtime, scheduler: Scheduler, payload: StopToysBatchBody
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for toy_id in payload.toy_ids:
        try:
            results.append(
                {"toy_id": toy_id, "ok": True, "response": await scheduler.stop_toy(toy_id)}
            )
        except LovenseError as exc:
            results.append({"toy_id": toy_id, "ok": False, "error": str(exc)})
    runtime.bump()
    return {"results": results}


@router.post("/stop/features/batch", summary="Zero several motors")
async def stop_features_batch(
    runtime: Runtime, scheduler: Scheduler, payload: StopFeaturesBatchBody
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for item in payload.items:
        try:
            results.append(
                {
                    "toy_id": item.toy_id,
                    "feature": str(item.feature),
                    "ok": True,
                    "response": await scheduler.stop_feature(item.toy_id, item.feature),
                }
            )
        except LovenseError as exc:
            results.append(
                {
                    "toy_id": item.toy_id,
                    "feature": str(item.feature),
                    "ok": False,
                    "error": str(exc),
                }
            )
    runtime.bump()
    return {"results": results}
