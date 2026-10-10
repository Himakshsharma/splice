"""HTTP API.

Every job endpoint requires the job's access token (returned once, on creation)
via the ``X-Job-Token`` header or a ``token`` query parameter (needed for
``<video src>`` and download links). Unknown ids and wrong tokens both return
404 so job ids cannot be probed. Tokens are random 256-bit values stored only as
SHA-256 hashes; they are capability links, not user accounts.
"""

from __future__ import annotations

import json
import re
import shutil
import unicodedata
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, Header, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError

from app import __version__
from app.core.errors import APIError, MediaError
from app.core.rate_limit import client_ip
from app.processing import transcribe as tr
from app.processing.edit_plan import EditPlan
from app.processing.media import ACCEPTED_EXTENSIONS, probe, tool_available, validate_source
from app.schemas.jobs import (
    CreateJobResponse,
    EditPlanResponse,
    EditSettings,
    HealthResponse,
    JobResponse,
    JobStatus,
    PublicConfig,
    RenderRequest,
    TranscriptResponse,
)
from app.services.job_store import JobRecord
from app.services.jobs import JobManager, public_job, read_json
from app.services.state_machine import ACTIVE

router = APIRouter(prefix="/api")
_JOB_ID = re.compile(r"^[0-9a-f]{32}$")
_CHUNK = 1024 * 1024


def _manager(request: Request) -> JobManager:
    return request.app.state.jobs


def _safe_display_name(name: str | None) -> str:
    """A display-only name: no path parts, no control chars, bounded length."""
    base = (name or "video").replace("\\", "/").split("/")[-1]
    base = "".join(ch for ch in unicodedata.normalize("NFKC", base) if ch.isprintable())
    return (base.strip() or "video")[:120]


def _load_job(request: Request, job_id: str, token: str | None, allow_expired: bool = False) -> JobRecord:
    mgr = _manager(request)
    rec = mgr.store.get(job_id) if _JOB_ID.match(job_id) else None
    if rec is None or not rec.token_matches(token):
        raise APIError(404, "job_not_found", "This job does not exist or the link is invalid.")
    if not allow_expired and (rec.status == JobStatus.EXPIRED or (rec.is_expired and rec.status not in ACTIVE)):
        raise APIError(410, "job_expired", "This job has expired and its files were deleted.")
    return rec


Token = Annotated[str | None, Header(alias="X-Job-Token")]
TokenQ = Annotated[str | None, Query(alias="token")]


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    mgr = _manager(request)
    s = mgr.settings
    ffmpeg, ffprobe = tool_available("ffmpeg"), tool_available("ffprobe")
    whisper_ok = s.whisper_engine != "none" and tr.engine_installed(s.whisper_engine)
    return HealthResponse(
        status="ok" if ffmpeg and ffprobe else "degraded",
        version=__version__,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        whisper_engine=s.whisper_engine,
        whisper_available=whisper_ok,
        whisper_model_loaded=tr.loaded_models(),
        active_jobs=mgr.store.count_active(),
    )


@router.get("/config", response_model=PublicConfig)
def public_config(request: Request) -> PublicConfig:
    s = _manager(request).settings
    return PublicConfig(
        max_upload_mb=s.max_upload_mb,
        max_video_duration_seconds=s.max_video_duration_seconds,
        accepted_extensions=list(ACCEPTED_EXTENSIONS),
        whisper_engine=s.whisper_engine,
        whisper_models=s.whisper_allowed_models,
        default_whisper_model=s.whisper_model,
        job_ttl_minutes=s.job_ttl_minutes,
        source_repo_url=s.source_repo_url,
        defaults=EditSettings(whisper_model=s.whisper_model),
    )


