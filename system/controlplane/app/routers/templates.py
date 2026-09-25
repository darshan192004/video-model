from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from ..deps import require_user
from ..models import User
from ..workflow import template_definitions, template_schema, template_spec

router = APIRouter(prefix="/api/templates", tags=["templates"])

_INTERNAL_KEYS = {"graph", "_fixture"}


def get_template(template_id: str) -> dict[str, Any]:
    try:
        spec = template_spec(template_id)
    except ValueError:
        raise HTTPException(404, "template not found") from None
    return {key: value for key, value in spec.items() if key not in _INTERNAL_KEYS}


@router.get("")
async def list_templates(
    _: Annotated[User, Depends(require_user)],
) -> dict[str, Any]:
    return {
        "templates": [get_template(template_id) for template_id in template_definitions()],
        "schema": template_schema(),
    }


@router.get("/{template_id}/schema")
async def template_params(
    template_id: str,
    _: Annotated[User, Depends(require_user)],
) -> dict[str, Any]:
    return get_template(template_id)