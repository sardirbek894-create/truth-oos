# =============================================================================
# Olympus Engine v9 — Backend Dockerfile (multi-stage, bare-metal Linux)
# =============================================================================
# Stage 1: build wheels for faster, reproducible installs.
# Stage 2: minimal runtime with onnxruntime CPU + libsodium.
# =============================================================================

# ---- Build stage ----
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        libffi-dev \
        libsodium-dev \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-test.txt ./
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt

# ---- Runtime stage ----
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    OLYMPUS_ENV=production \
    OLYMPUS_BIND=0.0.0.0:8000

RUN apt-get update && apt-get install -y --no-install-recommends \
        libffi8 \
        libsodium23 \
        libpq5 \
        tini \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r olympus && useradd -r -g olympus -d /app -s /sbin/nologin olympus

COPY --from=builder /install /usr/local
WORKDIR /app

# Copy application code.
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini

USER olympus

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/v1/ready || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "4", \
     "--loop", "uvloop", \
     "--http", "httptools", \
     "--access-log", \
     "--proxy-headers"]
