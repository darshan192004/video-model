from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from . import db
from .settings import get_settings

log = logging.getLogger("media.main")

DB_CONNECT_RETRY_SECONDS = 60.0


async def _schema_up_with_retry() -> None:
    deadline = time.monotonic() + DB_CONNECT_RETRY_SECONDS
    delay = 1.0
    while True:
        try:
            await db.schema_up()
            return
        except Exception as exc:  # noqa: BLE001 - retried until the window closes
            if time.monotonic() >= deadline:
                log.error("schema creation failed: %s", exc)
                raise
            # Postgres may still be initialising; keep retrying inside the window.
            log.warning("waiting for database: %s", exc)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 5.0)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if get_settings().auto_migrate:
        await _schema_up_with_retry()
    try:
        yield
    finally:
        await db.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="media-controlplane", lifespan=lifespan)
    static = Path(settings.spa_static)

    @app.get("/api/healthz")
    async def healthz() -> dict[str, str]:
        # Liveness only: a database outage is reported, never turned into a
        # non-200, so compose does not restart a healthy process.
        return {"status": "ok", "db": "up" if await db.ping() else "down"}

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(static / "index.html")

    return app


app = create_app()
