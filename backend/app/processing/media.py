"""FFmpeg / FFprobe helpers: safe subprocess execution and media inspection.

Commands are always passed as argument lists (never through a shell) and file
paths are server-generated, so user input can never be interpreted as a command.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from app.core.errors import MediaError

log = logging.getLogger("splice.media")

ACCEPTED_EXTENSIONS = (".mp4", ".mov", ".webm", ".m4v", ".mkv")
# Containers ffprobe reports for the extensions above.
ACCEPTED_FORMATS = {"mov", "mp4", "m4a", "3gp", "3g2", "mj2", "matroska", "webm"}


class FFmpegError(RuntimeError):
    def __init__(self, message: str, stderr_tail: str = ""):
        super().__init__(message)
        self.stderr_tail = stderr_tail


def tool_available(name: str) -> bool:
    return shutil.which(name) is not None


def run_tool(args: list[str], timeout: float, what: str) -> subprocess.CompletedProcess[str]:
    """Run ffmpeg/ffprobe, raising FFmpegError with a short stderr tail on failure.

    The stderr tail goes to server logs only; callers translate it into a generic
    user-facing message.
    """
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=max(1.0, timeout), check=False)
    except FileNotFoundError as exc:
        raise FFmpegError(f"{args[0]} is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise FFmpegError(f"{what} timed out after {timeout:.0f}s") from exc
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-8:])
        log.warning("ffmpeg step failed", extra={"step": what, "returncode": proc.returncode, "stderr_tail": tail})
        raise FFmpegError(f"{what} failed (exit {proc.returncode})", tail)
    return proc


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    format_name: str
    size_bytes: int
    has_video: bool
    has_audio: bool
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    rotation: int = 0


def _parse_fps(rate: str | None) -> float | None:
    if not rate or rate in ("0/0", "0"):
        return None
    try:
        value = float(Fraction(rate))
    except (ValueError, ZeroDivisionError):
        return None
    return round(value, 3) if 0 < value < 1000 else None


def probe(path: Path, timeout: float = 30) -> MediaInfo:
    """Inspect a media file with ffprobe. Raises MediaError for unreadable media."""
    args = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        proc = run_tool(args, timeout, "ffprobe")
        data = json.loads(proc.stdout or "{}")
    except (FFmpegError, json.JSONDecodeError) as exc:
        raise MediaError(
            "unreadable_media", "The file could not be read as a video. It may be corrupt or in an unsupported format."
        ) from exc

    streams = data.get("streams", [])
    fmt = data.get("format", {})
    video = next(
        (s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")), None
    )
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    duration = 0.0
    for candidate in (fmt.get("duration"), (video or {}).get("duration"), (audio or {}).get("duration")):
        try:
            duration = float(candidate)
            if duration > 0:
                break
        except (TypeError, ValueError):
            continue

    rotation = 0
    if video:
        for sd in video.get("side_data_list", []) or []:
            if "rotation" in sd:
                try:
                    rotation = int(float(sd["rotation"])) % 360
                except (TypeError, ValueError):
                    pass
        tag_rot = (video.get("tags") or {}).get("rotate")
        if tag_rot and not rotation:
            try:
                rotation = int(tag_rot) % 360
            except ValueError:
                pass

    width = int(video["width"]) if video and video.get("width") else None
    height = int(video["height"]) if video and video.get("height") else None
    if rotation in (90, 270) and width and height:
        width, height = height, width  # report display orientation

    return MediaInfo(
        duration=round(duration, 3),
        format_name=str(fmt.get("format_name", "")),
        size_bytes=int(fmt.get("size", 0) or (path.stat().st_size if path.exists() else 0)),
        has_video=video is not None,
        has_audio=audio is not None,
        width=width,
        height=height,
        fps=_parse_fps((video or {}).get("avg_frame_rate")) or _parse_fps((video or {}).get("r_frame_rate")),
        video_codec=(video or {}).get("codec_name"),
        audio_codec=(audio or {}).get("codec_name"),
        rotation=rotation,
    )


def validate_source(info: MediaInfo, max_duration: float) -> None:
    """Reject media SPLICE cannot meaningfully process."""
    formats = set(info.format_name.split(","))
    if not formats & ACCEPTED_FORMATS:
        raise MediaError("unsupported_format", "Unsupported container. Please upload MP4, MOV or WebM.")
    if not info.has_video:
        raise MediaError("no_video_stream", "This file has no video track. SPLICE edits videos, not audio-only files.")
    if not info.has_audio:
        raise MediaError("no_audio_stream", "This video has no audio track, so there is no speech or silence to analyse.")
    if info.duration <= 0.2:
        raise MediaError("too_short", "The video is too short to edit.")
    if info.duration > max_duration:
        raise MediaError(
            "too_long",
            f"The video is {info.duration:.0f}s long; this server accepts up to {max_duration:.0f}s.",
        )
