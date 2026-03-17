# ── AetheerAI Dockerfile ─────────────────────────────────────────────────────
# Multi-stage build: builder installs deps, runtime image is slim.
# Usage:
#   docker build -t aetheerai .
#   docker run -p 8000:8000 --env-file .env aetheerai

# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# System deps for native Python packages (cryptography, pillow, reportlab, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ libffi-dev libssl-dev libjpeg-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY AetheerAI/requirements.txt ./requirements.txt

RUN pip install --upgrade pip && \
    pip install --prefix=/install --no-cache-dir \
        sqlalchemy>=2.0.0 \
        python-jose[cryptography]>=3.3.0 \
        passlib[bcrypt]>=1.7.4 \
        python-multipart>=0.0.9 \
        -r requirements.txt

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Security: run as a non-root user
RUN useradd -m -u 1000 aetheer

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY AetheerAI/ ./

# Create writable directories needed at runtime
RUN mkdir -p memory data/uploads logs && chown -R aetheer:aetheer /app

USER aetheer

# Expose the FastAPI port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"

# Default command — override with env vars via --env-file or -e flags
CMD ["python", "start_api.py", "--host", "0.0.0.0", "--port", "8000"]
