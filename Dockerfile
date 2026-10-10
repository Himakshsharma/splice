# SPLICE — single container: React UI + FastAPI API + FFmpeg + Whisper.
# Works on Render (Docker web service) and Hugging Face Docker Spaces; listens on $PORT.
#
#   docker build -t splice .
#   docker run -p 7860:7860 splice        # then open http://localhost:7860

# ---------- 1. build the frontend ----------
FROM node:20-slim AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY frontend/ ./
# Same-origin API: the UI calls /api on the host that served it.
ARG VITE_API_BASE_URL=""
ARG VITE_SOURCE_REPO_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL VITE_SOURCE_REPO_URL=$VITE_SOURCE_REPO_URL
# Type-checking and tests run in CI; the image only needs the production bundle.
RUN npx vite build

# ---------- 2. runtime ----------
FROM python:3.11-slim AS runtime

# FFmpeg is NOT present on hosting platforms by default — install it explicitly.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Non-root user (uid 1000 is also what Hugging Face Spaces expects).
RUN useradd --create-home --uid 1000 splice
WORKDIR /app

# faster-whisper (default): int8 CPU inference, fits small free instances.
# openai-whisper: the PyTorch reference implementation (needs ~1.5 GB+ RAM).
ARG WHISPER_ENGINE=faster-whisper
ARG WHISPER_PRELOAD_MODELS="tiny"
COPY backend/requirements-base.txt backend/requirements.txt backend/requirements-optional.txt ./
RUN pip install --no-cache-dir -r requirements-base.txt \
    && if [ "$WHISPER_ENGINE" = "openai-whisper" ]; then \
         pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt; \
       elif [ "$WHISPER_ENGINE" = "faster-whisper" ]; then \
         pip install --no-cache-dir -r requirements-optional.txt; \
       fi

# Download model weights at build time so no request ever waits for a download.
ENV WHISPER_CACHE_DIR=/app/models
RUN mkdir -p /app/models && for m in $WHISPER_PRELOAD_MODELS; do \
      if [ "$WHISPER_ENGINE" = "openai-whisper" ]; then \
        python -c "import whisper; whisper.load_model('$m', device='cpu', download_root='/app/models')"; \
      elif [ "$WHISPER_ENGINE" = "faster-whisper" ]; then \
        python -c "from faster_whisper import WhisperModel; WhisperModel('$m', device='cpu', compute_type='int8', download_root='/app/models')"; \
      fi; \
    done && chown -R splice:splice /app/models

COPY backend/app ./app
COPY --from=frontend /fe/dist ./frontend-dist

ENV APP_ENV=production \
    FRONTEND_DIST=/app/frontend-dist \
    TEMP_DIR=/tmp/splice \
    WHISPER_ENGINE=$WHISPER_ENGINE \
    WHISPER_MODEL=tiny \
    WHISPER_ALLOWED_MODELS=tiny \
    TRUST_PROXY_HEADERS=true \
    PYTHONUNBUFFERED=1 \
    PORT=7860

USER splice
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s CMD python -c "import os,urllib.request;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"7860\")}/api/health',timeout=4)" || exit 1

# --no-access-log: download URLs carry the job token as a query parameter; keep it out of logs.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860} --proxy-headers --forwarded-allow-ips='*' --no-access-log"]
