FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 REKAMIND_DATA_DIR=/data

WORKDIR /app
COPY pyproject.toml ./
COPY rekamind_server ./rekamind_server
RUN pip install ".[postgres,s3]" \
 && useradd --system --uid 10001 rekamind \
 && mkdir /data && chown rekamind /data

USER rekamind
VOLUME /data
EXPOSE 8787
# Inside a container the app must listen on all interfaces; what is exposed to
# the network is decided by the compose file's `ports:` mapping, not here.
ENV REKAMIND_HOST=0.0.0.0
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8787/api/health', timeout=2)"
CMD ["python", "-m", "rekamind_server"]
