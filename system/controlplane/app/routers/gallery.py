from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import (
    Authenticated,
    DbSession,
    ensure_owned_or_admin,
    require_csrf,
    require_user,
)
from ..models import GalleryMedia, User
from ..settings import get_settings

router = APIRouter(prefix="/api/gallery", tags=["gallery"])

CurrentUser = Annotated[User, Depends(require_user)]
GalleryCsrf = Annotated[Authenticated, Depends(require_csrf)]


def _safe_job_directory(media: GalleryMedia) -> Path:
    root = Path(get_settings().gallery_root).resolve()
    owner = root / str(media.user_id)
    unresolved = owner / str(media.job_id)
    directory = unresolved.resolve()
    if owner.is_symlink() or unresolved.is_symlink() or not directory.is_relative_to(root):
        raise HTTPException(404, "gallery file not found")
    return directory


def _safe_media_path(media: GalleryMedia) -> Path:
    directory = _safe_job_directory(media)
    filename = Path(media.filename).name
    if not filename or filename != media.filename or ".." in filename:
        raise HTTPException(404, "gallery file not found")
    unresolved = directory / filename
    if unresolved.is_symlink():
        raise HTTPException(404, "gallery file not found")
    path = unresolved.resolve()
    if not path.is_relative_to(directory) or not path.is_file():
        raise HTTPException(404, "gallery file not found")
    return path


def _serialize(media: GalleryMedia) -> dict[str, Any]:
    return {
        "id": media.id,
        "job_id": str(media.job_id),
        "user_id": media.user_id,
        "kind": media.kind,
        "filename": media.filename,
        "size_bytes": media.size_bytes,
        "content_type": media.content_type,
        "sha256": media.sha256,
        "created_at": media.created_at.isoformat(),
        "file_url": f"/api/gallery/{media.id}/file",
        "metadata_url": f"/api/gallery/{media.id}/metadata",
    }


async def _media_for_user(db: AsyncSession, user: User, media_id: int) -> GalleryMedia:
    media = await db.get(GalleryMedia, media_id)
    if media is None:
        raise HTTPException(404, "gallery media not found")
    ensure_owned_or_admin(user, media.user_id)
    return media


@router.get("")
async def list_gallery(
    user: CurrentUser,
    db: DbSession,
    user_id: Annotated[int | None, Query(alias="user")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    owner_id = user_id if user_id is not None else user.id
    ensure_owned_or_admin(user, owner_id)
    media = list(
        (
            await db.scalars(
                select(GalleryMedia)
                .where(GalleryMedia.user_id == owner_id)
                .order_by(GalleryMedia.created_at.desc(), GalleryMedia.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    return {
        "user_id": owner_id,
        "items": [_serialize(item) for item in media],
        "limit": limit,
        "offset": offset,
    }


@router.get("/{media_id}/file")
async def get_gallery_file(
    media_id: int,
    user: CurrentUser,
    db: DbSession,
) -> FileResponse:
    media = await _media_for_user(db, user, media_id)
    path = _safe_media_path(media)
    return FileResponse(
        path,
        media_type=media.content_type,
        filename=media.filename,
        content_disposition_type="inline",
    )


@router.get("/{media_id}/metadata")
async def get_gallery_metadata(
    media_id: int,
    user: CurrentUser,
    db: DbSession,
) -> dict[str, Any]:
    media = await _media_for_user(db, user, media_id)
    return _serialize(media)


@router.delete("/{media_id}")
async def delete_gallery_media(
    media_id: int,
    user: CurrentUser,
    db: DbSession,
    _: GalleryCsrf,
) -> dict[str, int | bool]:
    media = await _media_for_user(db, user, media_id)
    result = await remove_gallery_media(db, media)
    return {"gallery_id": media_id, "deleted": True, "removed_items": result}


async def remove_gallery_media(db: AsyncSession, media: GalleryMedia) -> int:
    directory = _safe_job_directory(media)
    related = list(
        (
            await db.scalars(
                select(GalleryMedia).where(GalleryMedia.job_id == media.job_id)
            )
        ).all()
    )
    for item in related:
        await db.delete(item)
    await db.commit()
    if directory.exists():
        shutil.rmtree(directory)
    return len(related)
