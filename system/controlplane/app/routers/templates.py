from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from ..deps import require_user
from ..models import User
from ..workflow import template_schema

router = APIRouter(prefix="/api/templates", tags=["templates"])


def get_template(template_id: str) -> dict[str, Any]:
    templates = template_schema().get("templates", {})
    template = templates.get(template_id)
    if template is None:
        raise HTTPException(404, "template not found")
    return {"id": template_id, **template}


@router.get("")
async def list_templates(
    _: Annotated[User, Depends(require_user)],
) -> dict[str, Any]:
    return {
        "templates": [get_template(template_id) for template_id in template_schema()["templates"]],
        "schema": template_schema(),
    }


@router.get("/{template_id}/schema")
async def template_params(
    template_id: str,
    _: Annotated[User, Depends(require_user)],
) -> dict[str, Any]:
    return get_template(template_id)