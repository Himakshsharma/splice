# SPLICE architecture

This document explains how SPLICE works and why it is built this way — written so you can walk an interviewer
through it. File references point at the real implementation.

```
browser ──upload──▶ FastAPI ──▶ SQLite (job row) + private job folder
   ▲                   │
   │ poll status        ▼
   │            worker thread pool
   │   validate ─▶ extract audio ─▶ transcribe ─▶ detect silence ─▶ plan ─▶ render ─▶ verify
   └──── stream / download MP4 ◀──────────────────────────────────────────────────────┘
```

## 1. Why Whisper is used

Whisper is an open-source speech-recognition model trained on 680k hours of multilingual audio. It is robust to
accents, background noise and microphone quality, runs locally (no API key, no per-minute cost) and returns timestamps.
SPLICE uses it to know *where words are*, show a searchable transcript, and protect speech from being cut.
`tiny` (39M parameters) is the default because it runs on a CPU in reasonable time; `base` is selectable when the host
allows. Implementation: [`backend/app/processing/transcribe.py`](../backend/app/processing/transcribe.py).

Two engines run the same Whisper weights:

| | `openai-whisper` | `faster-whisper` |
| --- | --- | --- |
| Runtime | PyTorch | CTranslate2 (C++), int8 on CPU |
| RAM for `tiny` | ~1 GB incl. PyTorch | a few hundred MB |
| Progress | none (single call) | per segment (real percentage) |
| Used for | local development (reference) | the Docker image / free hosting |

## 2. What Whisper does and does not do

It **does** convert speech to text with segment- and word-level timestamps (word timings via cross-attention
alignment). It **does not** detect silence: segments often include pauses, timestamps drift by tens to hundreds of
milliseconds, and a gap between segments is not proof of silence. Cutting only on transcript gaps clips word endings
and breaks sentence rhythm. So SPLICE measures silence from the signal (section 5) and uses Whisper's word spans
only as a veto: never cut inside something Whisper heard.

## 3. How FFmpeg extracts audio

[`audio.py`](../backend/app/processing/audio.py) runs:

```
ffmpeg -nostdin -i source.mp4 -map 0:a:0 -vn -ac 1 -ar 16000 -c:a pcm_s16le audio.wav
```

First audio stream only, video dropped, down-mixed to mono, resampled to 16 kHz, 16-bit PCM. That is exactly
Whisper's input format, and the same file feeds the silence detector — one decode, no further conversions. Exit codes
are checked; stderr tails go to server logs only (the user sees a plain-language message). Commands are argument
lists, never shell strings, and every path is server-generated.

## 4. How NumPy analyses the waveform

The WAV is read with the standard `wave` module into an `int16` array and scaled to `float32` in [-1, 1].
[`silence.py`](../backend/app/processing/silence.py) then frames it with
`numpy.lib.stride_tricks.sliding_window_view` — a zero-copy view of overlapping 30 ms windows every 10 ms — and
computes per-frame energy in one vectorised expression. A 5-minute clip is ~30,000 frames, processed in milliseconds.

## 5. RMS energy and dBFS

- **RMS** (root mean square) of a frame: `sqrt(mean(x²))` — the frame's average power, a robust loudness measure.
- **dBFS** (decibels relative to full scale): `20 · log10(RMS)`, where a full-scale sine is about −3 dBFS and digital
  silence would be −∞. SPLICE clamps RMS to `10^-5` first, so the floor is −100 dBFS and `log(0)` never happens.

Typical values: normal speech −30 to −10 dBFS, a quiet room −60 to −45 dBFS. The default threshold, **−40 dBFS**, sits
between them; noisy recordings need a higher (less negative) threshold.

## 6. How silence intervals are identified

1. `silent = dBFS < threshold` gives a boolean per frame.
2. Runs of `True` are found with `np.diff` on the padded mask → `[start, end)` frame indices.
3. Indices become seconds at frame centres; a run touching the start or end snaps exactly to `0` / the duration, so
   leading and trailing silence are handled correctly.
4. Silences separated by a loud blip shorter than 60 ms (a click, a breath) are merged.
5. Silences shorter than the user's *minimum pause* are discarded — natural short pauses stay.

Covered by unit tests for silence at the start, end and middle, short pauses, continuous tone, entirely silent audio,
very short audio, stereo input and invalid input ([`tests/test_silence.py`](../backend/tests/test_silence.py)).

## 7. From timestamps to an edit decision list

[`edit_plan.py`](../backend/app/processing/edit_plan.py) turns silences into an EDL:

1. Each silence `[s, e]` becomes a cut `[s + padding_after, e − padding_before]` (no padding at the very start/end).
2. Whisper word spans (+50 ms guard) are subtracted from cuts — quiet speech survives.
3. Cuts shorter than 80 ms are ignored (invisible jump, wasted encode).
4. The complement becomes retained segments; retained fragments shorter than the minimum clip length (stray noises
   between cuts) are turned into removals and merged with their neighbours.
5. If nothing remains, the original is kept with a warning instead of producing an empty video.
6. An optional maximum output length trims from the end.
7. Every entry gets source times, output times, duration, decision and reason, and `validate_plan` checks the
   invariants: contiguous, chronological, inside `[0, duration]`, no zero-length entries, at least one retained segment.

This list is the **single source of truth**: the renderer renders exactly its `retain` entries and the dashboard
draws exactly the same list.

## 8. How MoviePy and FFmpeg render the video

