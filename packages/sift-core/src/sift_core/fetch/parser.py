"""URL parsing and data extraction for Twitter Spaces."""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..exceptions import SpaceNotFoundError, SpaceNotAvailableError


@dataclass
class SpaceMetadata:
    """Parsed metadata from AudioSpaceById response."""

    space_id: str
    media_key: str
    title: str
    state: str  # "Running", "Ended", "Scheduled"
    is_replay_available: bool
    host_username: str | None = None
    host_display_name: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    total_live_listeners: int = 0
    total_replay_watched: int = 0
    participant_count: int = 0

    @property
    def is_downloadable(self) -> bool:
        """Check if the Space can be downloaded."""
        return self.state == "Ended" and self.is_replay_available

    @property
    def duration_seconds(self) -> int | None:
        """Calculate duration in seconds if start/end times are available."""
        if self.started_at and self.ended_at:
            return int((self.ended_at - self.started_at).total_seconds())
        return None


class SpaceURLParser:
    """Parser for Twitter Space URLs and API responses."""

    # Regex patterns for Space URLs
    URL_PATTERNS = [
        r"(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/i/spaces/([a-zA-Z0-9]+)",
        r"(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/spaces/([a-zA-Z0-9]+)",
    ]

    @classmethod
    def extract_space_id(cls, url: str) -> str:
        """
        Extract the Space ID from a Twitter Space URL.

        Args:
            url: Twitter Space URL (e.g., https://x.com/i/spaces/1vOxwdyYrlqKB)

        Returns:
            The Space ID (e.g., 1vOxwdyYrlqKB)

        Raises:
            SpaceNotFoundError: If URL doesn't match expected pattern
        """
        for pattern in cls.URL_PATTERNS:
            match = re.search(pattern, url)
            if match:
                return match.group(1)

        raise SpaceNotFoundError(f"Could not extract Space ID from URL: {url}")

    @classmethod
    def is_valid_space_url(cls, url: str) -> bool:
        """Check if a URL is a valid Twitter Space URL."""
        try:
            cls.extract_space_id(url)
            return True
        except SpaceNotFoundError:
            return False

    @classmethod
    def parse_audio_space_response(cls, data: dict[str, Any]) -> SpaceMetadata:
        """
        Parse the AudioSpaceById GraphQL response.

        Args:
            data: Raw JSON response from AudioSpaceById endpoint

        Returns:
            SpaceMetadata object with parsed data

        Raises:
            SpaceNotFoundError: If Space data not found in response
            SpaceNotAvailableError: If Space exists but replay not available
        """
        try:
            audio_space = data["data"]["audioSpace"]
            metadata = audio_space["metadata"]
        except (KeyError, TypeError) as e:
            raise SpaceNotFoundError(f"Invalid API response structure: {e}")

        # Extract basic info
        space_id = metadata.get("rest_id", "")
        media_key = metadata.get("media_key", "")
        title = metadata.get("title", "Untitled Space")
        state = metadata.get("state", "Unknown")
        is_replay_available = metadata.get("is_space_available_for_replay", False)

        if not media_key:
            raise SpaceNotFoundError("No media_key found in Space metadata")

        # Extract host info
        host_username = None
        host_display_name = None
        try:
            creator = metadata["creator_results"]["result"]
            legacy = creator.get("legacy", {})
            host_username = legacy.get("screen_name")
            host_display_name = legacy.get("name")
        except (KeyError, TypeError):
            pass

        # Parse timestamps (milliseconds to datetime)
        def parse_timestamp(ts: int | None) -> datetime | None:
            if ts:
                return datetime.fromtimestamp(ts / 1000)
            return None

        created_at = parse_timestamp(metadata.get("created_at"))
        started_at = parse_timestamp(metadata.get("started_at"))
        ended_at = parse_timestamp(metadata.get("ended_at"))

        # Extract counts
        total_live_listeners = metadata.get("total_live_listeners", 0) or 0
        total_replay_watched = metadata.get("total_replay_watched", 0) or 0

        # Get participant count
        participant_count = 0
        try:
            participant_count = audio_space["participants"]["total"]
        except (KeyError, TypeError):
            pass

        result = SpaceMetadata(
            space_id=space_id,
            media_key=media_key,
            title=title,
            state=state,
            is_replay_available=is_replay_available,
            host_username=host_username,
            host_display_name=host_display_name,
            created_at=created_at,
            started_at=started_at,
            ended_at=ended_at,
            total_live_listeners=total_live_listeners,
            total_replay_watched=total_replay_watched,
            participant_count=participant_count,
        )

        if not result.is_downloadable:
            if state != "Ended":
                raise SpaceNotAvailableError(
                    f"Space is not yet ended (state: {state})"
                )
            raise SpaceNotAvailableError(
                "Space replay is not available for download"
            )

        return result

    @classmethod
    def parse_stream_response(cls, data: dict[str, Any]) -> str:
        """
        Parse the live_video_stream/status response.

        Args:
            data: Raw JSON response from stream status endpoint

        Returns:
            The m3u8 playlist URL

        Raises:
            SpaceNotAvailableError: If stream URL not found
        """
        try:
            return data["source"]["location"]
        except (KeyError, TypeError):
            raise SpaceNotAvailableError(
                "Could not find stream URL in response"
            )
