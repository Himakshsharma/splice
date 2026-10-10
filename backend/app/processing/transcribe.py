"""Whisper speech recognition.

Two interchangeable engines, both running the open-source Whisper weights locally
(no API key, no network calls at inference time):

* ``openai-whisper`` – the reference PyTorch implementation from OpenAI.
* ``faster-whisper`` – the same weights converted to CTranslate2; int8 on CPU,
  typically several times faster and lighter. Optional install.

Whisper *transcribes*. It is not a silence detector: its timestamps are
approximate (tens to hundreds of ms). SPLICE uses its word timings only to
protect speech from being cut, while cut points come from the energy detector.

Models are loaded lazily on first use, cached for the life of the process, and
guarded by a lock so concurrent jobs never load the same model twice.
"""

from __future__ import annotations

import importlib.util
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

log = logging.getLogger("splice.transcribe")

ProgressFn = Callable[[float], None]


class TranscriptionUnavailable(RuntimeError):
    """Whisper could not run (package missing, weights not downloadable, out of memory)."""


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)


@dataclass
class Transcript:
    engine: str
    model: str
    language: str | None
    segments: list[Segment]

    def speech_spans(self) -> list[tuple[float, float]]:
        """Word timings when available (precise), else segment timings."""
        spans: list[tuple[float, float]] = []
        for seg in self.segments:
            if seg.words:
                spans.extend((w.start, w.end) for w in seg.words if w.end > w.start)
            elif seg.end > seg.start:
                spans.append((seg.start, seg.end))
        return spans

    def to_dict(self) -> dict:
        return {
            "engine": self.engine,
            "model": self.model,
            "language": self.language,
            "segments": [
                {
                    "start": s.start,
                    "end": s.end,
                    "text": s.text,
                    "words": [{"start": w.start, "end": w.end, "text": w.text} for w in s.words],
                }
                for s in self.segments
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Transcript:
        return cls(
            engine=data["engine"],
            model=data["model"],
            language=data.get("language"),
            segments=[
                Segment(s["start"], s["end"], s["text"], [Word(**w) for w in s.get("words", [])]) for s in data["segments"]
            ],
        )


def engine_installed(engine: str) -> bool:
    module = {"openai-whisper": "whisper", "faster-whisper": "faster_whisper"}.get(engine)
    return bool(module) and importlib.util.find_spec(module) is not None


_models: dict[tuple[str, str, str], object] = {}
_load_lock = threading.Lock()
_infer_lock = threading.Lock()  # one inference at a time keeps peak RAM bounded on small hosts


def loaded_models() -> list[str]:
    return sorted({f"{engine}:{name}" for engine, name, _ in _models})


def _resolve_device(device: str) -> str:
    if device != "auto":
        return device
    try:
        import torch  # type: ignore

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _load(engine: str, model_name: str, device: str, cache_dir: Path | None) -> object:
    key = (engine, model_name, device)
    if key in _models:
        return _models[key]
    with _load_lock:
        if key in _models:
            return _models[key]
        if not engine_installed(engine):
            raise TranscriptionUnavailable(f"The {engine} package is not installed on this server.")
        log.info("loading whisper model", extra={"engine": engine, "model": model_name, "device": device})
        try:
            if engine == "openai-whisper":
                import whisper  # type: ignore

                model = whisper.load_model(model_name, device=device, download_root=str(cache_dir) if cache_dir else None)
            else:
                from faster_whisper import WhisperModel  # type: ignore

                model = WhisperModel(
                    model_name,
                    device=device,
                    compute_type="int8" if device == "cpu" else "float16",
                    download_root=str(cache_dir) if cache_dir else None,
                )
        except MemoryError as exc:
            raise TranscriptionUnavailable("Not enough memory to load the Whisper model.") from exc
        except Exception as exc:  # download / checksum / runtime failures
            log.warning("whisper model load failed", extra={"engine": engine, "model": model_name, "error": repr(exc)[:300]})
            raise TranscriptionUnavailable(
                f"The Whisper '{model_name}' model could not be loaded (weights unavailable or download failed)."
            ) from exc
        _models[key] = model
        return model


def transcribe(
    audio: np.ndarray,
    sample_rate: int,
    engine: str,
    model_name: str,
    device: str = "cpu",
    language: str | None = None,
    cache_dir: Path | None = None,
    on_progress: ProgressFn | None = None,
    should_abort: Callable[[], None] | None = None,
) -> Transcript:
    """Transcribe 16 kHz mono float32 audio with timestamps (segment + word level)."""
    if sample_rate != 16_000:
        raise ValueError("Whisper expects 16 kHz audio")
    if audio.size == 0:
        return Transcript(engine, model_name, language, [])
    device = _resolve_device(device)
    model = _load(engine, model_name, device, cache_dir)
    audio = np.ascontiguousarray(audio, dtype=np.float32)
    duration = audio.size / sample_rate

    with _infer_lock:
        if should_abort:
            should_abort()
        try:
            if engine == "openai-whisper":
                result = model.transcribe(  # type: ignore[attr-defined]
                    audio,
                    language=language,
                    fp16=(device == "cuda"),
                    word_timestamps=True,
                    condition_on_previous_text=False,
                    verbose=None,
                )
                segments = [
                    Segment(
                        round(float(s["start"]), 3),
                        round(float(s["end"]), 3),
                        str(s["text"]).strip(),
                        [
                            Word(round(float(w["start"]), 3), round(float(w["end"]), 3), str(w["word"]).strip())
                            for w in s.get("words", [])
                        ],
                    )
                    for s in result.get("segments", [])
                ]
                detected = result.get("language")
            else:
                seg_iter, info = model.transcribe(  # type: ignore[attr-defined]
                    audio,
                    language=language,
                    word_timestamps=True,
                    vad_filter=False,
                    condition_on_previous_text=False,
                )
                segments = []
                for s in seg_iter:  # generator: decoding happens as we iterate
                    if should_abort:
                        should_abort()
                    segments.append(
                        Segment(
                            round(s.start, 3),
                            round(s.end, 3),
                            s.text.strip(),
                            [Word(round(w.start, 3), round(w.end, 3), w.word.strip()) for w in (s.words or [])],
                        )
                    )
                    if on_progress and duration > 0:
                        on_progress(min(1.0, s.end / duration))
                detected = info.language
        except MemoryError as exc:
            raise TranscriptionUnavailable("Ran out of memory while transcribing.") from exc

    segments = [s for s in segments if s.text or s.words]
    return Transcript(engine, model_name, language or detected, segments)
