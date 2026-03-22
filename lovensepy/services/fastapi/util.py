"""Shared helpers for the FastAPI service."""

from __future__ import annotations

from typing import Any

from lovensepy._models import ToyInfo

from .backend import LovenseControlBackend


def as_dict(model: Any) -> Any:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model


def toy_info_as_dict(toy: ToyInfo) -> dict[str, Any]:
    return toy.model_dump()


async def extract_toy_ids(backend: LovenseControlBackend) -> list[str]:
    response = await backend.get_toys()
    if not response.data or not response.data.toys:
        return []
    return sorted({toy.id for toy in response.data.toys if toy.id})
