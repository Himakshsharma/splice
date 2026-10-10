# Local setup

SPLICE runs entirely on your laptop with no paid services or API keys. You need two terminals: one for the Python
API, one for the React UI.

## 1. Install the tools

### Windows (PowerShell)

```powershell
winget install --id Git.Git -e
winget install --id Python.Python.3.11 -e
winget install --id OpenJS.NodeJS.LTS -e
winget install --id Gyan.FFmpeg -e
```

Close and reopen PowerShell so the new PATH entries load, then check:

```powershell
git --version
py -3.11 --version
node --version          # v20 or newer
ffmpeg -version
ffprobe -version
```

If `ffmpeg` is "not recognized", open *Settings → System → About → Advanced system settings → Environment
Variables*, and make sure the folder containing `ffmpeg.exe` (winget prints it, typically under
`%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_*\ffmpeg-*\bin`) is in your user `Path`.

### macOS

```bash
brew install git python@3.11 node@20 ffmpeg
```

### Linux (Debian/Ubuntu)

```bash
sudo apt update
sudo apt install -y git python3.11 python3.11-venv nodejs npm ffmpeg
```

(Use [NodeSource](https://github.com/nodesource/distributions) if your distribution's Node.js is older than 20.)

## 2. Get the code

```bash
git clone https://github.com/<you>/splice.git
cd splice
```

## 3. Backend (terminal 1)

### Windows

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --port 8000
```

If activation fails with *"running scripts is disabled on this system"*, allow scripts **for this terminal session
only** (nothing is changed permanently) and activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Alternatively use Command Prompt: `.venv\Scripts\activate.bat`.

### macOS / Linux

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

The `--extra-index-url` line installs the CPU-only build of PyTorch (≈200 MB instead of several GB). Leave it out if
you have an NVIDIA GPU and want CUDA, then set `WHISPER_DEVICE=auto` in `.env`.

Check it: open <http://localhost:8000/api/health> — you should see `"ffmpeg": true, "whisper_available": true`.

**Lighter alternative:** `pip install -r requirements-optional.txt` and set `WHISPER_ENGINE=faster-whisper` in `.env`
(same Whisper weights, no PyTorch).

## 4. Frontend (terminal 2)

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. The dev server forwards `/api` to the backend on port 8000, so no extra configuration
is needed (leave `VITE_API_BASE_URL` empty).

## 5. Try it

1. Go to **Start editing**.
2. Drop in a short MP4/MOV/WebM with some pauses (a 30–60 s phone recording is ideal).
3. Press **Remove silence**. The first run downloads the Whisper `tiny` weights (~75 MB) into `~/.cache/whisper`.
4. When it finishes, compare the two players, inspect the timeline and 3D view, and press **Download MP4**.

Or test the whole pipeline from a terminal (generates its own test video):

```bash
python scripts/smoke_test.py --base-url http://localhost:8000
```

## 6. Run the tests

```bash
cd backend
pip install -r requirements-dev.txt
ruff check .
pytest

cd ../frontend
npm run typecheck
npm test
```

## Single-process mode (optional)

Build the UI once and let FastAPI serve it — this is exactly what the Docker image does:

```bash
cd frontend && npm run build && cd ../backend
# Windows: $env:FRONTEND_DIST="../frontend/dist"; uvicorn app.main:app --port 8000
FRONTEND_DIST=../frontend/dist uvicorn app.main:app --port 8000
```

Then everything is at <http://localhost:8000>.