def _parse_settings(raw: str | None, allowed_models: list[str], default_model: str) -> EditSettings:
    try:
        data = json.loads(raw) if raw else {}
        if not isinstance(data, dict):
            raise TypeError
        data.setdefault("whisper_model", default_model)
        settings = EditSettings(**data)
    except ValidationError as exc:
        fields = [{"field": ".".join(map(str, e["loc"])), "message": e["msg"]} for e in exc.errors()]
        raise APIError(422, "invalid_settings", "Some editing settings are invalid.", {"fields": fields}) from None
    except (TypeError, ValueError):
        raise APIError(422, "invalid_settings", "Settings must be a JSON object.") from None
    if settings.whisper_model not in allowed_models:
        raise APIError(422, "invalid_settings", f"Whisper model must be one of: {', '.join(allowed_models)}.")
    return settings


@router.post("/jobs", status_code=201, response_model=CreateJobResponse)
def create_job(
    request: Request,
    file: Annotated[UploadFile, File(description="MP4, MOV or WebM video")],
    settings: Annotated[str | None, Form(description="EditSettings as JSON")] = None,
) -> CreateJobResponse:
    mgr = _manager(request)
    cfg = mgr.settings

    allowed, retry_after = request.app.state.limiter.allow(client_ip(request, cfg.trust_proxy_headers))
    if not allowed:
        raise APIError(
            429,
            "rate_limited",
            "Too many uploads from your network. Please try again later.",
            {"retry_after_seconds": retry_after},
        )

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > cfg.max_upload_bytes + 64 * 1024:
        raise APIError(413, "file_too_large", f"The file exceeds the {cfg.max_upload_mb} MB upload limit.")

    edit_settings = _parse_settings(settings, cfg.whisper_allowed_models, cfg.whisper_model)
    display_name = _safe_display_name(file.filename)
    ext = Path(display_name).suffix.lower()
    if ext not in ACCEPTED_EXTENSIONS:
        raise APIError(
            415,
            "unsupported_file_type",
            f"Unsupported file type. Accepted: {', '.join(e.lstrip('.') for e in ACCEPTED_EXTENSIONS)}.",
        )

    if not mgr.capacity_available():
        raise APIError(503, "server_busy", "The server is busy with other videos. Please try again in a minute.")

    free_mb = shutil.disk_usage(cfg.jobs_dir).free / (1024 * 1024)
    if free_mb < cfg.min_free_disk_mb + cfg.max_upload_mb:
        raise APIError(507, "insufficient_storage", "The server is low on temporary storage. Please try again later.")

    # Stream the upload to a private staging directory, enforcing the size limit as we go.
    staging = cfg.jobs_dir / f"upload-{uuid.uuid4().hex}"
    staging.mkdir(parents=True)
    dest = staging / f"source{ext}"
    try:
        written = 0
        with dest.open("wb") as out:
            while chunk := file.file.read(_CHUNK):
                written += len(chunk)
                if written > cfg.max_upload_bytes:
                    raise APIError(413, "file_too_large", f"The file exceeds the {cfg.max_upload_mb} MB upload limit.")
                out.write(chunk)
        if written == 0:
            raise APIError(422, "empty_file", "The uploaded file is empty.")
        try:  # fast content check so obviously bad files never become jobs
            validate_source(probe(dest, timeout=30), cfg.max_video_duration_seconds)
        except MediaError as exc:
            raise APIError(422, exc.code, exc.message) from None

        rec, token = mgr.store.create(display_name, edit_settings.model_dump())
        staging.rename(mgr.paths(rec.id).root)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        file.file.close()

    mgr.submit(rec.id)
    return CreateJobResponse(job_id=rec.id, access_token=token, job=JobResponse(**public_job(rec)))


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(request: Request, job_id: str, x_job_token: Token = None, token: TokenQ = None) -> JobResponse:
    rec = _load_job(request, job_id, x_job_token or token, allow_expired=True)
    return JobResponse(**public_job(rec))


