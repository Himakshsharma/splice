"""Application configuration.

All environment-specific values are read from environment variables (optionally
loaded from ``backend/.env``) and validated once at startup. Invalid values fail
fast with a readable message instead of surfacing later as obscure runtime bugs.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Whisper checkpoints that can realistically run on a CPU-only free host.
KNOWN_WHISPER_MODELS = ("tiny", "tiny.en", "base", "base.en", "small", "small.en")


class Settings(BaseModel):
    app_env: Literal["development", "production", "test"] = "development"
    frontend_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    frontend_dist: Path | None = None

    max_upload_mb: int = Field(50, ge=1, le=2048)
    max_video_duration_seconds: int = Field(300, ge=5, le=7200)
    max_concurrent_jobs: int = Field(1, ge=1, le=16)
    max_queued_jobs: int = Field(4, ge=1, le=100)
    job_timeout_seconds: int = Field(900, ge=30, le=21600)
    job_ttl_minutes: int = Field(60, ge=1, le=10080)
    cleanup_interval_minutes: int = Field(5, ge=1, le=1440)
    min_free_disk_mb: int = Field(500, ge=0)
    rate_limit_jobs_per_hour: int = Field(20, ge=0)
    trust_proxy_headers: bool = False

    whisper_engine: Literal["openai-whisper", "faster-whisper", "none"] = "openai-whisper"
    whisper_model: str = "tiny"
    whisper_allowed_models: list[str] = Field(default_factory=lambda: ["tiny", "base"])
    whisper_device: Literal["cpu", "cuda", "auto"] = "cpu"
    whisper_cache_dir: Path | None = None

    render_engine: Literal["auto", "moviepy", "ffmpeg"] = "auto"
    temp_dir: Path = Field(default_factory=lambda: BACKEND_ROOT / "tmp")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    source_repo_url: str | None = None

    @field_validator("whisper_allowed_models")
    @classmethod
    def _known_models(cls, v: list[str]) -> list[str]:
        unknown = [m for m in v if m not in KNOWN_WHISPER_MODELS]
        if unknown:
            raise ValueError(f"unsupported Whisper model(s) {unknown}; choose from {KNOWN_WHISPER_MODELS}")
        if not v:
            raise ValueError("at least one Whisper model must be allowed")
        return v

    @model_validator(mode="after")
    def _default_model_allowed(self) -> Settings:
        if self.whisper_model not in self.whisper_allowed_models:
            raise ValueError(
                f"WHISPER_MODEL={self.whisper_model!r} must be one of WHISPER_ALLOWED_MODELS {self.whisper_allowed_models}"
            )
        return self

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def jobs_dir(self) -> Path:
        return self.temp_dir / "jobs"

    @property
    def db_path(self) -> Path:
        return self.temp_dir / "splice.db"


def _load_dotenv() -> None:
    """Populate os.environ from backend/.env without overriding real env vars."""
    env_file = BACKEND_ROOT / ".env"
    if not env_file.is_file():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_LIST_FIELDS = {"frontend_origins", "whisper_allowed_models"}


def settings_from_env(env: dict[str, str] | None = None) -> Settings:
    """Build Settings from an environment mapping (defaults to os.environ)."""
    if env is None:
        _load_dotenv()
        env = dict(os.environ)
    data: dict[str, object] = {}
    for name in Settings.model_fields:
        raw = env.get(name.upper())
        if raw is None or raw == "":
            continue
        if name in _LIST_FIELDS:
            data[name] = [item.strip() for item in raw.split(",") if item.strip()]
        else:
            data[name] = raw
    try:
        return Settings(**data)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(map(str, e['loc'])).upper() or 'CONFIG'}: {e['msg']}" for e in exc.errors())
        raise RuntimeError(f"Invalid SPLICE configuration -> {problems}") from exc


@lru_cache
def get_settings() -> Settings:
    return settings_from_env()
