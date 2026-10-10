"""Energy-based silence detection with NumPy.

Pipeline:  waveform -> overlapping frames -> RMS -> dBFS -> threshold ->
runs of silent frames -> merge tiny speech blips -> drop short silences.

This module only *finds* silence. Deciding what to cut (padding, Whisper speech
protection, minimum segment length) lives in ``edit_plan.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Analysis resolution: 30 ms windows every 10 ms.
FRAME_SECONDS = 0.030
HOP_SECONDS = 0.010
DB_FLOOR = -100.0  # value used for digital silence instead of -inf
# Bursts of "loud" frames shorter than this inside a silence (a click, a breath)
# do not split the silence in two.
DEFAULT_MERGE_GAP = 0.06


@dataclass(frozen=True)
class Interval:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def _validate(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    arr = np.asarray(samples, dtype=np.float64)
    if arr.ndim == 2:  # (n, channels) -> mono
        arr = arr.mean(axis=1)
    if arr.ndim != 1:
        raise ValueError("samples must be a 1-D (mono) or 2-D (n, channels) array")
    if not np.all(np.isfinite(arr)):
        raise ValueError("samples contain NaN or infinite values")
    return arr


def frame_rms(
    samples: np.ndarray, sample_rate: int, frame_seconds: float = FRAME_SECONDS, hop_seconds: float = HOP_SECONDS
) -> np.ndarray:
    """Root-mean-square energy of each analysis frame.

    The signal is zero-padded so that every sample belongs to at least one frame;
    audio shorter than a frame yields a single frame.
    """
    arr = _validate(samples, sample_rate)
    if arr.size == 0:
        return np.zeros(0)
    frame = max(1, round(frame_seconds * sample_rate))
    hop = max(1, round(hop_seconds * sample_rate))
    n_frames = 1 + max(0, int(np.ceil((arr.size - frame) / hop)))
    needed = (n_frames - 1) * hop + frame
    if needed > arr.size:
        arr = np.pad(arr, (0, needed - arr.size))
    windows = np.lib.stride_tricks.sliding_window_view(arr, frame)[::hop][:n_frames]
    return np.sqrt(np.mean(np.square(windows), axis=1))


def to_dbfs(rms: np.ndarray | float, floor: float = DB_FLOOR) -> np.ndarray:
    """Convert linear RMS (full scale = 1.0) to dBFS without ever taking log(0)."""
    rms = np.asarray(rms, dtype=np.float64)
    min_linear = 10.0 ** (floor / 20.0)
    return 20.0 * np.log10(np.maximum(rms, min_linear))


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Return [start, end) index pairs of consecutive True values."""
    if mask.size == 0:
        return []
    padded = np.concatenate(([False], mask, [False]))
    edges = np.flatnonzero(np.diff(padded.astype(np.int8)))
    return list(zip(edges[0::2].tolist(), edges[1::2].tolist(), strict=True))


def merge_intervals(intervals: list[Interval], max_gap: float) -> list[Interval]:
    """Merge intervals whose gap is <= max_gap. Input need not be sorted."""
    merged: list[Interval] = []
    for iv in sorted(intervals, key=lambda i: i.start):
        if merged and iv.start - merged[-1].end <= max_gap:
            merged[-1] = Interval(merged[-1].start, max(merged[-1].end, iv.end))
        else:
            merged.append(iv)
    return merged


def detect_silence(
    samples: np.ndarray,
    sample_rate: int,
    threshold_db: float,
    min_silence_duration: float,
    merge_gap: float = DEFAULT_MERGE_GAP,
    frame_seconds: float = FRAME_SECONDS,
    hop_seconds: float = HOP_SECONDS,
) -> list[Interval]:
    """Find silent intervals (seconds) at least ``min_silence_duration`` long.

    Silence touching the beginning or end of the audio is reported up to 0.0 and
    the exact audio duration respectively.
    """
    if min_silence_duration <= 0:
        raise ValueError("min_silence_duration must be positive")
    arr = _validate(samples, sample_rate)
    if arr.size == 0:
        return []
    duration = arr.size / sample_rate
    db = to_dbfs(frame_rms(arr, sample_rate, frame_seconds, hop_seconds))
    silent = db < threshold_db

    raw: list[Interval] = []
    for a, b in _runs(silent):
        start = 0.0 if a == 0 else a * hop_seconds + frame_seconds / 2
        end = duration if b == len(silent) else (b - 1) * hop_seconds + frame_seconds / 2
        start, end = max(0.0, start), min(duration, end)
        if end > start:
            raw.append(Interval(start, end))

    merged = merge_intervals(raw, merge_gap)
    return [Interval(round(iv.start, 4), round(iv.end, 4)) for iv in merged if iv.duration + 1e-9 >= min_silence_duration]


def waveform_envelope(samples: np.ndarray, sample_rate: int, max_points: int = 1200) -> tuple[float, list[float]]:
    """Downsampled loudness curve (dBFS) for the timeline / 3D visualisation.

    Returns (seconds_per_point, values). Values are the loudest frame in each bucket
    so short words stay visible.
    """
    db = to_dbfs(frame_rms(samples, sample_rate))
    if db.size == 0:
        return HOP_SECONDS, []
    bucket = max(1, int(np.ceil(db.size / max_points)))
    pad = (-db.size) % bucket
    if pad:
        db = np.concatenate([db, np.full(pad, DB_FLOOR)])
    env = db.reshape(-1, bucket).max(axis=1)
    return bucket * HOP_SECONDS, [round(float(v), 1) for v in env]
