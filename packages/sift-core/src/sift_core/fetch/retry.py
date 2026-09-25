"""Retry utilities with exponential backoff."""

import httpx
import structlog
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

logger = structlog.get_logger(__name__)


# Retryable HTTP exceptions (network errors, timeouts, 5xx)
RETRYABLE_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
)


def is_retryable_status(response: httpx.Response) -> bool:
    """Check if HTTP status code is retryable (5xx or 429 rate limit)."""
    return response.status_code >= 500 or response.status_code == 429


class RetryableHTTPError(Exception):
    """Exception for retryable HTTP errors."""

    def __init__(self, response: httpx.Response):
        self.response = response
        super().__init__(f"HTTP {response.status_code}")


def retry_on_network_error(
    max_attempts: int = 3,
    min_wait: float = 1,
    max_wait: float = 10,
):
    """
    Decorator for retrying on network errors with exponential backoff.

    Args:
        max_attempts: Maximum number of retry attempts
        min_wait: Minimum wait time between retries (seconds)
        max_wait: Maximum wait time between retries (seconds)

    Example:
        @retry_on_network_error(max_attempts=3)
        async def fetch_data():
            ...
    """
    return retry(
        retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS + (RetryableHTTPError,)),
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
        before_sleep=before_sleep_log(logger, log_level=20),  # INFO level
        reraise=True,
    )


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    max_attempts: int = 3,
    **kwargs,
) -> httpx.Response:
    """
    Make an HTTP request with automatic retry on transient failures.

    Args:
        client: httpx.AsyncClient instance
        method: HTTP method (GET, POST, etc.)
        url: Request URL
        max_attempts: Maximum retry attempts
        **kwargs: Additional arguments to pass to client.request()

    Returns:
        httpx.Response

    Raises:
        Original exception after all retries exhausted
    """

    @retry_on_network_error(max_attempts=max_attempts)
    async def _request():
        response = await client.request(method, url, **kwargs)
        if is_retryable_status(response):
            raise RetryableHTTPError(response)
        return response

    return await _request()
