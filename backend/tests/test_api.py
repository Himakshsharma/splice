"""API tests, including a full upload -> process -> download -> delete round trip."""

from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import upload, wait_for_terminal
from media_factory import HAS_FFMPEG, audio_only_file, silent_video_no_audio, tone_video

from app.processing.media import FFmpegError, probe
from app.services.job_store import iso, utcnow

needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe not installed")
PATTERN = [("tone", 1.2), ("silence", 1.5), ("tone", 1.2), ("silence", 1.0), ("tone", 0.8)]


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg missing")
    return tone_video(tmp_path_factory.mktemp("api") / "talk.mp4", PATTERN)


def H(token: str) -> dict:
    return {"X-Job-Token": token}


def test_health_and_config(client):
    h = client.get("/api/health").json()
    assert h["ffmpeg"] is HAS_FFMPEG and h["whisper_engine"] == "none"
    assert "version" in h and "temp" not in str(h)  # no paths leaked
    c = client.get("/api/config").json()
    assert c["max_upload_mb"] == 50 and ".mp4" in c["accepted_extensions"]
    assert c["defaults"]["silence_threshold_db"] == -40.0


def test_missing_job_and_bad_ids(client):
    assert client.get("/api/jobs/" + "0" * 32, headers=H("x")).status_code == 404
    r = client.get("/api/jobs/../../etc/passwd")
    assert r.status_code == 404
    body = client.get("/api/jobs/not-a-hex-id", headers=H("x")).json()
    assert body["error"]["code"] == "job_not_found"


def test_unsupported_extension(client, tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("hello")
    r = upload(client, f)
    assert r.status_code == 415 and r.json()["error"]["code"] == "unsupported_file_type"


def test_corrupt_video_rejected_and_not_kept(client, tmp_path):
    f = tmp_path / "broken.mp4"
    f.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"garbage" * 500)
    r = upload(client, f)
    assert r.status_code == 422 and r.json()["error"]["code"] == "unreadable_media"
    jobs_dir = client.app.state.jobs.settings.jobs_dir
    assert list(jobs_dir.iterdir()) == []  # staging cleaned up


def test_empty_file(client, tmp_path):
    f = tmp_path / "empty.mp4"
    f.write_bytes(b"")
    r = upload(client, f)
    assert r.status_code == 422 and r.json()["error"]["code"] == "empty_file"