[`render.py`](../backend/app/processing/render.py) has two strategies, chosen per job (`RENDER_ENGINE=auto`):

- **MoviePy** (short clips, ≤40 segments): `VideoFileClip(src).subclipped(a, b)` per segment →
  `concatenate_videoclips(..., method="chain")` → optional `resized()` → `write_videofile(libx264, aac, crf, preset)`.
  MoviePy streams frames through an FFmpeg pipe, so memory stays flat. A custom `proglog` logger reports real
  progress and raises to abort on cancel/timeout.
- **FFmpeg filter graph** (long videos or many segments): one pass of `trim/atrim → setpts → concat → scale`. No
  Python in the frame loop, so it is lighter on tiny CPUs; progress comes from `-progress pipe:1`.

Both **re-encode** rather than stream-copy: copying cuts only at keyframes and produces broken timestamps with
variable-frame-rate phone video. Output is H.264 (`yuv420p`, `+faststart` for web playback) + AAC, written as
`output.partial.mp4`, verified with FFprobe (video stream present, audio present if requested, duration within 3% of the
plan) and only then renamed to `output.mp4`.

## 9. Frontend ↔ FastAPI

- `POST /api/jobs` — multipart upload (`file` + `settings` JSON) via `XMLHttpRequest` for upload progress. The server
  streams the body to disk in 1 MB chunks, enforces the size limit while writing, FFprobes it, and only then creates
  the job. It returns a random 128-bit `job_id` and a 256-bit `access_token` (stored as SHA-256).
- `GET /api/jobs/{id}` — polled every ~1.2 s with `X-Job-Token`; exponential backoff on network errors.
- `GET …/edit-plan`, `…/transcript`, `…/download` — results; media URLs carry `?token=` because `<video>` cannot send
  headers. Downloads support HTTP Range so the player can seek.
- All requests go through one typed client ([`frontend/src/services/api.ts`](../frontend/src/services/api.ts)) whose
  types mirror the Pydantic schemas.

## 10. Progress tracking

A validated state machine ([`state_machine.py`](../backend/app/services/state_machine.py)):
`queued → validating → extracting_audio → transcribing → detecting_silence → generating_edit_plan → rendering → completed`,
with `failed`/`cancelled` from any active state, `completed → queued` for re-renders, and `expired` at the end.
Illegal transitions raise. The `progress` field is a real fraction when a stage can measure it (rendering; transcription
with faster-whisper) and `null` otherwise, in which case the UI shows an indeterminate bar. The polling hook ignores
responses for a job that is no longer current, so a slow reply can't overwrite a newer job.

## 11. Temporary media management

- Each job has a private folder `TEMP_DIR/jobs/<job_id>/` — never a static/public directory.
- Uploads land in a staging folder first; it is deleted if validation fails.
- Failed or cancelled jobs delete their files immediately.
- A janitor thread runs every `CLEANUP_INTERVAL_MINUTES`: expired jobs → files deleted + status `expired`; folders with
  no database row (crash leftovers) → deleted; metadata of long-expired jobs → purged.
- On startup, jobs left in an active state (the process died mid-job) are marked `failed` with
  `server_restarted` and their files removed.
- `DELETE /api/jobs/{id}` removes files and metadata on demand (cancels first if running).

All of this is covered by API tests (`test_failed_render_cleans_up_files`, `test_expired_jobs_are_cleaned`,
`test_orphan_directories_are_removed`, `test_restart_marks_interrupted_jobs_failed`).

## 12. Hardest engineering problems

- **Cutting without clipping speech.** Pure energy detection eats quiet syllables; pure Whisper timing is imprecise.
  Combining them (energy decides, Whisper vetoes, padding cushions) is the core design decision.
- **Frame-accurate cuts with A/V sync.** Stream copy can't cut between keyframes; re-encoding through one timeline
  (`trim` + `setpts`, or MoviePy's chained clips) keeps audio and video aligned, including VFR sources.
- **Honest job semantics on fragile hosting.** A thread pool in a sleeping, restartable free instance can't promise
  durability, so the design makes failure visible (restart recovery, deadlines, cancellation checks inside the render
  loop) instead of pretending otherwise.
- **Never trusting the upload.** Size enforced while streaming, content checked with FFprobe, no user-controlled paths,
  no shell, generic error messages.

## 13. Limits of CPU-only free hosting

On Render's free instance (0.1 CPU, 512 MB): PyTorch Whisper doesn't fit comfortably in memory, so the image uses
`faster-whisper` int8 `tiny`; encoding is the slowest step, so clips are capped at 90 s, one job runs at a time, and
the FFmpeg renderer is used. The instance sleeps after 15 minutes and the disk is ephemeral. No GPU is claimed or used.
Processing time scales roughly linearly with clip length and has not been benchmarked on the free tier — expect
minutes, not seconds.

## 14. Production-scale improvements

- Separate API and workers; durable queue (Redis/RQ, Celery or a managed queue) so restarts don't lose work.
- Object storage (S3/R2) with pre-signed upload/download URLs instead of proxying media through the API.
- PostgreSQL for job metadata; user accounts or signed, expiring URLs instead of capability tokens.
- GPU workers for larger Whisper models; batching; hardware encoders (NVENC).
- Neural VAD (Silero/WebRTC) as an alternative detector; filler-word removal from word timestamps.
- Server-Sent Events for progress; resumable/chunked uploads for large files.
- Shared rate limiting (Redis), request quotas, malware scanning of uploads, observability (metrics + tracing).
