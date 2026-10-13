# Sift API Dockerfile

# Supply-chain pinning: third-party binaries come from images pinned by
# content digest (tag kept for readability), never from `curl | sh`.
# To bump, resolve the new tag's index digest with
#   docker buildx imagetools inspect <image>:<tag>
FROM denoland/deno:bin-2.9.7@sha256:bc5aa4466e21b6d3021226a85ba2e1911f7c386254d97b9d797903ab74edace2 AS deno
FROM ghcr.io/astral-sh/uv:0.12.9@sha256:8b940d3a9d65bed080436972241af2e21c84b5e8c9193f7014ed71479ee795ff AS uv

FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# YouTube needs a JavaScript runtime so yt-dlp can solve the `n` challenge.
# Without one it warns "extraction without a JS runtime has been deprecated"
# and silently drops formats. yt-dlp only needs `deno` on PATH.
COPY --from=deno /deno /usr/local/bin/deno
RUN deno --version

COPY --from=uv /uv /usr/local/bin/uv

# Install from uv.lock into a project venv using the image's Python.
# --frozen installs exactly what the lockfile pins and fails instead of
# re-resolving, so the image never picks up unreviewed versions.
ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Copy dependency files first for better caching. The ingestion core is a
# workspace package (packages/sift-core) the app depends on, so it has to be
# present before the app is installed.
COPY pyproject.toml uv.lock README.md ./
COPY packages/ ./packages/

# Third-party dependencies only (cached until the lockfile changes).
RUN uv sync --frozen --no-dev --no-install-workspace

# Copy application code
COPY app/ ./app/

# Install the workspace packages themselves (sift-core and the app).
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# Create output directory
RUN mkdir -p /app/output /app/data

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Run as non-root user
RUN addgroup --system sift && adduser --system --ingroup sift sift
RUN chown -R sift:sift /app
USER sift

# Run the application
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
