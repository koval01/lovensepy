"""OpenAPI schema tweaks (toy_id enums)."""

from __future__ import annotations

from typing import Any

from fastapi.applications import FastAPI
from fastapi.openapi.utils import get_openapi


def patch_openapi_toy_ids(app: FastAPI, toy_ids: list[str]) -> None:
    if not toy_ids:
        return
    app.openapi_schema = None

    schema_names = (
        "FunctionCommand",
        "PresetCommand",
        "PatternCommand",
        "StopToyBody",
        "StopFeatureBody",
    )

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        for model_name in schema_names:
            model = schema.get("components", {}).get("schemas", {}).get(model_name, {})
            props = model.get("properties", {})
            toy = props.get("toy_id")
            if isinstance(toy, dict):
                toy["enum"] = toy_ids
                toy["description"] = "Target toy id."
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]
