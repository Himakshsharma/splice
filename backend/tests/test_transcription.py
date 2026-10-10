"""Transcription wiring.

* ``test_pipeline_uses_whisper_word_timings`` replaces the model call with a test
  double so we can check *how the pipeline uses* Whisper output (storage, API,
  speech protection) quickly and offline. It never ships in the app.
* ``test_real_whisper_transcribes_synthetic_speech`` runs the actual open-source
  model on FFmpeg-synthesised speech. It downloads weights, so it is opt-in:
  ``SPLICE_RUN_WHISPER=1 pytest -m whisper``.
"""

from __future__ import annotations

import os

import pytest
from conftest import upload, wait_for_terminal
from media_factory import HAS_FFMPEG, HAS_FLITE, speech_video, tone_video

from app.processing import transcribe as tr
from app.processing.audio import extract_audio, load_wav


def test_unknown_engine_reports_unavailable():
    assert not tr.engine_installed("not-an-engine")


def test_transcript_round_trip_and_spans():
    t = tr.Transcript(
        "openai-whisper",
        "tiny",
        "en",
        [
            tr.Segment(0.0, 1.0, "hello", [tr.Word(0.1, 0.4, "hello")]),
            tr.Segment(2.0, 3.0, "world", []),
        ],
    )
    again = tr.Transcript.from_dict(t.to_dict())
    assert again.speech_spans() == [(0.1, 0.4), (2.0, 3.0)]


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg missing")
def test_missing_engine_degrades_honestly(client_factory, tmp_path):
    c = client_factory(whisper_engine="faster-whisper")  # not installed in the test env
    if tr.engine_installed("faster-whisper"):
        pytest.skip("faster-whisper is installed here")
    video = tone_video(tmp_path / "v.mp4", [("tone", 1.0), ("silence", 1.0), ("tone", 1.0)])
    r = upload(c, video)
    job = wait_for_terminal(c, r.json()["job_id"], r.json()["access_token"])
    assert job["status"] == "completed"
    assert job["result"]["transcript_status"] == "unavailable"
    assert any("energy only" in w for w in job["result"]["warnings"])


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg missing")
def test_pipeline_uses_whisper_word_timings(client_factory, tmp_path, monkeypatch):
    c = client_factory(whisper_engine="openai-whisper")
    # Whisper reports a word inside a 3s "silent" gap: energy alone would cut it.
    video = tone_video(tmp_path / "v.mp4", [("tone", 1.0), ("silence", 3.0), ("tone", 1.0)])

    def fake_transcribe(audio, sr, **kwargs):
        assert sr == 16_000 and audio.size > 0  # the real extracted audio is passed in
        return tr.Transcript(
            "openai-whisper",
            kwargs["model_name"],
            "en",
            [
                tr.Segment(0.0, 1.0, "first", [tr.Word(0.05, 0.9, "first")]),
                tr.Segment(2.2, 2.6, "whisper", [tr.Word(2.2, 2.6, "whisper")]),
                tr.Segment(4.0, 5.0, "last", [tr.Word(4.05, 4.9, "last")]),
            ],
        )

    monkeypatch.setattr(tr, "transcribe", fake_transcribe)
    r = upload(c, video, settings={"protect_speech": True, "padding_before": 0.1, "padding_after": 0.1})
    job_id, token = r.json()["job_id"], r.json()["access_token"]
    job = wait_for_terminal(c, job_id, token)
    assert job["status"] == "completed" and job["result"]["transcript_status"] == "completed"

    transcript = c.get(f"/api/jobs/{job_id}/transcript", headers={"X-Job-Token": token}).json()
    assert [s["text"] for s in transcript["segments"]] == ["first", "whisper", "last"]

    plan = c.get(f"/api/jobs/{job_id}/edit-plan", headers={"X-Job-Token": token}).json()
    kept = [d for d in plan["decisions"] if d["decision"] == "retain"]
    assert any(d["source_start"] <= 2.2 and d["source_end"] >= 2.6 for d in kept)  # protected word survived
    assert job["result"]["cut_count"] == 2  # the 3s gap is cut on both sides of the word


@pytest.mark.whisper
@pytest.mark.skipif(os.environ.get("SPLICE_RUN_WHISPER") != "1", reason="opt-in: set SPLICE_RUN_WHISPER=1")
@pytest.mark.skipif(not (HAS_FFMPEG and HAS_FLITE), reason="needs ffmpeg built with flite")
def test_real_whisper_transcribes_synthetic_speech(tmp_path):
    engine = os.environ.get("WHISPER_ENGINE", "openai-whisper")
    if not tr.engine_installed(engine):
        pytest.skip(f"{engine} not installed")
    video = speech_video(tmp_path / "speech.mp4", ["Hello and welcome to the demo", "Thanks for watching"], [0.5, 2.0, 0.5])
    samples, sr = load_wav(extract_audio(video, tmp_path / "a.wav", timeout=60))
    t = tr.transcribe(samples, sr, engine=engine, model_name="tiny", language="en")
    text = " ".join(s.text for s in t.segments).lower()
    assert "welcome" in text or "watching" in text
    assert t.speech_spans() and all(b > a for a, b in t.speech_spans())
