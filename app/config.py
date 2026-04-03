"""Configuration management using Pydantic Settings."""

from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Twitter Authentication
    twitter_auth_token: str = ""
    twitter_ct0: str = ""
    twitter_cookie_file: str | None = None

    # Public bearer token used by Twitter web client (not a secret)
    # This is the same token used by twitter.com - can be overridden via TWITTER_BEARER_TOKEN env var
    twitter_bearer_token: str = (
        "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCgYR9Wk5bLLMNhyFz4%3D"
        "sIHxcAabN8Z2cIUpYBUSsYGqNFtEGV1VTJFhD4ij8EV2YikPq3"
    )

    # Telegram Bot
    telegram_bot_token: str | None = None
    telegram_bot_mode: str = "polling"  # "polling" or "webhook"
    telegram_webhook_url: str | None = None  # e.g. "https://yourdomain.com/api/telegram/webhook"
    telegram_webhook_secret: str | None = None

    # Server
    host: str = "127.0.0.1"  # Bind to localhost by default for security
    port: int = 8000
    debug: bool = False

    # API Authentication (optional - if set, requires X-API-Key header)
    api_key: str | None = None

    # Encryption key for secrets at rest (auto-generated if not set)
    encryption_key: str | None = None

    # CORS (comma-separated origins, or "*" for all)
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # Rate limiting (requests per minute)
    rate_limit: str = "60/minute"  # Default: 60 requests per minute
    rate_limit_enabled: bool = True

    # Request timeout (seconds)
    request_timeout: int = 300  # 5 minutes default for long downloads

    # Sentry error tracking (optional)
    sentry_dsn: str | None = None
    sentry_environment: str = "development"
    sentry_traces_sample_rate: float = 0.1  # 10% of transactions

    # Downloads
    download_dir: str = "./output"
    max_concurrent_downloads: int = 5
    cleanup_after_hours: int = 24

    # Storage Management
    max_storage_gb: float | None = None  # Maximum storage limit for download dir
    min_free_space_gb: float | None = None  # Minimum free disk space to maintain
    storage_cleanup_interval: int = 3600  # Cleanup check interval in seconds
    storage_cleanup_enabled: bool = True  # Enable background cleanup

    # Speaker Diarization (pyannote)
    huggingface_token: str | None = None

    # Remote Whisper Service (for Docker/GPU transcription)
    whisper_service_url: str | None = None  # e.g., "http://whisper:8001"

    # YouTube cookies (Netscape format file for yt-dlp authentication)
    youtube_cookies_file: str | None = None  # path to cookies.txt

    # Spotify Transcript (sp_dc cookie for Read Along API)
    spotify_sp_dc: str | None = None

    # LLM Summarization
    llm_provider: str = "ollama"  # ollama, openai, anthropic, groq, deepseek, custom
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str | None = None  # For OpenAI-compatible endpoints
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-3-haiku-20240307"
    groq_api_key: str | None = None
    groq_model: str = "llama-3.1-70b-versatile"
    deepseek_api_key: str | None = None
    deepseek_model: str = "deepseek-chat"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-1.5-flash"

    # Subscription Worker
    subscription_worker_enabled: bool = True
    subscription_check_interval: int = 3600  # Check every hour (in seconds)
    subscription_max_concurrent: int = 2  # Max concurrent downloads per check
    subscription_webhook_url: str | None = None  # Optional webhook for notifications

    # Webhooks
    default_webhook_url: str | None = None  # Default webhook URL for job notifications
    webhook_retry_attempts: int = 3  # Number of retry attempts for failed webhooks
    webhook_retry_delay: int = 60  # Delay between retries in seconds

    # Scheduler
    scheduler_enabled: bool = True  # Enable scheduled downloads
    scheduler_check_interval: int = 60  # Check interval in seconds

    # Queue
    queue_enabled: bool = True  # Enable priority queue processing
    default_priority: int = 5  # Default priority level (1-10)
    max_concurrent_queue_jobs: int = 5  # Max concurrent jobs in queue

    # Cloud Storage - S3/S3-Compatible
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_bucket: str | None = None
    s3_region: str = "us-east-1"
    s3_endpoint_url: str | None = None  # For S3-compatible services (MinIO, etc.)

    # Cloud Storage - Google Drive
    google_drive_client_id: str | None = None
    google_drive_client_secret: str | None = None

    # Cloud Storage - Dropbox
    dropbox_app_key: str | None = None
    dropbox_app_secret: str | None = None

    def get_download_path(self) -> Path:
        """Get download directory as Path, creating if needed."""
        path = Path(self.download_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def has_auth(self) -> bool:
        """Check if authentication credentials are configured."""
        return bool(self.twitter_auth_token and self.twitter_ct0) or bool(
            self.twitter_cookie_file
        )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
