"""Async HTTP client for Twitter/X API."""

import json
from urllib.parse import quote

import httpx
import structlog
from cachetools import TTLCache

from .auth import AuthManager
from .parser import SpaceMetadata, SpaceURLParser
from ..exceptions import (
    AuthenticationError,
    SpaceNotFoundError,
    SpaceNotAvailableError,
    RateLimitError,
    XDownloaderError,
)
from .retry import request_with_retry

logger = structlog.get_logger(__name__)


class TwitterClient:
    """Async Twitter API client for Spaces operations."""

    BASE_URL = "https://x.com"

    # Known GraphQL query IDs for AudioSpaceById
    # These may change when Twitter updates their API
    GRAPHQL_QUERY_IDS = [
        "jyQ0_DEMZHeoluCgHJ-U5Q",
        "Uv5R_-Chxbn1FEkyUkSW2w",
        "xRXCnp1Xqr8FXlC0UlmV4A",
    ]

    # Cache for metadata (1 hour TTL)
    _metadata_cache: TTLCache = TTLCache(maxsize=1000, ttl=3600)

    def __init__(self, auth: AuthManager):
        """
        Initialize the Twitter client.

        Args:
            auth: AuthManager instance with valid credentials
        """
        self.auth = auth
        self._client: httpx.AsyncClient | None = None
        self._working_query_id: str | None = None

    async def __aenter__(self) -> "TwitterClient":
        """Async context manager entry."""
        self._client = httpx.AsyncClient(
            headers=self.auth.get_headers(),
            timeout=30.0,
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Get the HTTP client, ensuring it's initialized."""
        if self._client is None:
            raise RuntimeError(
                "TwitterClient must be used as async context manager"
            )
        return self._client

    async def get_space_metadata(self, space_id: str) -> SpaceMetadata:
        """
        Fetch Space metadata using AudioSpaceById GraphQL endpoint.

        Args:
            space_id: The Space ID (e.g., 1vOxwdyYrlqKB)

        Returns:
            SpaceMetadata object with parsed Space information

        Raises:
            AuthenticationError: If credentials are invalid
            SpaceNotFoundError: If Space doesn't exist
            SpaceNotAvailableError: If replay isn't available
        """
        # Check cache first
        if space_id in self._metadata_cache:
            logger.debug(f"Cache hit for space_id: {space_id}")
            return self._metadata_cache[space_id]

        variables = {
            "id": space_id,
            "isMetatagsQuery": False,
            "withReplays": True,
            "withListeners": True,
        }
        variables_encoded = quote(json.dumps(variables))

        # Try each known query ID
        query_ids = (
            [self._working_query_id] + self.GRAPHQL_QUERY_IDS
            if self._working_query_id
            else self.GRAPHQL_QUERY_IDS
        )

        last_error: Exception | None = None

        for query_id in query_ids:
            url = (
                f"{self.BASE_URL}/i/api/graphql/{query_id}/AudioSpaceById"
                f"?variables={variables_encoded}"
            )

            try:
                response = await request_with_retry(self.client, "GET", url)

                if response.status_code == 401:
                    raise AuthenticationError(
                        "Invalid authentication credentials"
                    )
                elif response.status_code == 403:
                    raise AuthenticationError(
                        "Access forbidden - credentials may be expired"
                    )
                elif response.status_code == 429:
                    raise RateLimitError(
                        "Rate limit exceeded. Please wait before retrying."
                    )
                elif response.status_code == 404:
                    # This query ID might be outdated, try next one
                    logger.debug(f"Query ID {query_id} returned 404, trying next")
                    continue
                elif response.status_code != 200:
                    logger.warning(
                        f"Unexpected status {response.status_code} for query {query_id}"
                    )
                    continue

                data = response.json()

                # Check for errors in response
                if "errors" in data:
                    error_msg = data["errors"][0].get("message", "Unknown error")
                    if "not found" in error_msg.lower():
                        raise SpaceNotFoundError(f"Space not found: {space_id}")
                    logger.warning(f"API error: {error_msg}")
                    continue

                # Parse the response
                metadata = SpaceURLParser.parse_audio_space_response(data)

                # Cache successful result and remember working query ID
                self._metadata_cache[space_id] = metadata
                self._working_query_id = query_id
                logger.debug(f"Successfully fetched metadata using query ID: {query_id}")

                return metadata

            except (AuthenticationError, SpaceNotFoundError, SpaceNotAvailableError):
                raise
            except RateLimitError:
                raise
            except Exception as e:
                last_error = e
                logger.warning(f"Error with query ID {query_id}: {e}")
                continue

        # All query IDs failed
        if last_error:
            raise XDownloaderError(
                f"All GraphQL query IDs failed. Last error: {last_error}"
            )
        raise SpaceNotFoundError(f"Could not fetch metadata for Space: {space_id}")

    async def get_stream_url(self, media_key: str) -> str:
        """
        Get the m3u8 playlist URL for a Space.

        Args:
            media_key: The media_key from Space metadata (e.g., 28_2013482329990144000)

        Returns:
            The m3u8 playlist URL

        Raises:
            AuthenticationError: If credentials are invalid
            SpaceNotAvailableError: If stream is not available
        """
        url = f"{self.BASE_URL}/i/api/1.1/live_video_stream/status/{media_key}"

        response = await request_with_retry(self.client, "GET", url)

        if response.status_code == 401:
            raise AuthenticationError("Invalid authentication credentials")
        elif response.status_code == 403:
            raise AuthenticationError(
                "Access forbidden - credentials may be expired"
            )
        elif response.status_code == 429:
            raise RateLimitError(
                "Rate limit exceeded. Please wait before retrying."
            )
        elif response.status_code == 404:
            raise SpaceNotAvailableError(
                f"Stream not found for media_key: {media_key}"
            )
        elif response.status_code != 200:
            raise XDownloaderError(
                f"Unexpected status code: {response.status_code}"
            )

        data = response.json()
        return SpaceURLParser.parse_stream_response(data)

    async def get_space_from_url(self, url: str) -> tuple[SpaceMetadata, str]:
        """
        Convenience method to get metadata and stream URL from a Space URL.

        Args:
            url: Twitter Space URL

        Returns:
            Tuple of (SpaceMetadata, m3u8_url)
        """
        space_id = SpaceURLParser.extract_space_id(url)
        metadata = await self.get_space_metadata(space_id)
        stream_url = await self.get_stream_url(metadata.media_key)
        return metadata, stream_url
