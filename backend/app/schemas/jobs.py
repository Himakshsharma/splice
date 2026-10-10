"""Pydantic request/response models for the jobs API."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class JobStatus(StrEnum):
    QUEUED = "queued"
    VALIDATING = "validating"
    EXTRACTING_AUDIO = "extracting_audio"
    TRANSCRIBING = "transcribing"
    DETECTING_SILENCE = "detecting_silence"
    GENERATING_EDIT_PLAN = "generating_edit_plan"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class EditSettings(BaseModel):
    """Every field here is consumed by the backend pipeline — nothing is decorative."""

    model_config = ConfigDict(extra="forbid")

    silence_threshold_db: float = Field(
        -40.0, ge=-70.0, le=-10.0, description="Frames quieter than this (dBFS) count as silence."
    )
    min_silence_duration: float = Field(0.5, ge=0.1, le=10.0, description="Only remove silences at least this long (s).")
    padding_before: float = Field(0.12, ge=0.0, le=1.5, description="Audio kept before speech resumes (s).")
    padding_after: float = Field(0.18, ge=0.0, le=1.5, description="Audio kept after speech ends (s).")
    min_segment_duration: float = Field(0.25, ge=0.0, le=5.0, description="Kept segments shorter than this are dropped (s).")
    max_output_duration: float | None = Field(None, ge=1.0, le=7200.0, description="Optional cap on output length (s).")
    whisper_model: str = Field("tiny", description="Whisper checkpoint used for transcription.")
    language: str | None = Field(None, description="ISO language code, or null for auto-detect.")
    protect_speech: bool = Field(True, description="Never cut inside words Whisper heard, even if they are quiet.")
    output_resolution: Literal["original", "1080p", "720p", "480p"] = "original"
    quality: Literal["draft", "balanced", "high"] = "balanced"
    keep_audio: bool = True
    mode: Literal["preview", "final"] = "final"

    @field_validator("language")
    @classmethod
    def _language(cls, v: str | None) -> str | None:
        if v is None or v.strip().lower() in ("", "auto"):
            return None
        v = v.strip().lower()
        if not (2 <= len(v) <= 3 and v.isalpha()):
            raise ValueError("language must be a 2-3 letter ISO code or 'auto'")
        return v

    @model_validator(mode="after")
    def _padding_fits(self) -> EditSettings:
        if self.padding_before + self.padding_after >= self.min_silence_duration + 1e-9:
            raise ValueError(
                "padding_before + padding_after must be smaller than min_silence_duration, otherwise nothing could ever be cut"
            )
        return self


class RenderRequest(BaseModel):
    """Re-render an analysed job, optionally with new cut/output settings.

    Transcription is cached, so only silence detection, planning and rendering re-run.
    """

    model_config = ConfigDict(extra="forbid")
    settings: EditSettings


class ErrorInfo(BaseModel):
    code: str
    message: str


class SourceInfo(BaseModel):
    filename: str
    size_bytes: int
    duration: float
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    has_audio: bool
    container: str | None = None


class ResultInfo(BaseModel):
    original_duration: float
    output_duration: float
    removed_duration: float
    removed_percent: float
    cut_count: int
    retained_count: int
    render_mode: Literal["preview", "final"]
    render_engine: str
    output_width: int | None = None
    output_height: int | None = None
    output_size_bytes: int
    transcript_status: str
    transcript_language: str | None = None
    warnings: list[str] = []


class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    stage_label: str
    progress: float | None = Field(None, description="0..1 when measurable, null when indeterminate.")
    created_at: str
    updated_at: str
    expires_at: str
    error: ErrorInfo | None = None
    source: SourceInfo | None = None
    settings: EditSettings
    result: ResultInfo | None = None


class CreateJobResponse(BaseModel):
    job_id: str
    access_token: str
    job: JobResponse


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str


class TranscriptResponse(BaseModel):
    status: Literal["pending", "completed", "empty", "unavailable", "disabled"]
    engine: str | None = None
    model: str | None = None
    language: str | None = None
    message: str | None = None
    segments: list[TranscriptSegment] = []


class EditDecisionOut(BaseModel):
    index: int
    decision: Literal["retain", "remove"]
    reason: str
    source_start: float
    source_end: float
    duration: float
    output_start: float | None
    output_end: float | None


class SilenceOut(BaseModel):
    start: float
    end: float


class WaveformOut(BaseModel):
    seconds_per_point: float
    db: list[float]


class EditPlanResponse(BaseModel):
    source_duration: float
    output_duration: float
    removed_duration: float
    cut_count: int
    retained_count: int
    threshold_db: float
    decisions: list[EditDecisionOut]
    silences: list[SilenceOut]
    waveform: WaveformOut
    warnings: list[str] = []


class PublicConfig(BaseModel):
    max_upload_mb: int
    max_video_duration_seconds: int
    accepted_extensions: list[str]
    whisper_engine: str
    whisper_models: list[str]
    default_whisper_model: str
    job_ttl_minutes: int
    source_repo_url: str | None
    defaults: EditSettings


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    ffmpeg: bool
    ffprobe: bool
    whisper_engine: str
    whisper_available: bool
    whisper_model_loaded: list[str]
    active_jobs: int
