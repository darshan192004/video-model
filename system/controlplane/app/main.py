import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="media-controlplane")
STATIC = Path(os.environ.get("SPA_STATIC", "/opt/media/spa"))


@app.get("/api/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
