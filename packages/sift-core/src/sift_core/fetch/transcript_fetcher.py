"""Fetch existing transcripts from YouTube and Spotify without Whisper."""

import asyncio
import logging
import re
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)


@dataclass
class FetchedTranscript:
    """Result of fetching a transcript from a platform."""

    success: bool
    text: str = ""
    segments: list[dict] = field(default_factory=list)  # [{start, end, text}]
    language: str = ""
    duration_seconds: float = 0.0
    source: str = ""  # "youtube_manual", "youtube_auto", "spotify"
    error: str | None = None


def _extract_youtube_video_id(url: str) -> str | None:
    """Extract video ID from various YouTube URL formats."""
    patterns = [
        r"(?:youtube\.com/watch\?.*v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/|youtube\.com/shorts/)([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def _extract_spotify_episode_id(url: str) -> str | None:
    """Extract episode ID from Spotify URL."""
    match = re.search(r"open\.spotify\.com/episode/([a-zA-Z0-9]+)", url)
    return match.group(1) if match else None


def _is_youtube_url(url: str) -> bool:
    return bool(re.search(r"(youtube\.com|youtu\.be)", url))


def _is_spotify_url(url: str) -> bool:
    return bool(re.search(r"open\.spotify\.com/episode/", url))


class TranscriptFetcher:
    """Fetches existing transcripts from YouTube captions and Spotify Read Along."""

    def can_fetch_transcript(self, url: str) -> bool:
        """Check if the URL is from a platform that supports transcript fetching."""
        return _is_youtube_url(url) or _is_spotify_url(url)

    async def fetch_transcript(
        self, url: str, language: str | None = None
    ) -> FetchedTranscript:
        """Fetch transcript from YouTube or Spotify."""
        if _is_youtube_url(url):
            video_id = _extract_youtube_video_id(url)
            if not video_id:
                return FetchedTranscript(success=False, error="Could not extract YouTube video ID")
            return await self._fetch_youtube_transcript(video_id, language)

        if _is_spotify_url(url):
            episode_id = _extract_spotify_episode_id(url)
            if not episode_id:
                return FetchedTranscript(success=False, error="Could not extract Spotify episode ID")
            return await self._fetch_spotify_transcript(episode_id)

        return FetchedTranscript(success=False, error="Unsupported platform for transcript fetching")

    async def list_available_languages(self, url: str) -> list[dict]:
        """List available transcript languages for a YouTube video.

        Returns list of dicts: [{language_code, language, is_generated}]
        """
        if not _is_youtube_url(url):
            return []

        video_id = _extract_youtube_video_id(url)
        if not video_id:
            return []

        def _list():
            from youtube_transcript_api import YouTubeTranscriptApi

            ytt = YouTubeTranscriptApi()
            transcript_list = ytt.list(video_id)
            result = []
            for t in transcript_list:
                result.append({
                    "language_code": t.language_code,
                    "language": t.language,
                    "is_generated": t.is_generated,
                })
            return result

        try:
            return await asyncio.to_thread(_list)
        except Exception as e:
            logger.warning(f"Failed to list transcript languages for {video_id}: {e}")
            return []

    async def _fetch_youtube_transcript(
        self, video_id: str, language: str | None = None
    ) -> FetchedTranscript:
        """Fetch transcript from YouTube using youtube-transcript-api."""

        def _fetch():
            from youtube_transcript_api import YouTubeTranscriptApi

            ytt = YouTubeTranscriptApi()
            transcript_list = ytt.list(video_id)

            # Build language preference order
            if language:
                # Try manual captions first, then auto-generated
                try:
                    transcript = transcript_list.find_manually_created_transcript([language])
                    source = "youtube_manual"
                except Exception:
                    try:
                        transcript = transcript_list.find_generated_transcript([language])
                        source = "youtube_auto"
                    except Exception:
                        # Fall back to any available transcript
                        transcript = transcript_list.find_transcript([language, "en"])
                        source = "youtube_auto"
            else:
                # Prefer manual captions in any language, then auto-generated
                manual = [t for t in transcript_list if not t.is_generated]
                if manual:
                    transcript = manual[0]
                    source = "youtube_manual"
                else:
                    generated = [t for t in transcript_list if t.is_generated]
                    if generated:
                        transcript = generated[0]
                        source = "youtube_auto"
                    else:
                        raise Exception("No transcripts available")

            data = transcript.fetch()
            return data, transcript.language_code, source

        try:
            data, lang_code, source = await asyncio.to_thread(_fetch)

            segments = []
            text_parts = []
            max_end = 0.0

            for entry in data:
                start = entry.start
                duration = entry.duration
                end = start + duration
                text = entry.text
                segments.append({"start": start, "end": end, "text": text})
                text_parts.append(text)
                if end > max_end:
                    max_end = end

            full_text = " ".join(text_parts)

            return FetchedTranscript(
                success=True,
                text=full_text,
                segments=segments,
                language=lang_code,
                duration_seconds=max_end,
                source=source,
            )
        except Exception as e:
            logger.error(f"YouTube transcript fetch failed for {video_id}: {e}")
            return FetchedTranscript(
                success=False, error=f"Failed to fetch YouTube transcript: {e}"
            )

    async def _fetch_spotify_transcript(self, episode_id: str) -> FetchedTranscript:
        """Fetch transcript from Spotify Read Along API."""
        from ..settings import get_ingest_settings

        settings = get_ingest_settings()
        sp_dc = settings.spotify_sp_dc

        if not sp_dc:
            return FetchedTranscript(
                success=False,
                error="Spotify sp_dc cookie not configured. Set SPOTIFY_SP_DC in .env",
            )

        try:
            access_token = await self._get_spotify_access_token(sp_dc)
        except Exception as e:
            return FetchedTranscript(
                success=False, error=f"Failed to get Spotify access token: {e}"
            )

        url = f"https://spclient.wg.spotify.com/transcript-read-along/v2/episode/{episode_id}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "App-Platform": "WebPlayer",
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=headers, timeout=15)
                resp.raise_for_status()
                data = resp.json()

            sections = data.get("section", [])
            segments = []
            text_parts = []
            max_end = 0.0

            for section in sections:
                start_ms = section.get("startMs", 0)
                # Use the text from the section
                lines = section.get("text", {}).get("sentence", {}).get("text", "")
                if not lines:
                    continue

                start = start_ms / 1000.0
                # Estimate end from next section or add a default duration
                end = start + 5.0  # default 5s, will be overridden below
                segments.append({"start": start, "end": end, "text": lines})
                text_parts.append(lines)

            # Fix segment end times using next segment's start
            for i in range(len(segments) - 1):
                segments[i]["end"] = segments[i + 1]["start"]
            if segments:
                max_end = segments[-1]["end"]

            full_text = " ".join(text_parts)

            return FetchedTranscript(
                success=True,
                text=full_text,
                segments=segments,
                language="",  # Spotify doesn't expose language in this API
                duration_seconds=max_end,
                source="spotify",
            )
        except httpx.HTTPStatusError as e:
            logger.error(f"Spotify transcript API error: {e.response.status_code}")
            return FetchedTranscript(
                success=False,
                error=f"Spotify API returned {e.response.status_code}. Transcript may not be available.",
            )
        except Exception as e:
            logger.error(f"Spotify transcript fetch failed: {e}")
            return FetchedTranscript(
                success=False, error=f"Failed to fetch Spotify transcript: {e}"
            )

    async def _get_spotify_access_token(self, sp_dc: str) -> str:
        """Exchange sp_dc cookie for a bearer token."""
        url = "https://open.spotify.com/get_access_token?reason=transport&productType=web_player"
        cookies = {"sp_dc": sp_dc}
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Origin": "https://open.spotify.com",
            "Referer": "https://open.spotify.com/",
        }

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, cookies=cookies, headers=headers, timeout=15)
            if resp.status_code == 403:
                raise Exception(
                    "Spotify blocked the token request (403). "
                    "This may be due to regional restrictions. "
                    "Try using a VPN or proxy to a supported region."
                )
            resp.raise_for_status()
            data = resp.json()

        token = data.get("accessToken")
        if not token:
            raise Exception("No access token in Spotify response")
        return token
