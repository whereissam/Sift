# Deployment Guide

## Desktop App (Recommended for end users)

The desktop app is a self-contained native binary — no Python, no server setup.

### Prerequisites

- [Rust](https://rustup.rs/) (for building)
- [Bun](https://bun.sh/) (for frontend build)
- yt-dlp and ffmpeg in PATH (`brew install yt-dlp ffmpeg`)

### Build

```bash
make desktop
```

This produces:
- **macOS**: `frontend/src-tauri/target/release/bundle/dmg/Sift_0.2.0_aarch64.dmg`
- **Windows**: `frontend/src-tauri/target/release/bundle/msi/Sift_0.2.0_x64_en-US.msi`
- **Linux**: `frontend/src-tauri/target/release/bundle/deb/audio-grab_0.2.0_amd64.deb`

### Development

```bash
make dev    # Tauri dev mode with hot-reload for both frontend and Rust backend
```

---

## Web Mode (Self-hosted server)

### Prerequisites

- Python 3.10+
- FFmpeg installed and in PATH
- (Optional) Twitter/X authentication cookies
- (Optional) Telegram bot token from @BotFather

## Local Development

### 1. Clone and Setup

```bash
cd xdownloader

# Install dependencies with uv
uv sync

# Or with dev dependencies
uv sync --dev
```

### 2. Configure Environment

Create `.env` file:

```env
# Required: Twitter Authentication
TWITTER_AUTH_TOKEN=your_auth_token_here
TWITTER_CT0=your_ct0_here

# Or use cookie file instead
# TWITTER_COOKIE_FILE=/path/to/cookies.txt

# Telegram Bot
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_BOT_MODE=polling          # "polling" or "webhook"
# TELEGRAM_WEBHOOK_URL=https://yourdomain.com/api/telegram/webhook
# TELEGRAM_WEBHOOK_SECRET=optional-secret

# YouTube cookies (for bypassing bot detection / age restrictions)
# YOUTUBE_COOKIES_FILE=./cookies.txt

# Server Configuration
HOST=0.0.0.0
PORT=8000
DOWNLOAD_DIR=/tmp/sift
MAX_CONCURRENT_DOWNLOADS=5
```

### 3. Run the Backend

```bash
# Development with auto-reload
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Or use the script
uv run sift-api
```

### 4. Run Telegram Bot

**Polling mode** (local dev — bot runs as a separate process):

```bash
uv run sift-bot
```

**Webhook mode** (production — bot runs inside the FastAPI server):

Set `TELEGRAM_BOT_MODE=webhook` and `TELEGRAM_WEBHOOK_URL` in `.env`, then just start the API server. The bot will register the webhook and process updates via `/api/telegram/webhook`.

```bash
uv run sift-api  # Bot starts automatically in webhook mode
```

## Docker Deployment

### Dockerfile

```dockerfile
FROM python:3.11-slim

# Install FFmpeg and curl (for uv)
RUN apt-get update && apt-get install -y ffmpeg curl && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### docker-compose.yml

```yaml
version: '3.8'

services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - TWITTER_AUTH_TOKEN=${TWITTER_AUTH_TOKEN}
      - TWITTER_CT0=${TWITTER_CT0}
      - DOWNLOAD_DIR=/app/downloads
    volumes:
      - ./downloads:/app/downloads
    restart: unless-stopped

  # Option A: Run bot as separate container (polling mode)
  bot:
    build: .
    command: uv run sift-bot
    environment:
      - TWITTER_AUTH_TOKEN=${TWITTER_AUTH_TOKEN}
      - TWITTER_CT0=${TWITTER_CT0}
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - DOWNLOAD_DIR=/app/downloads
    volumes:
      - ./downloads:/app/downloads
    restart: unless-stopped

  # Option B: Run bot inside API container (webhook mode)
  # Remove the bot service above and add these env vars to the api service:
  #   - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
  #   - TELEGRAM_BOT_MODE=webhook
  #   - TELEGRAM_WEBHOOK_URL=https://yourdomain.com/api/telegram/webhook
  #   - TELEGRAM_WEBHOOK_SECRET=${TELEGRAM_WEBHOOK_SECRET}
```

### Build and Run

```bash
# Build image
docker build -t xdownloader .

# Run with docker-compose
docker-compose up -d

# View logs
docker-compose logs -f
```

## Production Deployment

### Using Gunicorn

```bash
uv add gunicorn

uv run gunicorn app.main:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000
```

### Systemd Service

Create `/etc/systemd/system/xdownloader.service`:

```ini
[Unit]
Description=Sift API
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/xdownloader
Environment=PATH=/opt/xdownloader/venv/bin
EnvironmentFile=/opt/xdownloader/.env
ExecStart=/opt/xdownloader/venv/bin/gunicorn app.main:app \
    --workers 4 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 127.0.0.1:8000
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable xdownloader
sudo systemctl start xdownloader
```

### Nginx Reverse Proxy

```nginx
server {
    listen 80;
    server_name xdownloader.example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Increase timeout for large downloads
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }

    # Serve downloaded files directly
    location /downloads {
        alias /opt/xdownloader/downloads;
        internal;
    }
}
```

## Cloud Deployment

### Railway

1. Create `railway.toml`:

```toml
[build]
builder = "DOCKERFILE"
dockerfilePath = "Dockerfile"

[deploy]
startCommand = "uvicorn app.main:app --host 0.0.0.0 --port $PORT"
healthcheckPath = "/health"
```

2. Deploy:

```bash
railway login
railway init
railway up
```

### Render

Create `render.yaml`:

```yaml
services:
  - type: web
    name: xdownloader
    env: docker
    envVars:
      - key: TWITTER_AUTH_TOKEN
        sync: false
      - key: TWITTER_CT0
        sync: false
    healthCheckPath: /health
```

### Fly.io

1. Create `fly.toml`:

```toml
app = "xdownloader"
primary_region = "iad"

[build]
  dockerfile = "Dockerfile"

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = true
  auto_start_machines = true
  min_machines_running = 0

[env]
  DOWNLOAD_DIR = "/app/downloads"

[[mounts]]
  source = "downloads"
  destination = "/app/downloads"
```

2. Deploy:

```bash
fly launch
fly secrets set TWITTER_AUTH_TOKEN=xxx TWITTER_CT0=xxx
fly deploy
```

## Monitoring

### Health Check Endpoint

The API provides a health check at `/health`:

```json
{
  "status": "healthy",
  "ffmpeg": true,
  "auth_valid": true,
  "version": "1.0.0"
}
```

### Prometheus Metrics

Add to `requirements.txt`:
```
prometheus-fastapi-instrumentator
```

In `app/main.py`:
```python
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI()
Instrumentator().instrument(app).expose(app)
```

### Logging

Configure structured logging:

```python
import logging
import json

class JSONFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
        })

logging.basicConfig(
    level=logging.INFO,
    handlers=[logging.StreamHandler()],
)
logging.getLogger().handlers[0].setFormatter(JSONFormatter())
```

## Security Considerations

1. **Never expose credentials** - Use environment variables or secrets management
2. **Rate limiting** - Implement rate limiting to prevent abuse
3. **Input validation** - Validate all URLs and parameters
4. **Disk space** - Monitor and clean up downloaded files
5. **HTTPS** - Always use HTTPS in production
6. **Authentication** - Consider adding API keys for public deployments

### Rate Limiting Example

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.post("/api/download")
@limiter.limit("10/minute")
async def download(request: Request):
    pass
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| FFmpeg not found | Ensure FFmpeg is installed and in PATH |
| Auth errors | Re-export cookies from browser |
| Slow downloads | Increase concurrency, check network |
| Disk full | Clean up old downloads |
| Memory issues | Reduce concurrent downloads |
