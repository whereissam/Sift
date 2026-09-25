# Sift API Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    git \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# YouTube needs a JavaScript runtime so yt-dlp can solve the `n` challenge.
# Without one it warns "extraction without a JS runtime has been deprecated"
# and silently drops formats.
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh -s -- --yes \
    && deno --version

# Install uv for faster package management
RUN pip install uv

# Copy dependency files first for better caching. The ingestion core is a
# workspace package (packages/sift-core) the app depends on, so it has to be
# present before the app is installed.
COPY pyproject.toml ./
COPY uv.lock* ./
COPY packages/ ./packages/

# Install dependencies using uv
RUN uv pip install --system -e ./packages/sift-core -e .

# Copy application code
COPY app/ ./app/

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
