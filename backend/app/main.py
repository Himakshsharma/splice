"""SPLICE API entry point.

Run locally:  uvicorn app.main:app --reload --port 8000   (from the backend/ folder)

When ``FRONTEND_DIST`` points at the built React app, the same process also
serves the UI, so a single container gives one public URL (used on Hugging Face Spaces).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.routes import router
from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.rate_limit import SlidingWindowLimiter
from app.services.job_store import JobStore
from app.services.jobs import JobManager

log = logging.getLogger("splice")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.temp_dir.mkdir(parents=True, exist_ok=True)
        store = JobStore(settings.db_path, settings.job_ttl_minutes)
        manager = JobManager(settings, store)
        manager.start()
        app.state.jobs = manager
        app.state.limiter = SlidingWindowLimiter(settings.rate_limit_jobs_per_hour)
        log.info(
            "SPLICE started",
            extra={"env": settings.app_env, "whisper_engine": settings.whisper_engine, "whisper_model": settings.whisper_model},
        )
        try:
            yield
        finally:
            manager.shutdown()
            store.close()

    app = FastAPI(
        title="SPLICE API",
        version=__version__,
        description="AI-assisted jump-cut editing: Whisper transcription + energy-based silence removal.",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.frontend_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["X-Job-Token", "Content-Type"],
        max_age=600,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    install_error_handlers(app)
    app.include_router(router)

    dist = settings.frontend_dist
    if dist and (dist / "index.html").is_file():
        _mount_frontend(app, dist)
    return app


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built single-page app; unknown non-API paths fall back to index.html."""
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    index = dist / "index.html"
    root = dist.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"error": {"code": "not_found", "message": "Not Found", "details": {}}}, 404)
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


app = create_app()
