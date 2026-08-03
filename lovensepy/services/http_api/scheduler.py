"""Per-(toy, feature) scheduling merged to Lovense Function / Preset / Pattern."""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from lovensepy._constants import FUNCTION_RANGES, Actions
from lovensepy.toy_utils import features_for_toy, stop_actions

from .backend import LovenseControlBackend
from .util import as_dict, toy_info_as_dict


class ControlScheduler:
    """Schedules per-(toy, feature) holds and merges snapshots to the control backend."""

    def __init__(self, backend: LovenseControlBackend, *, session_max_sec: float = 60.0) -> None:
        self._backend = backend
        self._session_max_sec = session_max_sec
        self._closed = False
        self._state_lock = asyncio.Lock()
        self._locks: dict[str, asyncio.Lock] = {}
        self._levels: dict[tuple[str, str], float] = {}
        self._tasks: dict[tuple[str, str], asyncio.Task[None]] = {}
        self._session_tasks: dict[str, asyncio.Task[None]] = {}
        self._meta: dict[str, dict[str, Any]] = {}

    @property
    def closed(self) -> bool:
        return self._closed

    def _lock_for(self, toy_id: str) -> asyncio.Lock:
        if toy_id not in self._locks:
            self._locks[toy_id] = asyncio.Lock()
        return self._locks[toy_id]

    async def shutdown(self) -> None:
        async with self._state_lock:
            self._closed = True
            pending = list(self._tasks.values()) + list(self._session_tasks.values())
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        async with self._state_lock:
            self._tasks.clear()
            self._session_tasks.clear()
            self._levels.clear()
            self._meta.clear()

    async def _fetch_toy_dict(self, toy_id: str) -> dict[str, Any] | None:
        # Never query UART battery on the command path — that alone can cost hundreds
        # of milliseconds per slider tick and is already handled by the BLE supervisor.
        response = await self._backend.get_toys(query_battery=False)
        if not response.data:
            return None
        for toy in response.data.toys:
            if toy.id == toy_id:
                return toy_info_as_dict(toy)
        return None

    async def _expand_actions(self, toy_id: str, actions: dict[Actions, float]) -> dict[str, float]:
        if Actions.ALL not in actions:
            return {str(k): float(v) for k, v in actions.items()}
        if len(actions) != 1:
            raise ValueError("When using Actions.ALL, it must be the only key in actions.")
        level = float(actions[Actions.ALL])
        toy = await self._fetch_toy_dict(toy_id)
        if not toy:
            raise ValueError(f"Toy {toy_id!r} not found (GetToys).")
        feats = features_for_toy(toy)
        return {f: level for f in feats}

    async def _cancel_slot(self, toy_id: str, feature: str) -> None:
        key = (toy_id, feature)
        async with self._state_lock:
            old = self._tasks.pop(key, None)
        if old is not None and not old.done():
            old.cancel()
            try:
                await old
            except asyncio.CancelledError:
                pass

    async def cancel_sessions_for_toy(self, toy_id: str | None) -> None:
        async with self._state_lock:
            to_cancel = [
                tid
                for tid, m in list(self._meta.items())
                if m.get("kind") in ("preset", "pattern", "function_loop")
                and m.get("toy_id") == toy_id
            ]
        for tid in to_cancel:
            async with self._state_lock:
                task = self._session_tasks.pop(tid, None)
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            async with self._state_lock:
                self._meta.pop(tid, None)

    async def cancel_all_sessions(self) -> None:
        async with self._state_lock:
            tids = list(self._session_tasks.keys())
        for tid in tids:
            async with self._state_lock:
                task = self._session_tasks.pop(tid, None)
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        async with self._state_lock:
            for tid, m in list(self._meta.items()):
                if m.get("kind") in ("preset", "pattern", "function_loop"):
                    self._meta.pop(tid, None)

    async def cancel_every_slot_for_toy(self, toy_id: str) -> None:
        await self.cancel_sessions_for_toy(toy_id)
        keys = [key for key in self._tasks if key[0] == toy_id]
        for toy_key, feature in keys:
            await self._cancel_slot(toy_key, feature)

    async def cancel_all_function_slots(self) -> None:
        keys = list(self._tasks.keys())
        for toy_id, feature in keys:
            await self._cancel_slot(toy_id, feature)

    async def cancel_all_slots(self) -> None:
        await self.cancel_all_sessions()
        await self.cancel_all_function_slots()

    async def _run_session_until(self, task_id: str) -> None:
        try:
            while True:
                async with self._state_lock:
                    meta = self._meta.get(task_id)
                if not meta:
                    return
                deadline = float(meta["ends_mono"])
                now = time.monotonic()
                rem = deadline - now
                if rem <= 0:
                    break
                await asyncio.sleep(rem)
        except asyncio.CancelledError:
            raise
        finally:
            current = asyncio.current_task()
            async with self._state_lock:
                registered = self._session_tasks.get(task_id)
                if registered is current:
                    self._session_tasks.pop(task_id, None)
                    self._meta.pop(task_id, None)

    async def find_matching_preset_session(
        self, toy_id: str | None, preset_name: str
    ) -> str | None:
        async with self._state_lock:
            for tid, m in list(self._meta.items()):
                if m.get("kind") != "preset":
                    continue
                if m.get("toy_id") != toy_id:
                    continue
                if m.get("preset") != preset_name:
                    continue
                t = self._session_tasks.get(tid)
                if t is not None and not t.done():
                    return tid
            return None

    async def find_matching_pattern_session(self, toy_id: str | None, signature: str) -> str | None:
        async with self._state_lock:
            for tid, m in list(self._meta.items()):
                if m.get("kind") != "pattern":
                    continue
                if m.get("toy_id") != toy_id:
                    continue
                if m.get("pattern_session_key") != signature:
                    continue
                t = self._session_tasks.get(tid)
                if t is not None and not t.done():
                    return tid
            return None

    async def extend_session(self, task_id: str, duration: float) -> dict[str, Any]:
        if self._closed:
            raise RuntimeError("scheduler_closed")
        async with self._state_lock:
            meta = self._meta.get(task_id)
        if not meta:
            raise ValueError("session not found or not extendable")
        if meta.get("kind") == "function_loop":
            raise ValueError("function_loop sessions cannot be extended")
        if meta.get("kind") not in ("preset", "pattern"):
            raise ValueError("session not found or not extendable")

        requested = float(duration)
        if requested <= 0:
            effective = float(self._session_max_sec)
        else:
            effective = requested

        kind = meta.get("kind")
        toy_id_meta = meta.get("toy_id")

        if kind == "preset":
            preset_name = meta.get("preset")
            if not preset_name:
                raise ValueError("preset name missing from session meta")
            await self._backend.preset_request(
                preset_name,
                time=effective,
                toy_id=toy_id_meta,
                wait_for_completion=False,
            )
        elif kind == "pattern":
            pdata = meta.get("pattern_data")
            if not isinstance(pdata, list):
                raise ValueError(
                    "pattern_data missing in session meta (session started before "
                    "full pattern was stored); start the pattern once more to enable extend."
                )
            interval = int(meta.get("interval", 100))
            actions_raw = meta.get("pattern_actions")
            await self._backend.pattern_request(
                pdata,
                actions=actions_raw,
                interval=interval,
                time=effective,
                toy_id=toy_id_meta,
                wait_for_completion=False,
            )
        else:
            raise ValueError("session not extendable")

        now = time.monotonic()
        old_end = float(meta["ends_mono"])
        new_end = max(old_end, now + effective)
        meta["ends_mono"] = new_end
        meta["extension_count"] = int(meta.get("extension_count", 0)) + 1
        meta["last_extended_at"] = datetime.now(UTC).isoformat()
        meta["duration_sec"] = new_end - float(meta["started_monotonic_sec"])
        meta["last_extend_effective_sec"] = effective

        kind_str = str(meta.get("kind", "session"))

        new_task = asyncio.create_task(
            self._run_session_until(task_id),
            name=f"lovense:session:{kind_str}:{toy_id_meta}:wait",
        )
        async with self._state_lock:
            old_task = self._session_tasks.get(task_id)
            self._session_tasks[task_id] = new_task
        if old_task is not None and old_task is not new_task and not old_task.done():
            old_task.cancel()
            try:
                await old_task
            except asyncio.CancelledError:
                pass

        return {
            "renewed": True,
            "scheduler_task_id": task_id,
            "lovense_resent": True,
            "device_extend_time_sec": effective,
            "remaining_sec": max(0.0, new_end - time.monotonic()),
        }

    async def track_session(
        self,
        *,
        kind: Literal["preset", "pattern", "function_loop"],
        toy_id: str | None,
        duration: float,
        detail: dict[str, Any],
    ) -> str:
        if self._closed:
            raise RuntimeError("scheduler_closed")
        task_id = str(uuid.uuid4())
        requested = float(duration)
        if requested <= 0:
            effective = float(self._session_max_sec)
            duration_capped = True
        else:
            effective = requested
            duration_capped = False

        now_mono = time.monotonic()
        started_at = datetime.now(UTC).isoformat()
        async with self._state_lock:
            self._meta[task_id] = {
                "task_id": task_id,
                "kind": kind,
                "toy_id": toy_id,
                "duration_requested_sec": requested,
                "duration_sec": effective,
                "duration_capped_to_max": duration_capped,
                "extension_count": 0,
                "started_at": started_at,
                "started_monotonic_sec": now_mono,
                "ends_mono": now_mono + effective,
                **detail,
            }
        task = asyncio.create_task(
            self._run_session_until(task_id),
            name=f"lovense:session:{kind}:{toy_id}:wait",
        )
        async with self._state_lock:
            self._session_tasks[task_id] = task
        return task_id

    def _clamp_actions(self, actions: dict[str, float]) -> dict[str, float]:
        out: dict[str, float] = {}
        for feat, raw in actions.items():
            lo, hi = FUNCTION_RANGES.get(feat, (0, 20))
            v = int(round(float(raw)))
            out[feat] = float(max(lo, min(hi, v)))
        return out

    async def _apply_snapshot(self, toy_id: str) -> None:
        actions: dict[str, float] = {}
        async with self._state_lock:
            levels = list(self._levels.items())
        for (tid, feat), lvl in levels:
            if tid == toy_id:
                actions[feat] = lvl
        actions = self._clamp_actions(actions)

        # wait_for_completion=False: return as soon as the UART/HTTP write is queued.
        # Slider updates must not block on BLE notify round-trips or post-command sleeps.
        if not actions:
            toy_dict = await self._fetch_toy_dict(toy_id)
            if toy_dict:
                zeros = stop_actions(toy_dict)
                await self._backend.function_request(
                    zeros, time=0, toy_id=toy_id, wait_for_completion=False
                )
            else:
                await self._backend.stop(toy_id)
        else:
            await self._backend.function_request(
                actions, time=0, toy_id=toy_id, wait_for_completion=False
            )

    async def _run_slot(
        self,
        task_id: str,
        toy_id: str,
        feature: str,
        level: float,
        duration: float,
    ) -> None:
        key = (toy_id, feature)
        lock = self._lock_for(toy_id)
        me = asyncio.current_task()
        try:
            async with lock:
                if self._closed:
                    return
                async with self._state_lock:
                    # A newer continuous overwrite may already own this slot.
                    if self._tasks.get(key) is not me:
                        return
                    self._levels[key] = level
                await self._apply_snapshot(toy_id)

            if duration > 0:
                await asyncio.sleep(duration)
            else:
                # Indefinite hold: park until cancelled. Level changes must NOT cancel
                # this task — they overwrite ``_levels`` and re-apply in place.
                wait = asyncio.Event()
                await wait.wait()
        except asyncio.CancelledError:
            raise
        finally:
            async with lock:
                should_apply = False
                async with self._state_lock:
                    # Only silence this motor if we still own the slot. Otherwise a
                    # replacement hold already wrote the next level and a stop here
                    # would open a gap (the "switch contacts" jerk on sliders).
                    if self._tasks.get(key) is me:
                        self._tasks.pop(key, None)
                        self._levels.pop(key, None)
                        should_apply = True
                    self._meta.pop(task_id, None)
                if should_apply:
                    await self._apply_snapshot(toy_id)

    async def schedule_function(
        self,
        toy_id: str,
        actions: dict[Actions, float],
        duration: float,
        *,
        stop_previous: bool,
        loop_on_time: float | None,
        loop_off_time: float | None,
    ) -> dict[str, Any]:
        if self._closed:
            raise RuntimeError("scheduler_closed")
        if loop_on_time is not None or loop_off_time is not None:
            await self.cancel_every_slot_for_toy(toy_id)
            expanded = await self._expand_actions(toy_id, actions)
            response = await self._backend.function_request(
                expanded,
                time=duration,
                loop_on_time=loop_on_time,
                loop_off_time=loop_off_time,
                toy_id=toy_id,
                stop_previous=True,
                wait_for_completion=False,
            )
            out = as_dict(response)
            try:
                out["scheduler_task_id"] = await self.track_session(
                    kind="function_loop",
                    toy_id=toy_id,
                    duration=float(duration),
                    detail={
                        "actions": dict(expanded),
                        "loop_on_time": loop_on_time,
                        "loop_off_time": loop_off_time,
                    },
                )
            except RuntimeError as exc:
                if str(exc) != "scheduler_closed":
                    raise
            return out

        expanded = await self._expand_actions(toy_id, actions)
        if stop_previous:
            await self.cancel_every_slot_for_toy(toy_id)

        created: list[dict[str, Any]] = []
        for feature, level in expanded.items():
            updated = await self._update_or_schedule_slot(
                toy_id, feature, float(level), float(duration)
            )
            created.append(updated)
        return {"scheduled": created, "type": "OK"}

    async def _update_or_schedule_slot(
        self, toy_id: str, feature: str, level: float, duration: float
    ) -> dict[str, Any]:
        """Create a hold slot, or continuously overwrite an indefinite hold.

        Slider drags must never cancel→stop→restart. That sequence opens a gap where
        motors go to zero between the old and new Function write. For ``duration == 0``
        we keep one parked task and only rewrite the level + re-apply the snapshot.
        """
        key = (toy_id, feature)
        lock = self._lock_for(toy_id)

        # Continuous hold (slider / level set until stopped).
        if duration <= 0 and level > 0:
            async with lock:
                async with self._state_lock:
                    existing = self._tasks.get(key)
                    task_id: str | None = None
                    if existing is not None and not existing.done():
                        for tid, meta in self._meta.items():
                            if (
                                meta.get("kind") == "function"
                                and meta.get("toy_id") == toy_id
                                and meta.get("feature") == feature
                                and meta.get("duration_sec", 0) <= 0
                            ):
                                task_id = tid
                                break

                    if existing is None or existing.done() or task_id is None:
                        # First touch (or timed slot ended): park a keeper task. Do not
                        # cancel anything first — there is nothing useful to tear down.
                        task_id = str(uuid.uuid4())
                        now_mono = time.monotonic()
                        meta = {
                            "task_id": task_id,
                            "kind": "function",
                            "toy_id": toy_id,
                            "feature": feature,
                            "level": level,
                            "duration_sec": 0.0,
                            "started_at": datetime.now(UTC).isoformat(),
                            "started_monotonic_sec": now_mono,
                            "ends_mono": None,
                        }
                        self._levels[key] = level
                        self._meta[task_id] = meta
                        task = asyncio.create_task(
                            self._run_slot(task_id, toy_id, feature, level, 0.0),
                            name=f"lovense:{toy_id}:{feature}",
                        )
                        self._tasks[key] = task
                    else:
                        self._levels[key] = level
                        meta = self._meta.get(task_id)
                        if meta is not None:
                            meta["level"] = level
                        else:
                            meta = {"task_id": task_id, "level": level}

                await self._apply_snapshot(toy_id)

            async with self._state_lock:
                return dict(self._meta.get(task_id) or {"task_id": task_id, "level": level})

        # Timed hold, or explicit zero: replace the previous slot.
        await self._cancel_slot(toy_id, feature)
        if duration <= 0 and level <= 0:
            async with lock:
                async with self._state_lock:
                    self._levels.pop(key, None)
                await self._apply_snapshot(toy_id)
            return {
                "task_id": None,
                "kind": "function",
                "toy_id": toy_id,
                "feature": feature,
                "level": 0.0,
                "duration_sec": 0.0,
            }

        task_id = str(uuid.uuid4())
        now_mono = time.monotonic()
        started_at = datetime.now(UTC).isoformat()
        meta = {
            "task_id": task_id,
            "kind": "function",
            "toy_id": toy_id,
            "feature": feature,
            "level": level,
            "duration_sec": duration,
            "started_at": started_at,
            "started_monotonic_sec": now_mono,
            "ends_mono": (now_mono + duration) if duration > 0 else None,
        }
        async with self._state_lock:
            self._levels[key] = level
            self._meta[task_id] = meta
            task = asyncio.create_task(
                self._run_slot(task_id, toy_id, feature, level, duration),
                name=f"lovense:{toy_id}:{feature}",
            )
            self._tasks[key] = task
        return meta

    async def list_tasks(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        rows: list[dict[str, Any]] = []
        async with self._state_lock:
            metas = list(self._meta.values())
        for meta in metas:
            row = dict(meta)
            ends = row.get("ends_mono")
            if ends is not None:
                row["remaining_sec"] = max(0.0, ends - now)
            else:
                row["remaining_sec"] = None
            rows.append(row)
        rows.sort(
            key=lambda r: (
                r.get("toy_id") or "",
                r.get("kind", "function"),
                r.get("feature", ""),
                r.get("task_id", ""),
            )
        )
        return rows

    async def stop_all(self) -> dict[str, Any]:
        await self.cancel_all_slots()
        response = await self._backend.stop()
        return as_dict(response)

    async def stop_toy(self, toy_id: str) -> dict[str, Any]:
        await self.cancel_every_slot_for_toy(toy_id)
        response = await self._backend.stop(toy_id)
        return as_dict(response)

    async def stop_feature(self, toy_id: str, feature: Actions) -> dict[str, Any]:
        feat = str(feature)
        await self._cancel_slot(toy_id, feat)
        lock = self._lock_for(toy_id)
        async with lock:
            self._levels.pop((toy_id, feat), None)
            await self._apply_snapshot(toy_id)
        return {"type": "OK", "toy_id": toy_id, "feature": feat}
