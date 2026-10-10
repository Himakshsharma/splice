"""Job orchestration: runs the processing pipeline on a bounded worker pool.

Design notes (kept honest for free hosting):

* Workers are threads inside the API process (``MAX_CONCURRENT_JOBS``). There is
  no external queue, so a restart interrupts running jobs. On startup any job
  left in an active state is marked ``failed`` with a clear "server restarted"
  message and its files are removed — clients see a real terminal state and can
  retry instead of polling forever.
* Every stage checks a cancellation flag and an overall deadline
  (``JOB_TIMEOUT_SECONDS``); rendering checks them per frame / progress tick.
* Each job's files live in a private directory named by a random id and are
  deleted on failure, cancellation, deletion or TTL expiry.
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.core.errors import JobAborted, MediaError
from app.processing import audio as audio_mod
from app.processing import silence as silence_mod
from app.processing import transcribe as tr
from app.processing.edit_plan import EditPlan, PlanConfig, build_edit_plan
from app.processing.media import FFmpegError, MediaInfo, probe, validate_source
from app.processing.render import RenderOptions, render
from app.schemas.jobs import EditSettings, JobStatus
from app.services.job_store import JobRecord, JobStore
from app.services.state_machine import ACTIVE

log = logging.getLogger("splice.jobs")


@dataclass(frozen=True)
class JobPaths:
    root: Path

    @property
    def audio(self) -> Path:
        return self.root / "audio.wav"

    @property
    def transcript(self) -> Path:
        return self.root / "transcript.json"

    @property
    def analysis(self) -> Path:
        return self.root / "analysis.json"

    @property
    def plan(self) -> Path:
        return self.root / "plan.json"

    @property
    def output(self) -> Path:
        return self.root / "output.mp4"

    def source(self) -> Path | None:
        matches = sorted(self.root.glob("source.*"))
        return matches[0] if matches else None


def _write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


class JobManager:
    def __init__(self, settings: Settings, store: JobStore):
        self.settings = settings
        self.store = store
        self.settings.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._pool = ThreadPoolExecutor(max_workers=settings.max_concurrent_jobs, thread_name_prefix="splice-job")
        self._stop = threading.Event()
        self._janitor: threading.Thread | None = None

    # ---- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        self.recover_interrupted()
        self._janitor = threading.Thread(target=self._janitor_loop, name="splice-cleanup", daemon=True)
        self._janitor.start()

    def shutdown(self) -> None:
        self._stop.set()
        for job_id in self.store.active_ids():
            self.store.update(job_id, cancel_requested=True)
        self._pool.shutdown(wait=False, cancel_futures=True)

    def paths(self, job_id: str) -> JobPaths:
        return JobPaths(self.settings.jobs_dir / job_id)

    def recover_interrupted(self) -> None:
        for job_id in self.store.active_ids():
            log.warning("job interrupted by restart", extra={"job_id": job_id})
            self.store.transition(
                job_id,
                JobStatus.FAILED,
                force=True,
                error=("server_restarted", "The server restarted while this video was processing. Please try again."),
            )
            self.remove_files(job_id)

    # ---- submission ----------------------------------------------------------
    def capacity_available(self) -> bool:
        return self.store.count_active() < self.settings.max_concurrent_jobs + self.settings.max_queued_jobs

    def submit(self, job_id: str, rerender: bool = False) -> None:
        self._pool.submit(self._run, job_id, rerender)

    def request_cancel(self, job_id: str) -> None:
        self.store.update(job_id, cancel_requested=True)

    def remove_files(self, job_id: str) -> None:
        root = self.paths(job_id).root
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)

    # ---- pipeline ------------------------------------------------------------
    def _run(self, job_id: str, rerender: bool) -> None:
        started = time.monotonic()
        deadline = started + self.settings.job_timeout_seconds
        last_check = [0.0, False]

        def abort() -> None:
            if time.monotonic() > deadline:
                raise JobAborted("timeout")
            now = time.monotonic()
            if now - last_check[0] > 0.5:  # throttle DB reads during per-frame callbacks
                last_check[0] = now
                rec = self.store.get(job_id)
                last_check[1] = rec is None or rec.cancel_requested
            if last_check[1]:
                raise JobAborted("cancelled")

        def remaining() -> float:
            return max(1.0, deadline - time.monotonic())

        rec = self.store.get(job_id)
        if rec is None:
            return
        try:
            abort()
            settings = EditSettings(**rec.settings)
            paths = self.paths(job_id)
            if not rerender:
                info = self._stage_validate(job_id, paths, remaining)
                self._stage_audio(job_id, paths, remaining, abort)
                self._stage_transcribe(job_id, paths, settings, abort)
                self.store.update(job_id, analysis_done=True)
            else:
                info = self._source_info(job_id, paths)
                paths.output.unlink(missing_ok=True)
            plan = self._stage_plan(job_id, paths, settings, info, abort)
            self._stage_render(job_id, paths, settings, info, plan, abort, remaining)
            log.info("job completed", extra={"job_id": job_id, "seconds": round(time.monotonic() - started, 2)})
        except JobAborted as exc:
            if exc.reason == "cancelled":
                self._finish_failed(job_id, JobStatus.CANCELLED, ("cancelled", "The job was cancelled."))
            else:
                self._finish_failed(
                    job_id,
                    JobStatus.FAILED,
                    ("timeout", f"Processing exceeded the {self.settings.job_timeout_seconds}s limit for this server."),
                )
        except MediaError as exc:
            self._finish_failed(job_id, JobStatus.FAILED, (exc.code, exc.message))
        except FFmpegError as exc:
            log.warning("job failed in ffmpeg", extra={"job_id": job_id, "error": str(exc), "stderr_tail": exc.stderr_tail})
            self._finish_failed(
                job_id,
                JobStatus.FAILED,
                ("processing_failed", "FFmpeg could not process this video. Try a different file or a lower resolution."),
            )
        except Exception:
            log.exception("job crashed", extra={"job_id": job_id})
            self._finish_failed(
                job_id, JobStatus.FAILED, ("internal_error", "An unexpected error occurred while processing this video.")
            )

    def _finish_failed(self, job_id: str, status: JobStatus, error: tuple[str, str]) -> None:
        if self.store.get(job_id) is None:  # deleted while running
            self.remove_files(job_id)
            return
        self.store.transition(job_id, status, force=True, error=error)
        self.store.update(job_id, cancel_requested=False)
        self.remove_files(job_id)  # never keep user media from a failed job
        log.info("job ended", extra={"job_id": job_id, "status": status.value, "code": error[0]})

    def _to(self, job_id: str, status: JobStatus, progress: float | None = None) -> None:
        self.store.transition(job_id, status, progress=progress)

    def _source_info(self, job_id: str, paths: JobPaths) -> MediaInfo:
        rec = self.store.get(job_id)
        assert rec is not None and rec.source is not None
        s = rec.source
        return MediaInfo(
            duration=s["duration"],
            format_name=s.get("container") or "",
            size_bytes=s["size_bytes"],
            has_video=True,
            has_audio=s["has_audio"],
            width=s.get("width"),
            height=s.get("height"),
            fps=s.get("fps"),
            video_codec=s.get("video_codec"),
            audio_codec=s.get("audio_codec"),
        )

    def _stage_validate(self, job_id: str, paths: JobPaths, remaining) -> MediaInfo:
        self._to(job_id, JobStatus.VALIDATING)
        src = paths.source()
        if src is None:
            raise MediaError("missing_upload", "The uploaded file is missing.")
        info = probe(src, timeout=min(60, remaining()))
        validate_source(info, self.settings.max_video_duration_seconds)
        rec = self.store.get(job_id)
        self.store.update(
            job_id,
            source={
                "filename": rec.filename if rec else src.name,
                "size_bytes": src.stat().st_size,
                "duration": info.duration,
                "width": info.width,
                "height": info.height,
                "fps": info.fps,
                "video_codec": info.video_codec,
                "audio_codec": info.audio_codec,
                "has_audio": info.has_audio,
                "container": info.format_name,
            },
        )
        return info

    def _stage_audio(self, job_id: str, paths: JobPaths, remaining, abort) -> None:
        abort()
        self._to(job_id, JobStatus.EXTRACTING_AUDIO)
        audio_mod.extract_audio(paths.source(), paths.audio, timeout=remaining())  # type: ignore[arg-type]

    def _stage_transcribe(self, job_id: str, paths: JobPaths, settings: EditSettings, abort) -> None:
        abort()
        self._to(job_id, JobStatus.TRANSCRIBING)
        engine = self.settings.whisper_engine
        payload: dict[str, Any]
        if engine == "none":
            payload = {"status": "disabled", "message": "Transcription is disabled on this server."}
        else:
            samples, sr = audio_mod.load_wav(paths.audio)
            try:
                transcript = tr.transcribe(
                    samples,
                    sr,
                    engine=engine,
                    model_name=settings.whisper_model,
                    device=self.settings.whisper_device,
                    language=settings.language,
                    cache_dir=self.settings.whisper_cache_dir,
                    on_progress=lambda p: self.store.set_progress(job_id, p),
                    should_abort=abort,
                )
                payload = {"status": "completed" if transcript.segments else "empty", **transcript.to_dict()}
                if not transcript.segments:
                    payload["message"] = "Whisper did not detect any speech in this video."
            except tr.TranscriptionUnavailable as exc:
                # Degrade honestly: cuts still come from the energy detector, and the UI says so.
                payload = {
                    "status": "unavailable",
                    "engine": engine,
                    "model": settings.whisper_model,
                    "message": f"{exc} Cuts were made from audio energy only.",
                }
        _write_json(paths.transcript, payload)

    def _stage_plan(self, job_id: str, paths: JobPaths, settings: EditSettings, info: MediaInfo, abort) -> EditPlan:
        abort()
        self._to(job_id, JobStatus.DETECTING_SILENCE)
        samples, sr = audio_mod.load_wav(paths.audio)
        silences = silence_mod.detect_silence(samples, sr, settings.silence_threshold_db, settings.min_silence_duration)
        step, env = silence_mod.waveform_envelope(samples, sr)
        _write_json(
            paths.analysis,
            {
                "threshold_db": settings.silence_threshold_db,
                "silences": [{"start": s.start, "end": s.end} for s in silences],
                "waveform": {"seconds_per_point": step, "db": env},
            },
        )

        abort()
        self._to(job_id, JobStatus.GENERATING_EDIT_PLAN)
        transcript = read_json(paths.transcript) or {}
        spans = None
        if transcript.get("status") == "completed":
            spans = [silence_mod.Interval(a, b) for a, b in tr.Transcript.from_dict(transcript).speech_spans()]
        # The video container may be slightly longer/shorter than the audio; plan on the video duration.
        plan = build_edit_plan(
            info.duration,
            silences,
            PlanConfig(
                settings.padding_before,
                settings.padding_after,
                settings.min_segment_duration,
                settings.max_output_duration,
                settings.protect_speech,
            ),
            speech_spans=spans,
        )
        if transcript.get("status") == "unavailable":
            plan.warnings.append(transcript.get("message", "Transcription was unavailable."))
        _write_json(paths.plan, plan.to_dict())
        return plan

    def _stage_render(
        self, job_id: str, paths: JobPaths, settings: EditSettings, info: MediaInfo, plan: EditPlan, abort, remaining
    ) -> None:
        abort()
        self._to(job_id, JobStatus.RENDERING, progress=0.0)
        options = RenderOptions(
            resolution=settings.output_resolution,
            quality=settings.quality,
            keep_audio=settings.keep_audio,
            mode=settings.mode,
            engine=self.settings.render_engine,
        )
        result = render(
            paths.source(),
            paths.output,
            plan,
            info,
            options,
            paths.root,  # type: ignore[arg-type]
            timeout=remaining(),
            abort=abort,
            progress=lambda p: self.store.set_progress(job_id, p),
        )
        transcript = read_json(paths.transcript) or {}
        removed = max(0.0, plan.source_duration - plan.output_duration)
        self.store.update(
            job_id,
            result={
                "original_duration": plan.source_duration,
                "output_duration": round(result.duration, 3),
                "removed_duration": round(removed, 3),
                "removed_percent": round(100.0 * removed / plan.source_duration, 1) if plan.source_duration else 0.0,
                "cut_count": plan.cut_count,
                "retained_count": len(plan.retained),
                "render_mode": settings.mode,
                "render_engine": result.engine,
                "output_width": result.width,
                "output_height": result.height,
                "output_size_bytes": result.size_bytes,
                "transcript_status": transcript.get("status", "unavailable"),
                "transcript_language": transcript.get("language"),
                "warnings": plan.warnings,
            },
        )
        self.store.extend_expiry(job_id)
        self._to(job_id, JobStatus.COMPLETED, progress=1.0)

    # ---- cleanup -------------------------------------------------------------
    def run_cleanup(self) -> dict[str, int]:
        expired = 0
        for job_id in self.store.expired_candidates():
            rec = self.store.get(job_id)
            if rec is None:
                continue
            if rec.status in ACTIVE:
                self.request_cancel(job_id)  # worker will clean up when it notices
                continue
            self.remove_files(job_id)
            self.store.transition(job_id, JobStatus.EXPIRED, force=True)
            expired += 1
        known = self.store.all_ids()
        orphans = 0
        if self.settings.jobs_dir.exists():
            for child in self.settings.jobs_dir.iterdir():
                if child.name not in known:
                    shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink(missing_ok=True)
                    orphans += 1
        purged = self.store.purge_old(timedelta(days=1))
        if expired or orphans or purged:
            log.info("cleanup", extra={"expired": expired, "orphans": orphans, "purged": purged})
        return {"expired": expired, "orphans": orphans, "purged": purged}

    def _janitor_loop(self) -> None:
        interval = self.settings.cleanup_interval_minutes * 60
        while not self._stop.wait(interval):
            try:
                self.run_cleanup()
            except Exception:
                log.exception("cleanup failed")


def public_job(rec: JobRecord) -> dict[str, Any]:
    from app.services.state_machine import STAGE_LABELS

    status = rec.status
    if rec.is_expired and status not in ACTIVE:
        status = JobStatus.EXPIRED
    return {
        "job_id": rec.id,
        "status": status,
        "stage_label": STAGE_LABELS[status],
        "progress": rec.progress,
        "created_at": rec.created_at,
        "updated_at": rec.updated_at,
        "expires_at": rec.expires_at,
        "error": {"code": rec.error_code, "message": rec.error_message} if rec.error_code else None,
        "source": rec.source,
        "settings": rec.settings,
        "result": rec.result if status == JobStatus.COMPLETED else None,
    }
