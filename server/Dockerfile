# Build context is the repository root (see docker-compose.yml): the image bundles the web UI.

# ---- web UI -----------------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---- backend ----------------------------------------------------------------
# EXTRAS picks the variant: "postgres,s3" = API only (record/upload/view, no processing),
# "postgres,s3,asr" = also transcribes on the CPU (faster-whisper), "postgres,s3,asr,cuda" = NVIDIA GPU
# (needs the NVIDIA Container Toolkit on the host). Published as `<version>`, `<version>-cpu`, `<version>-cuda`.
FROM python:3.12-slim
ARG EXTRAS=postgres,s3
LABEL org.opencontainers.image.source="https://github.com/handokoaji/rekamind" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.description="Rekamind backend: meetings, transcripts, summaries, tasks"

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 REKAMIND_DATA_DIR=/data REKAMIND_WEB_DIR=/app/web HF_HOME=/data/huggingface \
    LD_LIBRARY_PATH=/usr/local/lib/python3.12/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.12/site-packages/nvidia/cudnn/lib

WORKDIR /app
COPY server/pyproject.toml ./
COPY server/rekamind_server ./rekamind_server
RUN pip install ".[${EXTRAS}]" \
 && useradd --system --uid 10001 rekamind \
 && mkdir /data && chown rekamind /data
COPY --from=web /web/dist ./web

USER rekamind
VOLUME /data
EXPOSE 8787
# Inside a container the app must listen on all interfaces; what is exposed to
# the network is decided by the compose file's `ports:` mapping, not here.
ENV REKAMIND_HOST=0.0.0.0
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8787/api/health', timeout=2)"
CMD ["python", "-m", "rekamind_server"]
