"""Generate small, deterministic test videos with FFmpeg (no binary fixtures in git)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _has_flite() -> bool:
    if not HAS_FFMPEG:
        return False
    out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    return " flite " in out


HAS_FLITE = _has_flite()


def tone_video(path: Path, pattern: list[tuple[str, float]], size: str = "320x240", fps: int = 25) -> Path:
    """Video whose audio follows ``pattern`` of ("tone"|"silence", seconds) blocks.

    A 300 Hz tone stands in for speech; silence is digital zero.
    """
    total = sum(d for _, d in pattern)
    enable, t = [], 0.0
    for kind, dur in pattern:
        if kind == "silence":
            enable.append(f"between(t,{t:.3f},{t + dur:.3f})")
        t += dur
    vol = f"volume=0:enable='{'+'.join(enable)}'" if enable else "anull"
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={fps}:duration={total}",
            "-f", "lavfi", "-i", f"sine=frequency=300:sample_rate=44100:duration={total}",
            "-filter:a", f"volume=0.5,{vol}",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )  # fmt: skip
    return path


def speech_video(path: Path, phrases: list[str], gaps: list[float], size: str = "320x240") -> Path:
    """Video with synthesized speech (FFmpeg's flite) separated by silent gaps.

    ``gaps`` has len(phrases) + 1 entries: leading silence, between phrases, trailing silence.
    """
    assert len(gaps) == len(phrases) + 1
    inputs: list[str] = []
    labels: list[str] = []
    filters: list[str] = []
    idx = 0
    for i, gap in enumerate(gaps):
        inputs += ["-f", "lavfi", "-i", f"anullsrc=r=22050:cl=mono:d={gap}"]
        labels.append(f"[{idx}:a]")
        idx += 1
        if i < len(phrases):
            text = phrases[i].replace("'", "").replace(":", "")
            inputs += ["-f", "lavfi", "-i", f"flite=text='{text}':voice=slt"]
            filters.append(f"[{idx}:a]aresample=22050[s{idx}]")
            labels.append(f"[s{idx}]")
            idx += 1
    filters.append(f"{''.join(labels)}concat=n={len(labels)}:v=0:a=1[aout]")
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-loglevel", "error", "-y", *inputs,
            "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=25",
            "-filter_complex", ";".join(filters),
            "-map", f"{idx}:v", "-map", "[aout]", "-shortest",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "44100", str(path),
        ],
        check=True,
    )  # fmt: skip
    return path


def silent_video_no_audio(path: Path, seconds: float = 2.0) -> Path:
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", f"testsrc2=size=160x120:rate=15:duration={seconds}",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )  # fmt: skip
    return path


def audio_only_file(path: Path, seconds: float = 2.0) -> Path:
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac", str(path)],
        check=True,
    )  # fmt: skip
    return path
