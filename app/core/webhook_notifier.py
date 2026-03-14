"""Webhook notification system with retry logic."""

import asyncio
import ipaddress
import logging
import socket
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse
import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)

# Private/reserved IP ranges that should not be targeted by webhooks
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _validate_webhook_url(url: str) -> tuple[bool, str | None]:
    """Validate webhook URL to prevent SSRF attacks."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Invalid URL"

    # Only allow http/https schemes
    if parsed.scheme not in ("http", "https"):
        return False, f"Invalid URL scheme: {parsed.scheme}. Only http/https allowed."

    if not parsed.hostname:
        return False, "URL has no hostname"

    # Resolve hostname and check against blocked networks
    try:
        addrs = socket.getaddrinfo(parsed.hostname, None)
        for _, _, _, _, sockaddr in addrs:
            ip = ipaddress.ip_address(sockaddr[0])
            for network in _BLOCKED_NETWORKS:
                if ip in network:
                    return False, f"Webhook URL resolves to a private/reserved IP address"
    except socket.gaierror:
        return False, f"Cannot resolve hostname: {parsed.hostname}"

    return True, None


class WebhookNotifier:
    """
    Handles webhook delivery with retry logic.

    Sends HTTP POST requests to webhook URLs when events occur.
    Retries failed deliveries with exponential backoff.
    """

    def __init__(
        self,
        default_url: Optional[str] = None,
        max_retries: Optional[int] = None,
        retry_delay: Optional[int] = None,
    ):
        settings = get_settings()
        self._default_url = default_url or settings.default_webhook_url
        self._max_retries = max_retries or settings.webhook_retry_attempts
        self._retry_delay = retry_delay or settings.webhook_retry_delay

    async def notify(
        self,
        event: str,
        payload: dict,
        webhook_url: Optional[str] = None,
    ) -> bool:
        """
        Send a webhook notification.

        Args:
            event: Event type (e.g., "job_completed", "job_failed", "batch_completed")
            payload: Event data to send
            webhook_url: URL to send to (uses default if not specified)

        Returns:
            True if the webhook was delivered successfully
        """
        url = webhook_url or self._default_url
        if not url:
            logger.debug(f"No webhook URL configured for event {event}")
            return False

        # Validate URL to prevent SSRF
        is_valid, validation_error = _validate_webhook_url(url)
        if not is_valid:
            logger.warning(f"Webhook URL validation failed for {event}: {validation_error}")
            return False

        full_payload = {
            "event": event,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            **payload,
        }

        success, error = await self._send_with_retry(url, full_payload)

        if success:
            logger.info(f"Webhook delivered: {event} to {url}")
        else:
            logger.error(f"Webhook failed: {event} to {url}: {error}")

        return success

    async def notify_job_complete(self, job: dict) -> bool:
        """
        Notify when a job completes successfully.

        Args:
            job: The completed job data

        Returns:
            True if webhook was delivered
        """
        payload = {
            "job_id": job.get("job_id"),
            "status": "completed",
            "job_type": job.get("job_type"),
            "content_info": job.get("content_info"),
            "file_path": job.get("converted_file_path") or job.get("raw_file_path"),
            "file_size_mb": job.get("file_size_mb"),
            "error": None,
            "batch_id": job.get("batch_id"),
        }

        webhook_url = job.get("webhook_url")
        return await self.notify("job_completed", payload, webhook_url)

    async def notify_job_failed(self, job: dict, error: Optional[str] = None) -> bool:
        """
        Notify when a job fails.

        Args:
            job: The failed job data
            error: Error message

        Returns:
            True if webhook was delivered
        """
        payload = {
            "job_id": job.get("job_id"),
            "status": "failed",
            "job_type": job.get("job_type"),
            "content_info": job.get("content_info"),
            "file_path": None,
            "file_size_mb": None,
            "error": error or job.get("error"),
            "batch_id": job.get("batch_id"),
        }

        webhook_url = job.get("webhook_url")
        return await self.notify("job_failed", payload, webhook_url)

    async def notify_batch_complete(self, batch: dict) -> bool:
        """
        Notify when a batch completes.

        Args:
            batch: The completed batch data

        Returns:
            True if webhook was delivered
        """
        payload = {
            "batch_id": batch.get("batch_id"),
            "name": batch.get("name"),
            "status": batch.get("status"),
            "total_jobs": batch.get("total_jobs"),
            "completed_jobs": batch.get("completed_jobs"),
            "failed_jobs": batch.get("failed_jobs"),
        }

        webhook_url = batch.get("webhook_url")
        return await self.notify("batch_completed", payload, webhook_url)

    async def send_test(self, webhook_url: str) -> tuple[bool, Optional[str]]:
        """
        Send a test webhook.

        Args:
            webhook_url: URL to test

        Returns:
            Tuple of (success, error_message)
        """
        # Validate URL to prevent SSRF
        is_valid, error = _validate_webhook_url(webhook_url)
        if not is_valid:
            return False, error

        payload = {
            "event": "test",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "message": "This is a test webhook from xdownloader",
        }

        return await self._send_with_retry(webhook_url, payload, max_retries=1)

    async def _send_with_retry(
        self,
        url: str,
        payload: dict,
        max_retries: Optional[int] = None,
    ) -> tuple[bool, Optional[str]]:
        """
        Send webhook with retry logic.

        Args:
            url: Webhook URL
            payload: Data to send
            max_retries: Override max retries

        Returns:
            Tuple of (success, error_message)
        """
        retries = max_retries if max_retries is not None else self._max_retries
        last_error = None

        for attempt in range(retries + 1):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        url,
                        json=payload,
                        headers={
                            "Content-Type": "application/json",
                            "User-Agent": "xdownloader-webhook/1.0",
                        },
                    )

                    if response.status_code >= 200 and response.status_code < 300:
                        return True, None

                    last_error = f"HTTP {response.status_code}: {response.text[:200]}"

            except httpx.TimeoutException:
                last_error = "Request timeout"
            except httpx.ConnectError as e:
                last_error = f"Connection error: {e}"
            except Exception as e:
                last_error = str(e)

            # Log retry attempt
            if attempt < retries:
                delay = self._retry_delay * (2 ** attempt)  # Exponential backoff
                logger.warning(
                    f"Webhook attempt {attempt + 1}/{retries + 1} failed: {last_error}. "
                    f"Retrying in {delay}s..."
                )
                await asyncio.sleep(delay)

        return False, last_error


# Global instance
_webhook_notifier: Optional[WebhookNotifier] = None


def get_webhook_notifier() -> WebhookNotifier:
    """Get or create the global webhook notifier instance."""
    global _webhook_notifier
    if _webhook_notifier is None:
        _webhook_notifier = WebhookNotifier()
    return _webhook_notifier
