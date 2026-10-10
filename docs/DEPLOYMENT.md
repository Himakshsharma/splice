# Deploying SPLICE for free

Checked against the providers' documentation in October 2026. Free tiers change — re-check the linked pages if
something below no longer matches.

| | What runs there | Cost | Notes |
| --- | --- | --- | --- |
| **Render** (primary) | Whole app in one Docker container: UI + API + FFmpeg + Whisper | Free web service | 0.1 CPU, 512 MB RAM, sleeps after 15 min idle, ephemeral disk |
| **Vercel** (optional) | The React UI only, talking to Render | Free Hobby plan | UI loads instantly even while Render wakes up |
| Hugging Face Spaces (alternative) | Same Docker container | Docker Spaces now need a paid PRO plan | 2 vCPU / 16 GB — much faster if you have PRO |

Why not put everything on Vercel? Vercel runs short-lived serverless functions; transcription and rendering need a
long-running process with FFmpeg and several hundred MB of model weights, so the Python side lives on Render.

---

## Option A — Render (one URL for the whole app)

### 1. Push the project to GitHub

```bash
cd "splice project"
git init
git add .
git commit -m "SPLICE: AI jump-cut editor"
git branch -M main
git remote add origin https://github.com/<your-username>/splice.git
git push -u origin main
```

(Create the empty `splice` repository on github.com first, without a README.)

### 2. Create the service

1. Sign in at <https://dashboard.render.com> with GitHub.
2. **New → Blueprint**, pick your `splice` repository. Render reads [`render.yaml`](../render.yaml) and proposes one
   free web service named `splice` built from the root `Dockerfile`.
3. Click **Apply**. The first build takes roughly 5–10 minutes: it builds the React UI, installs FFmpeg and
   `faster-whisper`, and downloads the Whisper `tiny` weights into the image.

The Dockerfile does **not** assume FFmpeg exists on the host: it installs it with `apt-get` in the image.

If you prefer the manual path: **New → Web Service → your repo**, Language **Docker**, Dockerfile path `./Dockerfile`,
Instance type **Free**, Health check path `/api/health`, and copy the environment variables from `render.yaml`.

### 3. Verify

Your app is at `https://splice-xxxx.onrender.com` (shown in the dashboard).

```bash
curl https://splice-xxxx.onrender.com/api/health
# {"status":"ok", "ffmpeg":true, "whisper_engine":"faster-whisper", "whisper_available":true, ...}

python scripts/smoke_test.py --base-url https://splice-xxxx.onrender.com
```

The smoke test uploads a generated video with speech and silence, waits for the real pipeline, downloads the MP4 and
validates it with FFprobe. On the free instance expect it to take a few minutes. Then try the UI in a browser:
upload → process → preview → download.

### 4. Optional: set the repository link

In the service's **Environment** tab set `SOURCE_REPO_URL=https://github.com/<you>/splice` (shown on the About page).
To show it in the UI footer too, it's baked in at build time: add a Docker build argument or use the Vercel setup below.

### What to expect on the free instance

- **Sleep:** after 15 minutes without traffic the service stops; the next visit waits ~1 minute. The UI shows
  "The free server is waking up" and retries automatically.
- **Speed:** 0.1 CPU is a small slice. Transcription with `tiny` int8 and rendering a 60-second 720p clip can take
  several minutes. That's why `render.yaml` caps uploads at 30 MB / 90 s, runs one job at a time, uses the FFmpeg
  renderer, and why **Quick preview** mode (480p draft) is the fastest way to try it.
- **Storage:** the filesystem is wiped on every restart, redeploy or spin-down. Jobs live for 30 minutes at most
  anyway; a job interrupted by a restart is reported as failed and can be retried.
- **Monthly hours:** 750 free instance hours per workspace; a sleeping service doesn't use them.

---

## Option B — UI on Vercel + API on Render

Do Option A first, then:

1. Sign in at <https://vercel.com> with GitHub → **Add New… → Project** → import `splice`.
2. **Root Directory:** `frontend`. Framework preset: **Vite** (detected). Build command and output directory come
   from [`frontend/vercel.json`](../frontend/vercel.json): `npx vite build` → `dist`.
3. **Environment variables:**
   - `VITE_API_BASE_URL` = `https://splice-xxxx.onrender.com` (no trailing slash)
   - `VITE_SOURCE_REPO_URL` = `https://github.com/<you>/splice` (optional)
4. **Deploy.** You get `https://splice-<something>.vercel.app`.
5. Back in Render → your service → **Environment**, set
   `FRONTEND_ORIGINS=https://splice-<something>.vercel.app` (comma-separate several; no trailing slashes) and save —
   Render redeploys. Without this the browser blocks the API calls (CORS).
6. Verify: open the Vercel URL → **Start editing** → upload a short clip → download the result. In the browser's
   developer tools (Network tab) the `/api/...` requests should go to `onrender.com` and return 200/201.

---

## Option C — Hugging Face Docker Space (needs HF PRO)

Hugging Face now requires a paid plan to create Docker (and Gradio-on-CPU) Spaces; free accounts can only create
Static Spaces or ZeroGPU Gradio Spaces. If you have PRO, the same Dockerfile runs unchanged and gets 2 vCPU / 16 GB RAM,
enough for `base` or `openai-whisper`:

1. <https://huggingface.co/new-space> → SDK **Docker** → blank template → hardware **CPU basic**.
2. Add a `README.md` at the top of the Space repository with this header (the rest of the README can follow):

   ```yaml
   ---
   title: SPLICE
   emoji: ✂️
   colorFrom: indigo
   colorTo: blue
   sdk: docker
   app_port: 7860
   ---
   ```

3. Push the project into the Space repository (`git remote add space https://huggingface.co/spaces/<you>/splice`,
   `git push space main`; use an access token with write scope as the password).
4. Optional Space **Variables**: `WHISPER_ALLOWED_MODELS=tiny,base`, `MAX_VIDEO_DURATION_SECONDS=300`,
   `MAX_UPLOAD_MB=100`, `MAX_CONCURRENT_JOBS=2`. To use the PyTorch reference engine, rebuild with the Docker build
   argument `WHISPER_ENGINE=openai-whisper`.

Spaces on free hardware also sleep when unused, and their disk is not persistent — the same caveats as Render apply.

---

## Running the container anywhere else

```bash
docker build -t splice .
docker run --rm -p 7860:7860 splice
# open http://localhost:7860
```

Build arguments: `WHISPER_ENGINE` (`faster-whisper` | `openai-whisper` | `none`), `WHISPER_PRELOAD_MODELS`
(e.g. `"tiny base"`), `VITE_API_BASE_URL`, `VITE_SOURCE_REPO_URL`. Every runtime setting in `backend/.env.example`
can be passed with `-e`.
