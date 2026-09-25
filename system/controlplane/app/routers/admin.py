from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

import fastapi
import uvicorn
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select

from ..deps import Authenticated, DbSession, require_admin, require_csrf
from ..models import GalleryMedia, Job, JobStatus, User
from ..settings import get_settings
from .gallery import remove_gallery_media

router = APIRouter(prefix="/api/admin", tags=["admin"])

AdminUser = Annotated[User, Depends(require_admin)]
AdminCsrf = Annotated[Authenticated, Depends(require_csrf)]
APP_VERSION = "0.1.0"


def audit(user: User, action: str, target: str) -> None:
    fields = ("_".join(user.subject.split()), action, "_".join(target.split()))
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"AUDIT {' '.join(fields)} {timestamp}", flush=True)


def _storage_usage() -> dict[str, int]:
    path = Path(get_settings().gallery_root)
    while not path.exists() and path != path.parent:
        path = path.parent
    usage = shutil.disk_usage(path)
    return {"free_bytes": usage.free, "total_bytes": usage.total, "used_bytes": usage.used}


@router.get("/system")
async def system_info(admin: AdminUser, db: DbSession) -> dict[str, Any]:
    queue_depth = int(
        (
            await db.scalar(
                select(func.count()).select_from(Job).where(Job.status == JobStatus.QUEUED.value)
            )
        )
        or 0
    )
    running = int(
        (
            await db.scalar(
                select(func.count()).select_from(Job).where(Job.status == JobStatus.RUNNING.value)
            )
        )
        or 0
    )
    audit(admin, "system.view", "system")
    return {
        "versions": {
            "app": APP_VERSION,
            "uvicorn": uvicorn.__version__,
            "fastapi": fastapi.__version__,
        },
        "queue_depth": queue_depth,
        "worker": {"status": "placeholder", "running_jobs": running},
        "storage": _storage_usage(),
    }


@router.get("/jobs/{job_id}/raw")
async def raw_job(
    job_id: UUID,
    admin: AdminUser,
    db: DbSession,
) -> dict[str, Any]:
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    audit(admin, "job.raw", str(job.id))
    return {
        "job_id": str(job.id),
        "template_id": job.template_id,
        "status": job.status,
        "workflow": dict(job.params or {}),
        "params": dict(job.params or {}),
        "counts": dict(job.counts or {}),
    }


@router.get("/users")
async def list_users(
    admin: AdminUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    users = list(
        (
            await db.scalars(
                select(User).order_by(User.id.asc()).limit(limit).offset(offset)
            )
        ).all()
    )
    audit(admin, "users.view", "users")
    return {
        "users": [
            {
                "id": item.id,
                "subject": item.subject,
                "name": item.name,
                "email": item.email,
                "groups": list(item.groups or []),
                "is_admin": item.is_admin,
                "created_at": item.created_at.isoformat(),
            }
            for item in users
        ],
        "limit": limit,
        "offset": offset,
    }


@router.post("/gallery/{media_id}/delete")
async def delete_gallery(
    media_id: int,
    admin: AdminUser,
    _: AdminCsrf,
    db: DbSession,
) -> dict[str, int | bool]:
    media = await db.get(GalleryMedia, media_id)
    if media is None:
        raise HTTPException(404, "gallery media not found")
    removed_items = await remove_gallery_media(db, media)
    audit(admin, "gallery.delete", str(media_id))
    return {"gallery_id": media_id, "deleted": True, "removed_items": removed_items}
