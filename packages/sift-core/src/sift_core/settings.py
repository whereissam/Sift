"""Settings the ingestion core reads — and nothing else.

The core used to call `app.config.get_settings()` directly, which tied it to
the whole application's configuration (bot, server, LLM, cloud, ...) and made
it impossible to use as a library without the app's `.env`. This module is the
seam instead:

* `IngestSettings` holds only the fields ingest actually uses. It is a
  `BaseSettings`, so on its own it loads from the same env vars / `.env`.
* `app.config.Settings` subclasses it, so the app's settings object *is* a
  valid `IngestSettings`, and the app registers it with `set_settings_provider`.
* Library callers can skip both and pass an `IngestSettings(...)` straight to a
  downloader or `download_audio(..., settings=...)`.

Cloud transcription credentials follow the same pattern: the core never opens
the app's database, the app registers a `set_cloud_credentials_provider`.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_RATE_LIMIT = re.compile(r"^\d+(?:\.\d+)?[KMG]?$")


def normalize_rate_limit(value: object) -> Optional[str]:
    """Validate a yt-dlp ``--limit-rate`` value; blank means no limit.

    Accepts bytes per second with an optional K/M/G suffix ("500K", "1.5M").
    Anything else is rejected rather than handed to yt-dlp.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("rate limit must be a string such as '500K' or '2M'")
    text = value.strip().upper()
    if not text:
        return None
    if not _RATE_LIMIT.match(text) or float(text.rstrip("KMG")) == 0:
        raise ValueError(
            f"invalid rate limit {value!r}: use bytes/s with an optional "
            "K, M or G suffix, e.g. '500K' or '2M'"
        )
    return text


class IngestSettings(BaseSettings):
    """Configuration for downloading, auth cookies, and transcription."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Downloads
    download_dir: str = "./output"

    # yt-dlp transfer controls, applied by every yt-dlp adapter. Fragments
    # are the HLS/DASH segments fetched in parallel; the rate limit is
    # yt-dlp's --limit-rate syntax ("500K", "2M"). Throttling is less about
    # bandwidth than about looking less like a scraper to the platform.
    download_concurrent_fragments: int = Field(default=16, ge=1, le=64)
    download_rate_limit: Optional[str] = None

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

    # YouTube cookies (Netscape format file for yt-dlp authentication)
    youtube_cookies_file: str | None = None  # path to cookies.txt
    # Alternatively, read YouTube cookies straight from a local browser —
    # needed when YouTube bot-blocks the server IP ("Sign in to confirm
    # you're not a bot" / HTTP 429). Same syntax as Instagram's setting:
    # chrome, chromium, brave, edge, firefox, safari, opera, vivaldi,
    # optionally "browser:profile" (e.g. "chrome:Default").
    youtube_cookies_from_browser: str | None = None

    # Instagram cookies (Netscape format file for yt-dlp authentication).
    # Instagram requires a logged-in session for most reels/posts.
    instagram_cookies_file: str | None = None  # path to cookies.txt
    # Alternatively, read Instagram cookies straight from a local browser.
    # One of: chrome, chromium, brave, edge, firefox, safari, opera, vivaldi.
    # Optionally "browser:profile" (e.g. "chrome:Default").
    instagram_cookies_from_browser: str | None = None

    # Spotify Transcript (sp_dc cookie for Read Along API)
    spotify_sp_dc: str | None = None

    # Speaker Diarization (pyannote)
    huggingface_token: str | None = None

    # Remote Whisper Service (for Docker/GPU transcription)
    whisper_service_url: str | None = None  # e.g., "http://whisper:8001"

    # P23: subtitle reflow. Raw ASR segments are not subtitles -- Whisper
    # emits 10-30 s cues, fetched YouTube captions emit 2-3 word ones. On by
    # default because the un-reflowed output is the bug; set False to restore
    # the raw one-cue-per-segment path.
    subtitle_reflow: bool = True
    subtitle_style_preset: str = "balanced"  # broadcast | balanced | youtube | single_line

    @field_validator("download_rate_limit", mode="before")
    @classmethod
    def _check_rate_limit(cls, value: object) -> Optional[str]:
        return normalize_rate_limit(value)

    def with_download_overrides(
        self,
        *,
        concurrent_fragments: Optional[int] = None,
        rate_limit: Optional[str] = None,
    ) -> "IngestSettings":
        """A copy with per-call transfer overrides; ``None`` keeps the setting.

        `model_copy` skips validation, so the values are checked here — they
        end up in a yt-dlp argv.
        """
        update: dict[str, object] = {}
        if concurrent_fragments is not None:
            if not 1 <= concurrent_fragments <= 64:
                raise ValueError("concurrent_fragments must be between 1 and 64")
            update["download_concurrent_fragments"] = concurrent_fragments
        if rate_limit is not None:
            update["download_rate_limit"] = normalize_rate_limit(rate_limit)
        return self.model_copy(update=update) if update else self

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
def _settings_from_env() -> IngestSettings:
    return IngestSettings()


_settings_provider: Callable[[], IngestSettings] = _settings_from_env


def set_settings_provider(provider: Callable[[], IngestSettings]) -> None:
    """Replace where the core gets its default settings from.

    The app passes its own cached `get_settings`, so a `cache_clear()` there is
    seen here too. Use `reset_settings_provider` to undo.
    """
    global _settings_provider
    _settings_provider = provider


def reset_settings_provider() -> None:
    """Go back to loading settings from env / `.env`."""
    global _settings_provider
    _settings_provider = _settings_from_env


def get_ingest_settings() -> IngestSettings:
    """Default settings for callers that did not pass their own."""
    return _settings_provider()


# ─── Cloud transcription credentials ───

CloudCredentials = dict  # {"provider": str | None, "api_key": str | None}

_cloud_credentials_provider: Optional[Callable[[], Optional[CloudCredentials]]] = None


def set_cloud_credentials_provider(
    provider: Optional[Callable[[], Optional[CloudCredentials]]],
) -> None:
    """Register where `CloudTranscriptionEngine` looks up its API key.

    The app stores the key encrypted in its database; the core must not reach
    into that, so the app hands over a callable. `None` unregisters.
    """
    global _cloud_credentials_provider
    _cloud_credentials_provider = provider


def get_cloud_credentials() -> Optional[CloudCredentials]:
    """Credentials from the registered provider, or None if there is none."""
    if _cloud_credentials_provider is None:
        return None
    return _cloud_credentials_provider()
