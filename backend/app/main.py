"""FastAPI-App: API + ausgeliefertes React-Frontend."""
from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .api import events, images, jobs, projects, sources
from .db import get_conn, migrate
from .logging_setup import log, setup_logging

logger = logging.getLogger("app")
STATIC_DIR = Path(__file__).parent / "static"
VERSION = "0.1.0"


def create_app() -> FastAPI:
    s = config.settings
    setup_logging(s.log_level)
    s.ensure_dirs()
    migrate()
    app = FastAPI(title="Timelapse Studio", version=VERSION, docs_url="/api/docs", openapi_url="/api/openapi.json")

    @app.get("/api/health")
    def health():
        conn = get_conn()
        conn.execute("SELECT 1").fetchone()
        hb = conn.execute("SELECT value FROM setting WHERE key='worker_heartbeat'").fetchone()
        worker_age = int(time.time()) - int(hb["value"]) if hb else None
        return {"status": "ok", "version": VERSION, "worker_alive": worker_age is not None and worker_age < 30,
                "ffmpeg": shutil.which("ffmpeg") is not None, "hwaccel": s.hwaccel}

    @app.get("/api/info")
    def info():
        return {"version": VERSION, "hwaccel": s.hwaccel, "thumb_size": s.thumb_size,
                "max_parallel_renders": s.max_parallel_renders, "render_window": s.render_window,
                "ntfy": bool(s.ntfy_url and s.ntfy_topic)}

    projects.seed_presets()
    for r in (sources.router, images.router, projects.router, jobs.router, events.router):
        app.include_router(r)

    if STATIC_DIR.is_dir():
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            f = (STATIC_DIR / path).resolve()
            if path and f.is_file() and STATIC_DIR.resolve() in f.parents:
                return FileResponse(f)
            return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    log(logger, logging.INFO, "App gestartet", version=VERSION, hwaccel=s.hwaccel)
    return app


app = create_app()
