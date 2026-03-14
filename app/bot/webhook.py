"""Telegram webhook endpoint for FastAPI integration."""

import logging
from typing import Optional

from fastapi import APIRouter, Request, Response

router = APIRouter(prefix="/api/telegram", tags=["telegram"])
logger = logging.getLogger(__name__)

_application = None
_webhook_secret: Optional[str] = None


async def setup_webhook_mode(app_instance, secret: Optional[str] = None):
    """Store the telegram Application instance for webhook processing."""
    global _application, _webhook_secret
    _application = app_instance
    _webhook_secret = secret


async def shutdown_webhook_mode():
    """Gracefully stop the telegram Application."""
    global _application
    if _application:
        await _application.stop()
        await _application.shutdown()
        _application = None


@router.post("/webhook")
async def telegram_webhook(request: Request) -> Response:
    if _application is None:
        return Response(content="Bot not initialized", status_code=503)

    # Always verify secret token — reject if secret is not configured
    if not _webhook_secret:
        return Response(content="Webhook secret not configured", status_code=503)

    import hmac
    header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not hmac.compare_digest(header_secret, _webhook_secret):
        return Response(content="Unauthorized", status_code=403)

    from telegram import Update

    body = await request.json()
    update = Update.de_json(body, _application.bot)
    await _application.process_update(update)

    return Response(content="ok", status_code=200)