@router.get("/jobs/{job_id}/transcript", response_model=TranscriptResponse)
def get_transcript(request: Request, job_id: str, x_job_token: Token = None, token: TokenQ = None) -> TranscriptResponse:
    rec = _load_job(request, job_id, x_job_token or token)
    data = read_json(_manager(request).paths(rec.id).transcript)
    if data is None:
        if rec.status in ACTIVE:
            return TranscriptResponse(status="pending")
        raise APIError(404, "transcript_not_available", "No transcript is available for this job.")
    return TranscriptResponse(
        status=data["status"],
        engine=data.get("engine"),
        model=data.get("model"),
        language=data.get("language"),
        message=data.get("message"),
        segments=[{"start": s["start"], "end": s["end"], "text": s["text"]} for s in data.get("segments", [])],
    )


@router.get("/jobs/{job_id}/edit-plan", response_model=EditPlanResponse)
def get_edit_plan(request: Request, job_id: str, x_job_token: Token = None, token: TokenQ = None) -> EditPlanResponse:
    rec = _load_job(request, job_id, x_job_token or token)
    paths = _manager(request).paths(rec.id)
    plan_data, analysis = read_json(paths.plan), read_json(paths.analysis)
    if plan_data is None or analysis is None:
        raise APIError(
            409 if rec.status in ACTIVE else 404,
            "edit_plan_not_ready",
            "The edit plan is not ready yet." if rec.status in ACTIVE else "No edit plan exists for this job.",
        )
    plan = EditPlan.from_dict(plan_data)
    return EditPlanResponse(
        source_duration=plan.source_duration,
        output_duration=plan.output_duration,
        removed_duration=plan.removed_duration,
        cut_count=plan.cut_count,
        retained_count=len(plan.retained),
        threshold_db=analysis["threshold_db"],
        decisions=plan_data["decisions"],
        silences=analysis["silences"],
        waveform=analysis["waveform"],
        warnings=plan.warnings,
    )


@router.post("/jobs/{job_id}/render", status_code=202, response_model=JobResponse)
def rerender(request: Request, job_id: str, body: RenderRequest, x_job_token: Token = None) -> JobResponse:
    """Re-cut and re-render with new settings, reusing the cached audio + transcript."""
    mgr = _manager(request)
    rec = _load_job(request, job_id, x_job_token)
    if rec.status != JobStatus.COMPLETED or not rec.analysis_done:
        raise APIError(409, "job_not_ready", "A job can be re-rendered only after it has completed.")
    new = body.settings
    if new.whisper_model != rec.settings.get("whisper_model") or new.language != rec.settings.get("language"):
        raise APIError(
            422, "invalid_settings", "Whisper model and language are fixed after analysis. Start a new job to change them."
        )
    if not mgr.capacity_available():
        raise APIError(503, "server_busy", "The server is busy with other videos. Please try again in a minute.")
    mgr.store.update(rec.id, settings=new.model_dump(), result=None, cancel_requested=False)
    mgr.store.transition(rec.id, JobStatus.QUEUED)
    mgr.submit(rec.id, rerender=True)
    return JobResponse(**public_job(mgr.store.get(rec.id)))  # type: ignore[arg-type]


@router.get("/jobs/{job_id}/download")
def download(
    request: Request, job_id: str, x_job_token: Token = None, token: TokenQ = None, inline: bool = False
) -> FileResponse:
    rec = _load_job(request, job_id, x_job_token or token)
    out = _manager(request).paths(rec.id).output
    if rec.status != JobStatus.COMPLETED or not out.exists():
        raise APIError(409, "output_not_ready", "The edited video is not ready yet.")
    stem = Path(rec.filename).stem[:80] or "video"
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._") or "video"
    return FileResponse(
        out,
        media_type="video/mp4",
        filename=f"{safe_stem}-splice.mp4",
        content_disposition_type="inline" if inline else "attachment",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(request: Request, job_id: str, x_job_token: Token = None) -> Response:
    mgr = _manager(request)
    rec = _load_job(request, job_id, x_job_token, allow_expired=True)
    if rec.status in ACTIVE:
        mgr.request_cancel(rec.id)  # the worker stops at its next checkpoint and removes the files
        return Response(status_code=202)
    mgr.remove_files(rec.id)
    mgr.store.delete(rec.id)
    return Response(status_code=204)
