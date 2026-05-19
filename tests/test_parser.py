"""Tests for URL parsing functionality."""

import pytest
from app.core.parser import SpaceURLParser
from app.core.exceptions import SpaceNotFoundError, SpaceNotAvailableError


class TestSpaceURLParser:
    """Tests for SpaceURLParser."""

    def test_extract_space_id_x_com(self):
        """Test extracting Space ID from x.com URL."""
        url = "https://x.com/i/spaces/1vOxwdyYrlqKB"
        space_id = SpaceURLParser.extract_space_id(url)
        assert space_id == "1vOxwdyYrlqKB"

    def test_extract_space_id_twitter_com(self):
        """Test extracting Space ID from twitter.com URL."""
        url = "https://twitter.com/i/spaces/1vOxwdyYrlqKB"
        space_id = SpaceURLParser.extract_space_id(url)
        assert space_id == "1vOxwdyYrlqKB"

    def test_extract_space_id_without_i(self):
        """Test extracting Space ID from URL without /i/."""
        url = "https://x.com/spaces/1vOxwdyYrlqKB"
        space_id = SpaceURLParser.extract_space_id(url)
        assert space_id == "1vOxwdyYrlqKB"

    def test_extract_space_id_with_params(self):
        """Test extracting Space ID from URL with query parameters."""
        url = "https://x.com/i/spaces/1vOxwdyYrlqKB?s=20"
        space_id = SpaceURLParser.extract_space_id(url)
        assert space_id == "1vOxwdyYrlqKB"

    def test_extract_space_id_invalid_url(self):
        """Test that invalid URLs raise SpaceNotFoundError."""
        with pytest.raises(SpaceNotFoundError):
            SpaceURLParser.extract_space_id("https://x.com/user/status/123")

    def test_is_valid_space_url(self):
        """Test URL validation."""
        assert SpaceURLParser.is_valid_space_url("https://x.com/i/spaces/1vOxwdyYrlqKB")
        assert SpaceURLParser.is_valid_space_url("https://twitter.com/i/spaces/abc123")
        assert not SpaceURLParser.is_valid_space_url("https://x.com/user/status/123")
        assert not SpaceURLParser.is_valid_space_url("not a url")

    def test_parse_audio_space_response_success(self):
        """Test parsing a valid AudioSpaceById response."""
        data = {
            "data": {
                "audioSpace": {
                    "metadata": {
                        "rest_id": "1vOxwdyYrlqKB",
                        "media_key": "28_2013482329990144000",
                        "title": "Test Space",
                        "state": "Ended",
                        "is_space_available_for_replay": True,
                        "created_at": 1737549600000,
                        "started_at": 1737549600000,
                        "ended_at": 1737556800000,
                        "total_live_listeners": 100,
                        "total_replay_watched": 50,
                        "creator_results": {
                            "result": {
                                "legacy": {
                                    "screen_name": "testuser",
                                    "name": "Test User",
                                }
                            }
                        }
                    },
                    "participants": {
                        "total": 10
                    }
                }
            }
        }

        metadata = SpaceURLParser.parse_audio_space_response(data)

        assert metadata.space_id == "1vOxwdyYrlqKB"
        assert metadata.media_key == "28_2013482329990144000"
        assert metadata.title == "Test Space"
        assert metadata.state == "Ended"
        assert metadata.is_replay_available
        assert metadata.host_username == "testuser"
        assert metadata.is_downloadable

    def test_parse_audio_space_response_not_ended(self):
        """Test that running Spaces raise SpaceNotAvailableError."""
        data = {
            "data": {
                "audioSpace": {
                    "metadata": {
                        "rest_id": "1vOxwdyYrlqKB",
                        "media_key": "28_2013482329990144000",
                        "title": "Live Space",
                        "state": "Running",
                        "is_space_available_for_replay": False,
                    },
                    "participants": {"total": 10}
                }
            }
        }

        with pytest.raises(SpaceNotAvailableError):
            SpaceURLParser.parse_audio_space_response(data)

    def test_parse_audio_space_response_no_replay(self):
        """Test that Spaces without replay raise SpaceNotAvailableError."""
        data = {
            "data": {
                "audioSpace": {
                    "metadata": {
                        "rest_id": "1vOxwdyYrlqKB",
                        "media_key": "28_2013482329990144000",
                        "title": "No Replay Space",
                        "state": "Ended",
                        "is_space_available_for_replay": False,
                    },
                    "participants": {"total": 10}
                }
            }
        }

        with pytest.raises(SpaceNotAvailableError):
            SpaceURLParser.parse_audio_space_response(data)

    def test_parse_stream_response(self):
        """Test parsing stream status response."""
        data = {
            "source": {
                "location": "https://example.com/playlist.m3u8",
                "status": "ENDED",
            }
        }

        url = SpaceURLParser.parse_stream_response(data)
        assert url == "https://example.com/playlist.m3u8"

    def test_parse_stream_response_missing_location(self):
        """Test that missing location raises SpaceNotAvailableError."""
        data = {"source": {"status": "ENDED"}}

        with pytest.raises(SpaceNotAvailableError):
            SpaceURLParser.parse_stream_response(data)
