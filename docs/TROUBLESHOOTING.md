# Troubleshooting

## Installation

**`py -3.11` not found (Windows).** Install Python 3.11 (`winget install Python.Python.3.11`) and reopen the terminal.
`py --list` shows installed versions.

**`Activate.ps1 cannot be loaded because running scripts is disabled`.** Run
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` (affects only the current window), then activate again,
or use `.venv\Scripts\activate.bat` from Command Prompt.

**`pip install` spends ages downloading `torch` (several GB).** Install the CPU wheel instead:
`pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt`, or skip PyTorch entirely
with `pip install -r requirements-optional.txt` and `WHISPER_ENGINE=faster-whisper`.

**`numba`/`llvmlite` build errors while installing openai-whisper.** You're on an unsupported Python version. Use 3.11.

**`npm install` fails / old Node.** `node --version` must be 20 or newer.

## FFmpeg

**`/api/health` shows `"ffmpeg": false` or uploads fail with "FFmpeg could not process this video".** `ffmpeg` and
`ffprobe` must both be on PATH in the terminal that runs uvicorn. Check with `ffmpeg -version` and `ffprobe -version`;
on Windows add the FFmpeg `bin` folder to PATH and open a new terminal.

**"Unsupported container" for a file that plays fine.** SPLICE accepts MP4/MOV/M4V, WebM and MKV containers. Convert
others: `ffmpeg -i input.avi -c:v libx264 -c:a aac output.mp4`.

**"This video has no audio track".** Screen recordings sometimes have no sound track; SPLICE needs audio to find
silence.

## Whisper

**Transcript says "Whisper could not run on this server".** The engine package isn't installed or the weights couldn't
be downloaded. Check `"whisper_available"` in `/api/health`. The first run downloads weights from the internet
(`openai-whisper`: `~/.cache/whisper`; `faster-whisper`: Hugging Face cache) — behind a proxy or offline, pre-download
them on a connected machine and set `WHISPER_CACHE_DIR`. The job still completes using energy-based cuts.

**Transcription is slow.** Use `tiny`, keep clips short, or switch to `WHISPER_ENGINE=faster-whisper`.

**Out of memory / process killed during transcription.** `openai-whisper` with PyTorch needs about 1 GB+ for `tiny`
and more for `base`. Use `faster-whisper`, set `WHISPER_ALLOWED_MODELS=tiny` and `MAX_CONCURRENT_JOBS=1`.

**Wrong language detected.** Pick the language in *Output and transcription → Language* instead of auto-detect.

## Cutting results

**Nothing was cut.** Your room noise is louder than the threshold. Look at the dashed threshold line on the timeline:
raise the threshold (e.g. −40 → −32 dBFS) until it sits above the quiet parts.

**Words get clipped.** Increase *Keep before/after speech*, lower the threshold, or make sure *Protect words Whisper
hears* is on.

**Cuts feel too frequent / jumpy.** Increase *Minimum pause to cut*.

## Uploads and CORS

**`413 file_too_large` / "The limit here is N MB".** Raise `MAX_UPLOAD_MB` (and make sure your host allows it) or
compress the video: `ffmpeg -i in.mp4 -vf scale=-2:720 -crf 28 out.mp4`.

**Browser console: "blocked by CORS policy".** The UI's origin isn't in `FRONTEND_ORIGINS`. Add the exact origin
(scheme + host, no trailing slash), e.g. `https://splice-abc.vercel.app`, and restart/redeploy the backend.

**`429 rate_limited`.** Too many uploads from one IP in an hour; adjust `RATE_LIMIT_JOBS_PER_HOUR` (0 disables).

**`503 server_busy`.** All worker and queue slots are taken. Wait, or raise `MAX_CONCURRENT_JOBS`/`MAX_QUEUED_JOBS`
if the machine has the CPU and RAM for it.

## Rendering

**"Processing exceeded the …s limit".** Increase `JOB_TIMEOUT_SECONDS`, use *Quick preview*, a lower resolution, or
a shorter clip.

**Edited video plays in some browsers but not others.** Output is H.264/AAC MP4 which all major browsers play;
headless/open-source Chromium builds lack an H.264 decoder (the download is still valid).

**"FFmpeg could not process this video".** Check the server log (JSON lines) for the `stderr_tail` of the failed step.
Unusual codecs (e.g. some ProRes variants) may need converting first.

## Deployment

**Render build fails at `npm install` / `vite build`.** Run `cd frontend && npm install && npx vite build` locally to
see the same error. Commit the generated `package-lock.json` for reproducible builds.

**Render: first request hangs for ~1 minute.** The free service was asleep. The UI retries automatically.

**Render: job fails with `server_restarted`.** The instance restarted (deploy, sleep or platform maintenance) while
processing; retry. Free instances are not durable.

**Vercel page loads but every action fails.** `VITE_API_BASE_URL` is missing or wrong (it's baked in at build time —
redeploy after changing it), or CORS isn't configured on Render.

**Hugging Face: "requires a paid plan".** Docker Spaces need HF PRO; use Render instead (docs/DEPLOYMENT.md).