@needs_ffmpeg
def test_missing_audio_and_audio_only(client, tmp_path):
    r = upload(client, silent_video_no_audio(tmp_path / "mute.mp4"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "no_audio_stream"
    r = upload(client, audio_only_file(tmp_path / "podcast.mp4"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "no_video_stream"


@needs_ffmpeg
def test_upload_size_limit(client_factory, tmp_path):
    c = client_factory(max_upload_mb="1")
    big = tmp_path / "big.mp4"
    big.write_bytes(b"\0" * (2 * 1024 * 1024))
    r = upload(c, big)
    assert r.status_code == 413 and r.json()["error"]["code"] == "file_too_large"


def test_invalid_settings(client, video):
    r = upload(client, video, settings={"silence_threshold_db": 20})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_settings"
    assert r.json()["error"]["details"]["fields"][0]["field"] == "silence_threshold_db"
    r = upload(client, video, settings={"whisper_model": "large-v3"})
    assert r.status_code == 422


@needs_ffmpeg
def test_full_pipeline_round_trip(client, video):
    r = upload(client, video, settings={"min_silence_duration": 0.5, "padding_before": 0.1, "padding_after": 0.1})
    assert r.status_code == 201, r.text
    job_id, token = r.json()["job_id"], r.json()["access_token"]
    assert r.json()["job"]["status"] == "queued"

    # token is required
    assert client.get(f"/api/jobs/{job_id}").status_code == 404
    assert client.get(f"/api/jobs/{job_id}", headers=H("wrong")).status_code == 404

    job = wait_for_terminal(client, job_id, token)
    assert job["status"] == "completed", job
    assert "rendering" in job["_seen"] or "completed" in job["_seen"]
    res = job["result"]
    assert res["original_duration"] == pytest.approx(5.7, abs=0.15)
    assert res["cut_count"] == 2 and res["retained_count"] == 3
    assert res["removed_duration"] > 1.8
    assert res["transcript_status"] == "disabled"
    assert job["source"]["width"] == 320 and job["source"]["has_audio"]

    t = client.get(f"/api/jobs/{job_id}/transcript", headers=H(token)).json()
    assert t["status"] == "disabled" and t["segments"] == []

    plan = client.get(f"/api/jobs/{job_id}/edit-plan", headers=H(token)).json()
    assert plan["cut_count"] == 2 and len(plan["silences"]) == 2
    assert len(plan["waveform"]["db"]) > 10
    assert plan["output_duration"] == pytest.approx(res["output_duration"], abs=0.35)

    dl = client.get(f"/api/jobs/{job_id}/download", params={"token": token})
    assert dl.status_code == 200 and dl.headers["content-type"] == "video/mp4"
    assert "attachment" in dl.headers["content-disposition"] and "talk-splice.mp4" in dl.headers["content-disposition"]
    out = client.app.state.jobs.settings.temp_dir / "check.mp4"
    out.write_bytes(dl.content)
    info = probe(out)
    assert info.has_video and info.has_audio and info.duration == pytest.approx(res["output_duration"], abs=0.2)

    ranged = client.get(f"/api/jobs/{job_id}/download?inline=1", params={"token": token}, headers={"Range": "bytes=0-99"})
    assert ranged.status_code == 206 and len(ranged.content) == 100

    # delete removes files and metadata
    job_dir = client.app.state.jobs.paths(job_id).root
    assert job_dir.exists()
    assert client.delete(f"/api/jobs/{job_id}", headers=H(token)).status_code == 204
    assert not job_dir.exists()
    assert client.get(f"/api/jobs/{job_id}", headers=H(token)).status_code == 404


@needs_ffmpeg
def test_rerender_reuses_analysis_with_new_settings(client, video):
    r = upload(client, video, settings={"mode": "preview"})
    job_id, token = r.json()["job_id"], r.json()["access_token"]
    first = wait_for_terminal(client, job_id, token)
    assert first["status"] == "completed" and first["result"]["render_mode"] == "preview"

    new = {**first["settings"], "mode": "final", "min_silence_duration": 5.0, "padding_before": 0.1, "padding_after": 0.1}
    rr = client.post(f"/api/jobs/{job_id}/render", headers=H(token), json={"settings": new})
    assert rr.status_code == 202, rr.text
    second = wait_for_terminal(client, job_id, token)
    assert second["status"] == "completed"
    assert "transcribing" not in second["_seen"]  # transcription was not repeated
    assert second["result"]["render_mode"] == "final"
    assert second["result"]["cut_count"] == 0  # no silence is 5s long

    bad = {**new, "whisper_model": "base"}
    assert client.post(f"/api/jobs/{job_id}/render", headers=H(token), json={"settings": bad}).status_code == 422


@needs_ffmpeg
def test_failed_render_cleans_up_files(client, video, monkeypatch):
    import app.services.jobs as jobs_mod

    def boom(*_a, **_k):
        raise FFmpegError("simulated encoder crash", "stderr with /secret/path")

    monkeypatch.setattr(jobs_mod, "render", boom)
    r = upload(client, video)
    job_id, token = r.json()["job_id"], r.json()["access_token"]
    job = wait_for_terminal(client, job_id, token)
    assert job["status"] == "failed"
    assert job["error"]["code"] == "processing_failed"
    assert "/secret/path" not in job["error"]["message"]
    assert not client.app.state.jobs.paths(job_id).root.exists()
    assert client.get(f"/api/jobs/{job_id}/download", headers=H(token)).status_code == 409


@needs_ffmpeg
def test_expired_jobs_are_cleaned(client, video):
    r = upload(client, video, settings={"mode": "preview", "output_resolution": "480p"})
    job_id, token = r.json()["job_id"], r.json()["access_token"]
    assert wait_for_terminal(client, job_id, token)["status"] == "completed"
    mgr = client.app.state.jobs
    mgr.store.update(job_id, expires_at=iso(utcnow() - timedelta(minutes=1)))

    assert client.get(f"/api/jobs/{job_id}/download", headers=H(token)).status_code == 410
    stats = mgr.run_cleanup()
    assert stats["expired"] == 1
    assert not mgr.paths(job_id).root.exists()
    assert client.get(f"/api/jobs/{job_id}", headers=H(token)).json()["status"] == "expired"


def test_orphan_directories_are_removed(client):
    mgr = client.app.state.jobs
    orphan = mgr.settings.jobs_dir / "upload-deadbeef"
    orphan.mkdir(parents=True)
    (orphan / "source.mp4").write_bytes(b"x")
    assert mgr.run_cleanup()["orphans"] == 1
    assert not orphan.exists()


@needs_ffmpeg
def test_restart_marks_interrupted_jobs_failed(client, video):
    mgr = client.app.state.jobs
    rec, token = mgr.store.create("x.mp4", {})
    mgr.paths(rec.id).root.mkdir(parents=True)
    mgr.recover_interrupted()
    job = client.get(f"/api/jobs/{rec.id}", headers=H(token)).json()
    assert job["status"] == "failed" and job["error"]["code"] == "server_restarted"
    assert not mgr.paths(rec.id).root.exists()


def test_rate_limit(client_factory, tmp_path):
    c = client_factory(rate_limit_jobs_per_hour="2")
    f = tmp_path / "x.txt"
    f.write_text("x")
    codes = [upload(c, f).status_code for _ in range(3)]
    assert codes == [415, 415, 429]


def test_cors_allows_only_configured_origin(client_factory):
    c = client_factory(frontend_origins="https://splice.example")
    ok = c.options("/api/health", headers={"Origin": "https://splice.example", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "https://splice.example"
    bad = c.options("/api/health", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers
