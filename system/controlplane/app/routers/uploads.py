from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote, unquote, urlparse

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from ..deps import Authenticated, DbSession, ensure_owned_or_admin, require_csrf, require_user
from ..models import User
from ..settings import get_settings

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

CurrentUser = Annotated[User, Depends(require_user)]
UploadCsrf = Annotated[Authenticated, Depends(require_csrf)]
MAX_UPLOAD_BYTES = 1024 * 1024 * 1024
ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "image/webp", "video/mp4"}


def sanitize_basename(filename: str | None) -> str:
    basename = str(filename or "upload").replace("\\", "/").rsplit("/", 1)[-1]
    basename = re.sub(r"\s+", "_", basename)
    basename = re.sub(r"[^A-Za-z0-9._-]", "_", basename).strip("._")
    if not basename or ".." in basename:
        basename = "upload"
    return basename[:160]


def upload_url(user_id: int, filename: str) -> str:
    return f"/api/uploads/{user_id}/{quote(filename)}"


def _owner_directory(user_id: int) -> Path:
    root = Path(get_settings().upload_root).resolve()
    unresolved_owner = root / str(user_id)
    owner = unresolved_owner.resolve()
    if unresolved_owner.is_symlink() or owner == root or not owner.is_relative_to(root):
        raise HTTPException(400, "invalid upload storage path")
    return owner


def resolve_upload(user_id: int, reference: str) -> Path:
    parsed = urlparse(reference)
    prefix = f"/api/uploads/{user_id}/"
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith(prefix)
    ):
        raise ValueError("must reference an upload owned by the current user")
    filename = unquote(parsed.path[len(prefix) :])
    if not filename or "/" in filename or "\\" in filename or sanitize_basename(filename) != filename:
        raise ValueError("contains an invalid upload reference")
    path = _owner_directory(user_id) / filename
    if path.is_symlink() or not path.is_file():
        raise ValueError("references an upload that does not exist")
    return path


@router.post("/pre")
async def pre_upload(
    file: Annotated[UploadFile, File()],
    user: CurrentUser,
    _: UploadCsrf,
) -> dict[str, str]:
    mime_type = (file.content_type or "").split(";", 1)[0].lower()
    if mime_type not in ALLOWED_MIME_TYPES:
        await file.close()
        raise HTTPException(415, "unsupported upload media type")
    if file.size is not None and file.size > MAX_UPLOAD_BYTES:
        await file.close()
        raise HTTPException(413, "upload exceeds 1 GiB")

    owner_dir = _owner_directory(user.id)
    owner_dir.mkdir(parents=True, exist_ok=True)
    temporary = owner_dir / f".{uuid.uuid4().hex}.upload"
    destination: Path | None = None
    digest = hashlib.sha256()
    size = 0
    try:
        with temporary.open("xb") as handle:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "upload exceeds 1 GiB")
                handle.write(chunk)
                digest.update(chunk)
        filename = f"{digest.hexdigest()[:12]}-{sanitize_basename(file.filename)}"
        destination = owner_dir / filename
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    assert destination is not None
    return {"path": str(destination), "url_path": upload_url(user.id, filename)}


@router.get("/{user_id}/files")
async def list_uploads(
    user_id: int,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    ensure_owned_or_admin(user, user_id)
    owner_dir = _owner_directory(user_id)
    files: list[dict[str, Any]] = []
    if owner_dir.is_dir():
        paths = sorted(owner_dir.iterdir(), key=lambda item: item.name)
        for path in paths[offset : offset + limit]:
            try:
                if not path.is_file() or path.is_symlink():
                    continue
                size = path.stat().st_size
            except OSError:
                continue
            files.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "url_path": upload_url(user_id, path.name),
                    "size_bytes": size,
                }
            )
    return {"user_id": user_id, "files": files, "limit": limit, "offset": offset}
