"""FastAPI application entry point."""

import uvicorn
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .config import get_settings
from .api import router as api_router
from .api.ratelimit import limiter
from .api.middleware import TimeoutMiddleware, RequestIDMiddleware
from .logging_config import configure_logging, get_logger

# Configure structured logging
_settings = get_settings()
configure_logging(json_logs=not _settings.debug, log_level="DEBUG" if _settings.debug else "INFO")
logger = get_logger(__name__)

# Initialize Sentry if configured
if _settings.sentry_dsn:
    import sentry_sdk
    sentry_sdk.init(
        dsn=_settings.sentry_dsn,
        environment=_settings.sentry_environment,
        traces_sample_rate=_settings.sentry_traces_sample_rate,
        send_default_pii=False,  # Don't send PII
    )
    logger.info("sentry_initialized", environment=_settings.sentry_environment)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    settings = get_settings()
    logger.info("Starting Sift API")
    logger.info(f"Server: {settings.host}:{settings.port}")
    logger.info(f"API auth: {'enabled (X-API-Key required)' if settings.api_key else 'disabled (open access)'}")
    logger.info(f"Twitter auth: {settings.has_auth}")
    logger.info(f"Download directory: {settings.download_dir}")

    # Recover unfinished jobs from previous run
    try:
        from .core.workflow import recover_unfinished_jobs
        from .core.job_store import get_job_store

        job_store = get_job_store()
        unfinished = job_store.get_unfinished_jobs()
        if unfinished:
            logger.info(f"Found {len(unfinished)} unfinished jobs - will recover in background")
            # Don't await - let it run in background so server starts quickly
            import asyncio
            asyncio.create_task(recover_unfinished_jobs())
    except Exception as e:
        logger.error(f"Failed to start job recovery: {e}")

    # Start subscription worker
    try:
        from .core.subscription_worker import start_subscription_worker
        await start_subscription_worker()
    except Exception as e:
        logger.error(f"Failed to start subscription worker: {e}")

    # Start queue manager
    try:
        from .core.queue_manager import start_queue_manager
        await start_queue_manager()
        logger.info("Queue manager started")
    except Exception as e:
        logger.error(f"Failed to start queue manager: {e}")

    # Start scheduler worker
    try:
        from .core.scheduler import start_scheduler_worker
        await start_scheduler_worker()
        logger.info("Scheduler worker started")
    except Exception as e:
        logger.error(f"Failed to start scheduler worker: {e}")

    # Start storage manager
    try:
        from .core.storage_manager import get_storage_manager
        storage_manager = get_storage_manager()
        if settings.storage_cleanup_enabled:
            await storage_manager.start_background_cleanup()
            logger.info("Storage manager started")
    except Exception as e:
        logger.error(f"Failed to start storage manager: {e}")

    # Start Telegram bot in webhook mode
    telegram_app = None
    if settings.telegram_bot_token and settings.telegram_bot_mode == "webhook":
        try:
            from .bot import SiftBot
            from .bot.webhook import setup_webhook_mode

            webhook_url = settings.telegram_webhook_url
            if not webhook_url:
                logger.error("TELEGRAM_WEBHOOK_URL is required for webhook mode")
            else:
                bot = SiftBot(settings.telegram_bot_token)
                telegram_app = await bot.setup_webhook(
                    webhook_url=webhook_url,
                    secret=settings.telegram_webhook_secret,
                )
                await setup_webhook_mode(telegram_app, secret=settings.telegram_webhook_secret)
                logger.info("Telegram bot started (webhook mode)")
        except Exception as e:
            logger.error(f"Failed to start Telegram bot: {e}")

    yield

    # Stop storage manager
    try:
        from .core.storage_manager import get_storage_manager
        storage_manager = get_storage_manager()
        await storage_manager.stop_background_cleanup()
    except Exception as e:
        logger.error(f"Failed to stop storage manager: {e}")

    # Stop scheduler worker
    try:
        from .core.scheduler import stop_scheduler_worker
        await stop_scheduler_worker()
    except Exception as e:
        logger.error(f"Failed to stop scheduler worker: {e}")

    # Stop queue manager
    try:
        from .core.queue_manager import stop_queue_manager
        await stop_queue_manager()
    except Exception as e:
        logger.error(f"Failed to stop queue manager: {e}")

    # Stop Telegram bot webhook
    if telegram_app:
        try:
            from .bot.webhook import shutdown_webhook_mode
            await shutdown_webhook_mode()
        except Exception as e:
            logger.error(f"Failed to stop Telegram bot: {e}")

    # Stop subscription worker
    try:
        from .core.subscription_worker import stop_subscription_worker
        await stop_subscription_worker()
    except Exception as e:
        logger.error(f"Failed to stop subscription worker: {e}")

    # Cleanup on shutdown
    logger.info("Shutting down Sift API")
    try:
        from .core.job_store import get_job_store
        from .core.checkpoint import CheckpointManager

        job_store = get_job_store()
        checkpoint_manager = CheckpointManager()

        # Clean up old data
        jobs_deleted = job_store.cleanup_old_jobs(days=7)
        checkpoints_deleted = checkpoint_manager.cleanup_old_checkpoints(max_age_hours=24)

        if jobs_deleted or checkpoints_deleted:
            logger.info(f"Cleanup: {jobs_deleted} old jobs, {checkpoints_deleted} old checkpoints")
    except Exception as e:
        logger.error(f"Cleanup error: {e}")


app = FastAPI(
    title="Sift API",
    description="API for downloading audio from X Spaces, Apple Podcasts, and Spotify",
    version="0.2.0",
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS middleware
_settings = get_settings()
_cors_origins = (
    ["*"] if _settings.cors_origins == "*"
    else [o.strip() for o in _settings.cors_origins.split(",") if o.strip()]
)
_allow_credentials = _cors_origins != ["*"]  # Wildcard origins cannot use credentials
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["X-API-Key", "Content-Type", "Authorization"],
)

# Security headers middleware
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

app.add_middleware(SecurityHeadersMiddleware)

# Timeout middleware
app.add_middleware(TimeoutMiddleware)

# Request ID middleware (for tracing)
app.add_middleware(RequestIDMiddleware)

# Include API routes
app.include_router(api_router, prefix="/api", tags=["download"])

# Include Telegram webhook route
from .bot.webhook import router as telegram_router
app.include_router(telegram_router)


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Sift API",
        "version": "0.2.0",
        "docs": "/docs",
        "health": "/api/health",
        "audio": ["x_spaces", "apple_podcasts", "spotify", "youtube", "xiaoyuzhou"],
        "video": ["x_video", "youtube_video"],
    }


def main():
    """Run the application with uvicorn."""
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    main()
