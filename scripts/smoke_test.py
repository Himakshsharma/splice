#!/usr/bin/env python3
"""End-to-end smoke test for a running SPLICE server (local or deployed).

    python scripts/smoke_test.py                       # http://localhost:8000
    python scripts/smoke_test.py --base-url https://<you>-splice.hf.space

1. Generates a short video with known speech and silence (FFmpeg + flite TTS,
   falling back to tones if flite is unavailable).
2. Uploads it through the public API and polls the real job status.
3. Checks the transcript, silence intervals and edit decisions.
4. Downloads the output and validates it with FFprobe.
5. Deletes the job and confirms it is gone.

Only the Python standard library and ffmpeg/ffprobe are required.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

PHRASES = ["Hello and welcome to splice", "This pause should be removed", "Thanks for watching"]
GAPS = [1.0, 2.5, 2.0, 1.0]  # leading, between phrases, trailing silence (seconds)


def log(msg: str) -> None:
    print(f"[smoke] {msg}", flush=True)


def has_flite() -> bool:
    out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    return " flite " in out


def make_video(path: Path) -> bool:
    """Returns True if real synthesized speech was used."""
    speech = has_flite()
    inputs: list[str] = []
    labels: list[str] = []
    filters: list[str] = []
    idx = 0
    for i, gap in enumerate(GAPS):
        inputs += ["-f", "lavfi", "-i", f"anullsrc=r=22050:cl=mono:d={gap}"]
        labels.append(f"[{idx}:a]")
        idx += 1
        if i < len(PHRASES):
            src = f"flite=text='{PHRASES[i]}':voice=slt" if speech else "sine=frequency=300:duration=1.5"
            inputs += ["-f", "lavfi", "-i", src]
            filters.append(f"[{idx}:a]aresample=22050,volume=2[s{idx}]")
            labels.append(f"[s{idx}]")
            idx += 1
    filters.append(f"{''.join(labels)}concat=n={len(labels)}:v=0:a=1[aout]")
    cmd = [
        "ffmpeg", "-nostdin", "-loglevel", "error", "-y", *inputs,
        "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
        "-filter_complex", ";".join(filters), "-map", f"{idx}:v", "-map", "[aout]", "-shortest",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "44100", str(path),
    ]  # fmt: skip
    subprocess.run(cmd, check=True)
    return speech


def ffprobe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    return json.loads(out)


def request(method: str, url: str, token: str | None = None, body: bytes | None = None,
            content_type: str | None = None, timeout: float = 120) -> tuple[int, bytes]:  # fmt: skip
    req = urllib.request.Request(url, data=body, method=method)
    if token:
        req.add_header("X-Job-Token", token)
    if content_type:
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


def multipart(file_path: Path, settings: dict) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="settings"\r\n\r\n{json.dumps(settings)}\r\n'.encode(),
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
            "Content-Type: video/mp4\r\n\r\n"
        ).encode()
        + file_path.read_bytes()
        + b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def check(cond: bool, msg: str) -> None:
    if not cond:
        log(f"FAIL: {msg}")
        sys.exit(1)
    log(f"ok   {msg}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--timeout", type=float, default=600, help="max seconds to wait for processing")
    ap.add_argument("--keep", action="store_true", help="do not delete the job at the end")
    args = ap.parse_args()
    base = args.base_url.rstrip("/")

    status, body, wake_deadline = 0, b"", time.monotonic() + 240  # free hosts may need to wake up
    while time.monotonic() < wake_deadline:
        try:
            status, body = request("GET", f"{base}/api/health", timeout=60)
            if status == 200:
                break
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            log(f"     waiting for server ({exc})")
        time.sleep(5)
    check(status == 200, f"health endpoint reachable ({status})")
    health = json.loads(body)
    log(f"server: ffmpeg={health['ffmpeg']} whisper={health['whisper_engine']} available={health['whisper_available']}")

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "smoke.mp4"
        speech = make_video(src)
        src_dur = float(ffprobe(src)["format"]["duration"])
        log(f"generated {src_dur:.1f}s test video ({'synthesized speech' if speech else 'tones'})")

        payload, ctype = multipart(src, {"min_silence_duration": 0.6, "mode": "final", "language": "en"})
        status, body = request("POST", f"{base}/api/jobs", body=payload, content_type=ctype, timeout=300)
        check(status == 201, f"upload accepted ({status}: {body[:200]!r})")
        created = json.loads(body)
        job_id, token = created["job_id"], created["access_token"]

        seen: list[str] = []
        deadline = time.monotonic() + args.timeout
        while True:
            status, body = request("GET", f"{base}/api/jobs/{job_id}", token=token)
            job = json.loads(body)
            if not seen or seen[-1] != job["status"]:
                seen.append(job["status"])
                log(f"     status -> {job['status']} ({job['stage_label']})")
            if job["status"] in ("completed", "failed", "cancelled", "expired"):
                break
            if time.monotonic() > deadline:
                check(False, "job finished before timeout")
            time.sleep(1.5)
        check(job["status"] == "completed", f"job completed (error={job.get('error')})")

        status, body = request("GET", f"{base}/api/jobs/{job_id}/transcript", token=token)
        transcript = json.loads(body)
        check(status == 200 and transcript["status"] in ("completed", "empty", "unavailable", "disabled"),
              f"transcript returned (status={transcript['status']})")  # fmt: skip
        if transcript["segments"]:
            log("     transcript: " + " | ".join(s["text"] for s in transcript["segments"]))

        status, body = request("GET", f"{base}/api/jobs/{job_id}/edit-plan", token=token)
        plan = json.loads(body)
        check(status == 200 and len(plan["silences"]) >= 2, f"silence intervals detected ({len(plan['silences'])})")
        check(plan["cut_count"] >= 2, f"edit decisions generated ({plan['cut_count']} cuts)")

        status, video = request("GET", f"{base}/api/jobs/{job_id}/download?token={token}", timeout=300)
        check(status == 200 and len(video) > 1000, f"download returned {len(video)} bytes")
        out = Path(tmp) / "out.mp4"
        out.write_bytes(video)
        probe = ffprobe(out)
        kinds = {s["codec_type"]: s["codec_name"] for s in probe["streams"]}
        out_dur = float(probe["format"]["duration"])
        check(kinds.get("video") == "h264" and kinds.get("audio") == "aac", f"output is H.264/AAC ({kinds})")
        check(out_dur < src_dur - 2.0, f"output shorter than input ({src_dur:.1f}s -> {out_dur:.1f}s)")

        if not args.keep:
            status, _ = request("DELETE", f"{base}/api/jobs/{job_id}", token=token)
            check(status == 204, "job deleted")
            status, _ = request("GET", f"{base}/api/jobs/{job_id}", token=token)
            check(status == 404, "deleted job no longer accessible")

    log("SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
