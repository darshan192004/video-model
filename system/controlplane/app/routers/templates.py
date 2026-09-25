from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from ..deps import require_user
from ..models import User

router = APIRouter(prefix="/api/templates", tags=["templates"])

TEMPLATE_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "config" / "templates.schema.json"


@lru_cache(maxsize=1)
def template_schema() -> dict[str, Any]:
    with TEMPLATE_SCHEMA_PATH.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict) or not isinstance(value.get("templates"), list):
        raise RuntimeError("invalid templates schema")
    return value


def get_template(template_id: str) -> dict[str, Any]:
    for template in template_schema()["templates"]:
        if template.get("id") == template_id:
            return template
    raise HTTPException(404, "template not found")


@router.get("")
async def list_templates(
    _: Annotated[User, Depends(require_user)],
) -> dict[str, Any]:
    return template_schema()


@router.get("/{template_id}/schema")
async def template_params(
    template_id: str,
    _: Annotated[User, Depends(require_user)],
) -> dict[str, Any]:
    return get_template(template_id)
