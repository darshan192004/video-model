"""Gallery copy: lift ComfyUI output files into the per-user gallery tree."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .models import GalleryMedia, Job, User, utcnow
from .settings import get_settings

# Output keys ComfyUI emits under a node's `outputs` entry, mapped to kinds.
_KIND_KEYS = {
    "image": ("images",),
    "video": ("videos", "gifs"),
}

_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}


def safe_name(name: str) -> str:
    """Basename-only, whitespace collapsed to `_`, traversal impossible."""
    base = Path(name or "").name
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._ ")
    return base or "file"


def _source(output_dir: Path, subfolder: str, filename: str) -> Path | None:
    base = output_dir.resolve()
    parts = [p for p in subfolder.split("/") + [filename] if p not in ("", ".", "..")]
    candidate = base.joinpath(*parts).resolve()
    if not candidate.is_relative_to(base) or not candidate.is_file():
        return None
    return candidate


def _flatten_name(subfolder: str, filename: str, seen: set[str]) -> str:
    safe = safe_name(filename)
    if subfolder:
        prefix = safe_name(subfolder)
        if prefix:
            safe = f"{prefix}-{safe}"
    candidate, counter = safe, 1
    while candidate in seen:
        counter += 1
        candidate = f"{safe.rsplit('.', 1)[0]}-{counter}.{safe.rsplit('.', 1)[-1]}"
    return candidate


def _content_type(filename: str, kind: str) -> str:
    return _MIME_BY_EXT.get(Path(filename).suffix.lower(), f"image/{kind}")


async def copy_run_output(
    db: AsyncSession,
    job: Job,
    client_id: str,
    node_outputs: dict[str, Any],
) -> list[GalleryMedia]:
    """Copy a terminal job's output files into GALLERY_ROOT/<owner>/<job-id>/.

    Returns the freshly created GalleryMedia rows and writes a metadata.json
    sidecar next to the copied files. A job only reaches `success` through this
    function, so an empty return means the job should fail.
    """
    settings = get_settings()
    output_dir = Path(settings.comfy_output_dir)
    job_dir = Path(settings.gallery_root) / str(job.owner_id) / str(job.id)
    job_dir.mkdir(parents=True, exist_ok=True)

    rows: list[GalleryMedia] = []
    seen: set[str] = set()
    files_meta: list[dict[str, Any]] = []

    for node_output in node_outputs.values():
        if not isinstance(node_output, dict):
            continue
        for kind, keys in _KIND_KEYS.items():
            for key in keys:
                for item in node_output.get(key, []) or []:
                    if item.get("type", "output") != "output":
                        continue
                    source = _source(output_dir, str(item.get("subfolder") or ""), str(item.get("filename") or ""))
                    if source is None:
                        continue
                    target_name = _flatten_name(str(item.get("subfolder") or ""), source.name, seen)
                    seen.add(target_name)
                    target = job_dir / target_name
                    shutil.copyfile(source, target)
                    digest = hashlib.sha256(target.read_bytes()).hexdigest()
                    size = target.stat().st_size
                    rows.append(
                        GalleryMedia(
                            job_id=job.id,
                            user_id=job.owner_id,
                            kind=kind,
                            filename=target_name,
                            size_bytes=size,
                            content_type=_content_type(target_name, kind),
                            sha256=digest,
                        )
                    )
                    files_meta.append(
                        {
                            "filename": target_name,
                            "kind": kind,
                            "size_bytes": size,
                            "sha256": digest,
                        }
                    )

    owner = await db.get(User, job.owner_id)
    metadata = {
        "job_id": str(job.id),
        "template_id": job.template_id,
        "params": dict(job.params or {}),
        "client_id": client_id,
        "status": job.status,
        "created_at": _iso(job.created_at),
        "started_at": _iso(job.started_at),
        "finished_at": _iso(job.finished_at),
        "owner": owner.email if owner else None,
        "files": files_meta,
    }
    (job_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    for row in rows:
        db.add(row)
    if rows:
        await db.flush()
    return rows


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None