# ══════════════════════════════════════════════════════════════════════════════
# Dockerfile - AI Daily Briefing Agent
# Multi-stage build: smaller final image, faster Cloud Run cold starts
# Target: Google Cloud Run (--run-now mode) or Cloud Run Jobs
# ══════════════════════════════════════════════════════════════════════════════

# ── Stage 1: Build dependencies ────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build tools (needed for some native packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies into a virtual environment
COPY requirements.txt .
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt


# ── Stage 2: Runtime image ─────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Security: run as non-root user
RUN groupadd -r briefing && useradd -r -g briefing -d /app -s /sbin/nologin briefing

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY --chown=briefing:briefing . .

# Create directory for OAuth2 token (mounted as secret in Cloud Run)
RUN mkdir -p /app/config && chown -R briefing:briefing /app/config

# Switch to non-root user
USER briefing

# Environment defaults (overridden by Cloud Run env vars or Secret Manager)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENVIRONMENT=production \
    LOG_LEVEL=INFO

# Health check for Cloud Run (optional, mainly for long-running containers)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "from src.config import get_settings; get_settings()" || exit 1

# Default command: run briefing once (Cloud Run Jobs mode)
# Override with --schedule for long-running deployments
CMD ["python", "main.py", "--run-now"]
