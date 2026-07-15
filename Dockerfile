FROM node:24-bookworm-slim AS node-runtime

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY setup.py README.md ./
COPY spotifydl ./spotifydl
COPY assets ./assets

RUN python -m pip install --upgrade pip \
    && python -m pip install .

RUN groupadd --gid 10001 spotifydl \
    && useradd --create-home --uid 10001 --gid 10001 spotifydl \
    && mkdir -p /app/web_downloads /app/web_cache \
    && chown -R spotifydl:spotifydl /app

USER spotifydl

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"]

CMD ["python", "-m", "uvicorn", "spotifydl.web:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
