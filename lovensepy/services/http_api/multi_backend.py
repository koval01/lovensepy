"""
Multi-backend control for :mod:`lovensepy.services.fastapi`.

The scheduler expects one :class:`lovensepy.services.fastapi.backend.LovenseControlBackend`.
This module provides :class:`CompositeLovenseControlBackend` that merges multiple
backends (LAN, BLE hub, Socket API) and routes commands by `toy_id`.
"""

from __future__ import annotations

import asyncio
from typing import Any

from lovensepy import Actions, Presets
from lovensepy._models import CommandResponse, GetToysResponse

from .backend import LovenseControlBackend


def _dump_response(r: Any) -> Any:
    if hasattr(r, "model_dump"):
        return r.model_dump()
    return r


class CompositeLovenseControlBackend(LovenseControlBackend):
    def __init__(self, backends: dict[str, LovenseControlBackend]) -> None:
        self._backends = dict(backends)

    async def aclose(self) -> None:
        # Not part of the protocol, but used from FastAPI lifespan.
        await asyncio.gather(
            *(
                b.aclose()  # type: ignore[attr-defined]
                for b in self._backends.values()
                if hasattr(b, "aclose")
            ),
            return_exceptions=True,
        )

    async def _get_toys_index(
        self,
    ) -> tuple[dict[str, list[str]], dict[str, dict[str, Any]]]:
        toy_to_backends: dict[str, list[str]] = {}
        toy_dict_by_id: dict[str, dict[str, Any]] = {}

        # Query toys from each backend (in parallel).
        results = await asyncio.gather(
            *(b.get_toys() for b in self._backends.values()),
            return_exceptions=True,
        )

        for (name, _backend), res in zip(self._backends.items(), results):
            if isinstance(res, Exception) or res is None:
                continue
            if not getattr(res, "data", None) or not res.data.toys:
                continue
            for toy in res.data.toys:
                tid = getattr(toy, "id", None)
                if not tid:
                    continue
                toy_to_backends.setdefault(str(tid), []).append(name)
                toy_dict_by_id[str(tid)] = toy.model_dump()
        return toy_to_backends, toy_dict_by_id

    async def get_toys(
        self,
        timeout: float | None = None,
        *,
        query_battery: bool = True,
    ) -> GetToysResponse:
        _ = timeout

        # Query toys from each backend.
        tasks = [
            backend.get_toys(timeout=timeout, query_battery=query_battery)
            for backend in self._backends.values()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        toy_by_id: dict[str, dict[str, Any]] = {}
        for res in results:
            if isinstance(res, Exception) or res is None:
                continue
            if not getattr(res, "data", None) or not res.data.toys:
                continue
            for toy in res.data.toys:
                toy_by_id[str(toy.id)] = toy.model_dump()

        toy_rows = list(toy_by_id.values())
        return GetToysResponse.model_validate({"data": {"toys": toy_rows}})

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
        if toy_id is None:
            responses = await asyncio.gather(
                *(
                    b.function_request(
                        actions,
                        time=time,
                        loop_on_time=loop_on_time,
                        loop_off_time=loop_off_time,
                        toy_id=None,
                        stop_previous=stop_previous,
                        timeout=timeout,
                        wait_for_completion=wait_for_completion,
                    )
                    for b in self._backends.values()
                ),
                return_exceptions=True,
            )
            per: dict[str, Any] = {
                name: _dump_response(r)
                for name, r in zip(self._backends.keys(), responses)
                if not isinstance(r, Exception)
            }
            return CommandResponse(
                code=200,
                type="OK",
                result=True,
                data={"transport": "composite", "per_backend": per},
            )

        # toy_id routes by toy ownership.
        toy_ids = [toy_id] if isinstance(toy_id, str) else list(toy_id)
        toy_to_backends, _ = await self._get_toys_index()

        used: dict[str, list[str]] = {}
        for tid in toy_ids:
            for backend_name in toy_to_backends.get(str(tid), []):
                used.setdefault(backend_name, []).append(str(tid))

        if not used:
            raise ValueError(f"Unknown toy_id(s): {toy_ids}")

        responses = await asyncio.gather(
            *(
                self._backends[name].function_request(
                    actions,
                    time=time,
                    loop_on_time=loop_on_time,
                    loop_off_time=loop_off_time,
                    toy_id=ids,
                    stop_previous=stop_previous,
                    timeout=timeout,
                    wait_for_completion=wait_for_completion,
                )
                for name, ids in used.items()
            ),
            return_exceptions=True,
        )
        per = {
            name: _dump_response(r)
            for (name, _ids), r in zip(used.items(), responses)
            if not isinstance(r, Exception)
        }
        return CommandResponse(
            code=200,
            type="OK",
            result=True,
            data={"transport": "composite", "per_backend": per},
        )

    async def stop(
        self,
        toy_id: str | list[str] | None = None,
        timeout: float | None = None,
    ) -> CommandResponse:
        if toy_id is None:
            responses = await asyncio.gather(
                *(b.stop(toy_id=None, timeout=timeout) for b in self._backends.values()),
                return_exceptions=True,
            )
            per = {
                name: _dump_response(r)
                for name, r in zip(self._backends.keys(), responses)
                if not isinstance(r, Exception)
            }
            return CommandResponse(
                code=200,
                type="OK",
                result=True,
                data={"transport": "composite", "per_backend": per},
            )

        toy_ids = [toy_id] if isinstance(toy_id, str) else list(toy_id)
        toy_to_backends, _ = await self._get_toys_index()

        used: dict[str, list[str]] = {}
        for tid in toy_ids:
            for backend_name in toy_to_backends.get(str(tid), []):
                used.setdefault(backend_name, []).append(str(tid))

        if not used:
            raise ValueError(f"Unknown toy_id(s): {toy_ids}")

        responses = await asyncio.gather(
            *(self._backends[name].stop(toy_id=ids, timeout=timeout) for name, ids in used.items()),
            return_exceptions=True,
        )
        per = {
            name: _dump_response(r)
            for (name, _ids), r in zip(used.items(), responses)
            if not isinstance(r, Exception)
        }
        return CommandResponse(
            code=200,
            type="OK",
            result=True,
            data={"transport": "composite", "per_backend": per},
        )

    async def pattern_request(
        self,
        pattern: list[int],
        actions: list[str | Actions] | None = None,
        interval: int = 100,
        time: float = 0,
        toy_id: str | list[str] | None = None,
        timeout: float | None = None,
        *,
        wait_for_completion: bool = True,
    ) -> CommandResponse:
        if toy_id is None:
            responses = await asyncio.gather(
                *(
                    b.pattern_request(
                        pattern,
                        actions=actions,
                        interval=interval,
                        time=time,
                        toy_id=None,
                        timeout=timeout,
                        wait_for_completion=wait_for_completion,
                    )
                    for b in self._backends.values()
                ),
                return_exceptions=True,
            )
            per = {
                name: _dump_response(r)
                for name, r in zip(self._backends.keys(), responses)
                if not isinstance(r, Exception)
            }
            return CommandResponse(
                code=200,
                type="OK",
                result=True,
                data={"transport": "composite", "per_backend": per},
            )

        toy_ids = [toy_id] if isinstance(toy_id, str) else list(toy_id)
        toy_to_backends, _ = await self._get_toys_index()

        used: dict[str, list[str]] = {}
        for tid in toy_ids:
            for backend_name in toy_to_backends.get(str(tid), []):
                used.setdefault(backend_name, []).append(str(tid))
        if not used:
            raise ValueError(f"Unknown toy_id(s): {toy_ids}")

        responses = await asyncio.gather(
            *(
                self._backends[name].pattern_request(
                    pattern,
                    actions=actions,
                    interval=interval,
                    time=time,
                    toy_id=ids,
                    timeout=timeout,
                    wait_for_completion=wait_for_completion,
                )
                for name, ids in used.items()
            ),
            return_exceptions=True,
        )
        per = {
            name: _dump_response(r)
            for (name, _ids), r in zip(used.items(), responses)
            if not isinstance(r, Exception)
        }
        return CommandResponse(
            code=200,
            type="OK",
            result=True,
            data={"transport": "composite", "per_backend": per},
        )

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
        if toy_id is None:
            responses = await asyncio.gather(
                *(
                    b.preset_request(
                        name,
                        time=time,
                        toy_id=None,
                        timeout=timeout,
                        open_ended=open_ended,
                        wait_for_completion=wait_for_completion,
                    )
                    for b in self._backends.values()
                ),
                return_exceptions=True,
            )
            per = {
                name_b: _dump_response(r)
                for name_b, r in zip(self._backends.keys(), responses)
                if not isinstance(r, Exception)
            }
            return CommandResponse(
                code=200,
                type="OK",
                result=True,
                data={"transport": "composite", "per_backend": per},
            )

        toy_ids = [toy_id] if isinstance(toy_id, str) else list(toy_id)
        toy_to_backends, _ = await self._get_toys_index()

        used: dict[str, list[str]] = {}
        for tid in toy_ids:
            for backend_name in toy_to_backends.get(str(tid), []):
                used.setdefault(backend_name, []).append(str(tid))
        if not used:
            raise ValueError(f"Unknown toy_id(s): {toy_ids}")

        responses = await asyncio.gather(
            *(
                self._backends[name].preset_request(
                    name,
                    time=time,
                    toy_id=ids,
                    timeout=timeout,
                    open_ended=open_ended,
                    wait_for_completion=wait_for_completion,
                )
                for name, ids in used.items()
            ),
            return_exceptions=True,
        )
        per = {
            backend_name: _dump_response(r)
            for (backend_name, _ids), r in zip(used.items(), responses)
            if not isinstance(r, Exception)
        }
        return CommandResponse(
            code=200,
            type="OK",
            result=True,
            data={"transport": "composite", "per_backend": per},
        )
