# Sift API Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv for faster package management
RUN pip install uv

# Copy dependency files first for better caching
COPY pyproject.toml ./
COPY uv.lock* ./

# Install dependencies using uv
RUN uv pip install --system -e .

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
