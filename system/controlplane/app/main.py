from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .routers import admin, auth, gallery, jobs, templates, uploads
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
    app = FastAPI(
        title="media-controlplane",
        lifespan=lifespan,
        openapi_url="/api/openapi.json",
    )
    static = Path(settings.spa_static)

    @app.get("/api/healthz")
    async def healthz() -> dict[str, str]:
        # Liveness only: a database outage is reported, never turned into a
        # non-200, so compose does not restart a healthy process.
        return {"status": "ok", "db": "up" if await db.ping() else "down"}

    # The built Nuxt bundle is prerendered into SPA_STATIC and served verbatim.
    # History-mode routes (no '#' in the URL) fall through to index.html below.
    if static.is_dir():
        assets = static / "_nuxt"
        if assets.is_dir():
            app.mount("/_nuxt", StaticFiles(directory=assets), name="spa_assets")

    # /api/auth/*, /api/healthz and the SPA stay unauthenticated; every other
    # router carries its own require_user/require_admin dependency.
    app.include_router(auth.router)
    app.include_router(templates.router)
    app.include_router(uploads.router)
    app.include_router(jobs.router)
    app.include_router(gallery.router)
    app.include_router(admin.router)

    # The catch-all MUST be registered last so /api/* routes always win over
    # the SPA fallback under lazy router resolution.
    @app.get("/{path:path}", include_in_schema=False, response_model=None)
    def spa_fallback(path: str) -> FileResponse | JSONResponse:
        # Anything under /api already uses the routers above; keep API 404s
        # as JSON instead of HTML fallbacks.
        if path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        if static.is_dir():
            base = static.resolve()
            index = static / "index.html"
            try:
                candidate = (static / path).resolve()
            except OSError:
                candidate = base
            if candidate.is_relative_to(base):
                if candidate.is_dir():
                    candidate = candidate / "index.html"
                if candidate.is_file():
                    return FileResponse(candidate)
            if index.is_file():
                return FileResponse(index)
        return JSONResponse({"detail": "SPA not built"}, status_code=404)

    return app


app = create_app()
