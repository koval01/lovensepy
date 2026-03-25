"""Shared helpers for the FastAPI service."""

from __future__ import annotations

import re
from typing import Any

from lovensepy._models import ToyInfo

from .backend import LovenseControlBackend


def as_dict(model: Any) -> Any:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model


def toy_info_as_dict(toy: ToyInfo) -> dict[str, Any]:
    return toy.model_dump()


def gap_name_from_ble_advertisement_cache(
    advertisements: dict[str, dict[str, Any]],
    address: str,
    explicit_name: str | None,
) -> str | None:
    """Match ``address`` to ``GET /ble/advertisements`` rows (fingerprint) for ``LVS-…`` name."""
    if explicit_name and str(explicit_name).strip():
        return str(explicit_name).strip()
    fp = re.sub(r"[^0-9a-fA-F]", "", address).lower()
    if len(fp) < 8:
        return None
    for row in advertisements.values():
        a = str(row.get("address") or "")
        if re.sub(r"[^0-9a-fA-F]", "", a).lower() == fp:
            n = row.get("name")
            if n and str(n).strip():
                return str(n).strip()
    return None


async def extract_toy_ids(backend: LovenseControlBackend) -> list[str]:
    response = await backend.get_toys()
    if not response.data or not response.data.toys:
        return []
    return sorted({toy.id for toy in response.data.toys if toy.id})
