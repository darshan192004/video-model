from __future__ import annotations

import math
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ..deps import (
    Authenticated,
    DbSession,
    ensure_owned_or_admin,
    require_csrf,
    require_user,
)
from ..models import GalleryMedia, Job, JobStatus, User, utcnow
from .templates import get_template
from .uploads import resolve_upload

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

CurrentUser = Annotated[User, Depends(require_user)]
JobCsrf = Annotated[Authenticated, Depends(require_csrf)]


class JobCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


def _type_error(parameter: dict[str, Any], value: Any) -> str | None:
    parameter_type = parameter.get("type")
    if parameter_type == "bool":
        return None if isinstance(value, bool) else "must be a boolean"
    if parameter_type == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            return "must be an integer"
        return None
    if parameter_type == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return "must be a number"
        return None
    if parameter_type in {"image", "string"}:
        return None if isinstance(value, str) and value else f"must be a non-empty {parameter_type}"
    return f"has unsupported type {parameter_type!r}"


def validate_params(template: dict[str, Any], supplied: dict[str, Any]) -> dict[str, Any]:
    parameters = {item["name"]: item for item in template.get("params", [])}
    errors: list[dict[str, str]] = []
    unknown = sorted(set(supplied) - set(parameters))
    for name in unknown:
        errors.append({"param": name, "message": "is not accepted by this template"})

    validated: dict[str, Any] = {}
    for name, parameter in parameters.items():
        if name in supplied:
            value = supplied[name]
        elif "default" in parameter:
            value = parameter["default"]
        else:
            errors.append({"param": name, "message": "is required"})
            continue
        if value is None and parameter.get("default", object()) is None:
            validated[name] = None
            continue
        type_error = _type_error(parameter, value)
        if type_error:
            errors.append({"param": name, "message": type_error})
            continue
        if parameter["type"] in {"int", "float"}:
            if isinstance(value, float) and not math.isfinite(value):
                errors.append({"param": name, "message": "must be finite"})
                continue
            minimum = parameter.get("min")
            maximum = parameter.get("max")
            out_of_range = False
            if minimum is not None and value < minimum:
                errors.append({"param": name, "message": f"must be at least {minimum}"})
                out_of_range = True
            if maximum is not None and value > maximum:
                errors.append({"param": name, "message": f"must be at most {maximum}"})
                out_of_range = True
            if out_of_range:
                continue
            step = parameter.get("step")
            if step:
                offset = float(value) - float(minimum or 0)
                position = offset / float(step)
                if abs(position - round(position)) > 1e-9:
                    errors.append({"param": name, "message": f"must align to step {step}"})
        validated[name] = value

    if errors:
        raise HTTPException(
            422,
            detail={
                "code": "parameter_validation_failed",
                "message": "job parameters do not match the template schema",
                "errors": errors,
            },
        )
    return validated


def validate_image_references(
    user: User,
    template: dict[str, Any],
    params: dict[str, Any],
) -> None:
    errors: list[dict[str, str]] = []
    for parameter in template.get("params", []):
        if parameter.get("type") != "image" or params.get(parameter["name"]) is None:
            continue
        try:
            resolve_upload(user.id, params[parameter["name"]])
        except ValueError as exc:
            errors.append({"param": parameter["name"], "message": str(exc)})
    if errors:
        raise HTTPException(
            422,
            detail={
                "code": "image_validation_failed",
                "message": "image parameters must reference an existing owned upload",
                "errors": errors,
            },
        )


def _gallery_item(media: GalleryMedia) -> dict[str, Any]:
    return {
        "id": media.id,
        "job_id": str(media.job_id),
        "kind": media.kind,
        "filename": media.filename,
        "size_bytes": media.size_bytes,
        "content_type": media.content_type,
        "sha256": media.sha256,
        "created_at": media.created_at.isoformat(),
        "file_url": f"/api/gallery/{media.id}/file",
        "metadata_url": f"/api/gallery/{media.id}/metadata",
    }


def _job_payload(job: Job, gallery: list[GalleryMedia]) -> dict[str, Any]:
    counts = dict(job.counts or {})
    return {
        "job_id": str(job.id),
        "template_id": job.template_id,
        "params": dict(job.params or {}),
        "status": job.status,
        "counts": counts,
        "progress": counts,
        "cancel_requested": counts.get("cancel_requested") is True,
        "error": job.error,
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "gallery": [_gallery_item(item) for item in gallery],
    }


@router.post("", status_code=201)
async def create_job(
    request: JobCreateRequest,
    user: CurrentUser,
    _: JobCsrf,
    db: DbSession,
) -> dict[str, str]:
    template_id = request.template_id.strip()
    if not template_id:
        raise HTTPException(400, "template_id is required")
    try:
        template = get_template(template_id)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(400, "unknown template_id") from exc
        raise
    params = validate_params(template, request.params)
    validate_image_references(user, template, params)
    job = Job(
        owner_id=user.id,
        template_id=template_id,
        params=params,
        status=JobStatus.QUEUED.value,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return {"job_id": str(job.id)}


@router.get("")
async def list_jobs(
    user: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    jobs = list(
        (
            await db.scalars(
                select(Job)
                .where(Job.owner_id == user.id)
                .order_by(Job.created_at.desc(), Job.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    return {
        "jobs": [
            {
                "job_id": str(job.id),
                "template_id": job.template_id,
                "params": dict(job.params or {}),
                "status": job.status,
                "counts": dict(job.counts or {}),
                "error": job.error,
                "created_at": job.created_at.isoformat(),
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "finished_at": job.finished_at.isoformat() if job.finished_at else None,
            }
            for job in jobs
        ],
        "limit": limit,
        "offset": offset,
    }


async def _owned_job(db: DbSession, user: User, job_id: UUID) -> Job:
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    ensure_owned_or_admin(user, job.owner_id)
    return job


@router.get("/{job_id}")
async def get_job(
    job_id: UUID,
    user: CurrentUser,
    db: DbSession,
) -> dict[str, Any]:
    job = await _owned_job(db, user, job_id)
    gallery = list(
        (
            await db.scalars(
                select(GalleryMedia)
                .where(GalleryMedia.job_id == job.id)
                .order_by(GalleryMedia.created_at.asc())
            )
        ).all()
    )
    return _job_payload(job, gallery)


@router.post("/{job_id}/cancel")
async def cancel_job(
    job_id: UUID,
    user: CurrentUser,
    db: DbSession,
    _: JobCsrf,
) -> dict[str, Any]:
    job = await _owned_job(db, user, job_id)
    if job.status == JobStatus.QUEUED.value:
        job.status = JobStatus.CANCELLED.value
        job.finished_at = utcnow()
    elif job.status == JobStatus.RUNNING.value:
        counts = dict(job.counts or {})
        counts["cancel_requested"] = True
        job.counts = counts
    elif job.status != JobStatus.CANCELLED.value:
        raise HTTPException(409, "job is already terminal")
    await db.commit()
    await db.refresh(job)
    gallery = list(
        (
            await db.scalars(select(GalleryMedia).where(GalleryMedia.job_id == job.id))
        ).all()
    )
    return _job_payload(job, gallery)
