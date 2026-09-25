"""Single-FIFO job worker: claims queued jobs, drives ComfyUI, files the gallery.

The `jobs` table is the source of truth; the claim statement uses
FOR UPDATE SKIP LOCKED so even a misconfigured second worker cannot double-pick
a row. Progress is poll-based over ComfyUI /history (see comfy.py). A job only
reaches `success` through gallery.copy_run_output(), so a copied-empty result
fails the job rather than presenting phantom media.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import select

from . import gallery, workflow as workflow_mod
from .comfy import ComfyClient
from .db import session_scope
from .models import Job, JobStatus, utcnow
from .settings import get_settings

log = logging.getLogger("media.worker")


def make_client(transport: Any | None = None) -> ComfyClient:
    settings = get_settings()
    return ComfyClient(settings.comfy_internal_url, transport=transport)


async def claim_next(db) -> Job | None:
    result = await db.execute(
        select(Job)
        .where(Job.status == JobStatus.QUEUED.value)
        .order_by(Job.created_at.asc(), Job.id.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    return result.scalar_one_or_none()


def _cancel_requested(job: Job) -> bool:
    return bool((job.counts or {}).get("cancel_requested"))


def _terminal(history: dict[str, Any], prompt_id: str) -> dict[str, Any] | None:
    entry = history.get(prompt_id)
    if not isinstance(entry, dict):
        return None
    status = entry.get("status") or {}
    status_str = str(status.get("status_str") or "")
    if status_str == "completed" or status.get("completed") is True:
        return entry
    if status_str == "error" or "error" in status or status.get("exception"):
        return entry
    return None


def _error_message(entry: dict[str, Any]) -> str | None:
    status = entry.get("status") or {}
    status_str = str(status.get("status_str") or "")
    if status_str == "error" or status.get("exception"):
        return str(status.get("error") or status.get("exception") or "comfy execution error")
    if status.get("error"):
        return str(status["error"])
    return None


async def _set_failed(db, job: Job, message: str) -> None:
    job.status = JobStatus.FAILED.value
    job.error = (message or "unknown failure")[:2000]
    job.finished_at = utcnow()
    await db.commit()
    log.warning("job %s failed: %s", job.id, job.error)


async def process(db, job: Job, client: ComfyClient) -> None:
    """Run one claimed job to a terminal state. Never raises."""
    settings = get_settings()

    job.status = JobStatus.RUNNING.value
    job.started_at = utcnow()
    job.counts = dict(job.counts or {})
    await db.commit()

    try:
        graph = workflow_mod.template_graph(job.template_id)
        payload = workflow_mod.build_workflow(job.template_id, dict(job.params or {}), graph)
        prompt_id = await client.post_prompt(payload, client_id=str(job.id))
        job.client_id = prompt_id
        await db.commit()
    except Exception as exc:  # noqa: BLE001 - any submit failure fails the job
        await _set_failed(db, job, str(exc))
        return

    loop = asyncio.get_running_loop()
    deadline = loop.time() + settings.worker_job_timeout_seconds
    entry: dict[str, Any] | None = None
    try:
        while entry is None:
            if _cancel_requested(job):
                await client.interrupt()
                job.status = JobStatus.CANCELLED.value
                job.finished_at = utcnow()
                await db.commit()
                log.info("job %s cancelled while running", job.id)
                return
            try:
                entry = _terminal(await client.history(prompt_id), prompt_id)
            except Exception as exc:  # noqa: BLE001 - transient backend errors retry
                log.warning("worker history poll failed (retrying): %s", exc)
            if entry is None:
                if loop.time() >= deadline:
                    raise TimeoutError(
                        f"job exceeded the {settings.worker_job_timeout_seconds}s timeout"
                    )
                await asyncio.sleep(settings.worker_poll_seconds)
    except Exception as exc:  # noqa: BLE001 - timeout/interrupt-during-poll failures
        await _set_failed(db, job, str(exc))
        return

    error = _error_message(entry)
    if error:
        await _set_failed(db, job, error)
        return

    try:
        created = await gallery.copy_run_output(db, job, prompt_id, entry.get("outputs") or {})
    except Exception as exc:  # noqa: BLE001 - a copy failure is a job failure
        await _set_failed(db, job, f"gallery copy failed: {exc}")
        return

    if not created:
        await _set_failed(db, job, "comfy finished without any output files")
        return

    counts = dict(job.counts or {})
    counts["completed"] = True
    counts["media"] = len(created)
    job.counts = counts
    job.status = JobStatus.SUCCESS.value
    job.finished_at = utcnow()
    await db.commit()
    log.info("job %s success with %d media item(s)", job.id, len(created))


async def run_forever(transport: Any | None = None) -> None:
    settings = get_settings()
    client = make_client(transport)
    while True:
        try:
            async with session_scope() as db:
                job = await claim_next(db)
                if job is None:
                    await db.commit()
                    await asyncio.sleep(settings.worker_poll_seconds)
                    continue
                await process(db, job, client)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - worker cycle must survive transient faults
            log.exception("worker cycle failed")
            await asyncio.sleep(settings.worker_poll_seconds)


def main() -> None:
    logging.basicConfig(
        level=getattr(logging, get_settings().worker_log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()