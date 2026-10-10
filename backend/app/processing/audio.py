"""Audio extraction (FFmpeg) and loading (NumPy).

The audio is decoded once to 16 kHz mono 16-bit PCM WAV — the format Whisper
expects — and that same file feeds the silence detector, so there is exactly
one intermediate conversion.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from app.core.errors import MediaError
from app.processing.media import FFmpegError, run_tool

SAMPLE_RATE = 16_000


def extract_audio(src: Path, dst: Path, timeout: float) -> Path:
    """Decode the first audio stream of ``src`` into a 16 kHz mono WAV at ``dst``."""
    args = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(src),
        "-map",
        "0:a:0",
        "-vn",
        "-sn",
        "-dn",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-c:a",
        "pcm_s16le",
        str(dst),
    ]
    try:
        run_tool(args, timeout, "audio extraction")
    except FFmpegError as exc:
        dst.unlink(missing_ok=True)
        raise MediaError("audio_extraction_failed", "Could not decode the audio track of this video.") from exc
    if not dst.exists() or dst.stat().st_size <= 44:
        dst.unlink(missing_ok=True)
        raise MediaError("audio_extraction_failed", "The audio track is empty.")
    return dst


def load_wav(path: Path) -> tuple[np.ndarray, int]:
    """Load a 16-bit PCM WAV as float32 in [-1, 1]. Multi-channel input is down-mixed."""
    with wave.open(str(path), "rb") as wf:
        if wf.getsampwidth() != 2:
            raise ValueError("expected 16-bit PCM audio")
        channels = wf.getnchannels()
        sr = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, sr


def write_wav(path: Path, samples: np.ndarray, sr: int = SAMPLE_RATE) -> None:
    """Write float samples in [-1, 1] as 16-bit mono PCM (used by tests and tooling)."""
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
