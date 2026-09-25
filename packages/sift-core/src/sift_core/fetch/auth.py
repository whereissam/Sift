"""Authentication management for Twitter/X API."""

import contextlib
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

from ..settings import IngestSettings, get_ingest_settings
from ..exceptions import AuthenticationError


def _netscape_cookie_content(auth_token: str, ct0: str) -> str:
    """Build a Netscape-format cookie file body for yt-dlp (x.com + twitter.com)."""
    # Far-future expiry (year 2033); yt-dlp only needs the values present.
    expiry = "2000000000"
    lines = ["# Netscape HTTP Cookie File"]
    for domain in (".x.com", ".twitter.com"):
        lines.append(f"{domain}\tTRUE\t/\tTRUE\t{expiry}\tauth_token\t{auth_token}")
        lines.append(f"{domain}\tTRUE\t/\tTRUE\t{expiry}\tct0\t{ct0}")
    return "\n".join(lines) + "\n"


@contextlib.contextmanager
def twitter_ytdlp_cookies(
    settings: IngestSettings | None = None,
) -> Iterator[str | None]:
    """Yield a path to a Netscape cookie file for yt-dlp, or None if no auth.

    Prefers an explicit ``twitter_cookie_file``. Otherwise, if ``auth_token``
    and ``ct0`` are configured, writes them to a temporary cookie file that is
    removed on exit.
    """
    settings = settings or get_ingest_settings()

    if settings.twitter_cookie_file:
        yield settings.twitter_cookie_file
        return

    if settings.twitter_auth_token and settings.twitter_ct0:
        fd, path = tempfile.mkstemp(suffix=".txt", prefix="x-cookies-")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(
                    _netscape_cookie_content(
                        settings.twitter_auth_token, settings.twitter_ct0
                    )
                )
            yield path
        finally:
            with contextlib.suppress(OSError):
                os.unlink(path)
        return

    yield None


class AuthManager:
    """Manages Twitter/X authentication credentials."""

    def __init__(self, auth_token: str, ct0: str):
        """
        Initialize with authentication credentials.

        Args:
            auth_token: The auth_token cookie value from Twitter
            ct0: The ct0 cookie value (CSRF token) from Twitter
        """
        if not auth_token or not ct0:
            raise AuthenticationError("Both auth_token and ct0 are required")

        self.auth_token = auth_token
        self.ct0 = ct0

    @classmethod
    def from_env(cls, settings: IngestSettings | None = None) -> "AuthManager":
        """Load credentials from settings (environment variables by default)."""
        settings = settings or get_ingest_settings()

        if settings.twitter_cookie_file:
            return cls.from_cookie_file(settings.twitter_cookie_file)

        if not settings.twitter_auth_token or not settings.twitter_ct0:
            raise AuthenticationError(
                "Missing TWITTER_AUTH_TOKEN or TWITTER_CT0 environment variables"
            )

        return cls(
            auth_token=settings.twitter_auth_token,
            ct0=settings.twitter_ct0,
        )

    @classmethod
    def from_cookie_file(cls, path: str) -> "AuthManager":
        """
        Load credentials from a Netscape format cookie file.

        Args:
            path: Path to the cookies.txt file
        """
        cookie_path = Path(path)
        if not cookie_path.exists():
            raise AuthenticationError(f"Cookie file not found: {path}")

        auth_token = None
        ct0 = None

        with open(cookie_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or not line:
                    continue

                parts = line.split("\t")
                if len(parts) >= 7:
                    name = parts[5]
                    value = parts[6]

                    if name == "auth_token":
                        auth_token = value
                    elif name == "ct0":
                        ct0 = value

        if not auth_token or not ct0:
            raise AuthenticationError(
                "Could not find auth_token and ct0 in cookie file"
            )

        return cls(auth_token=auth_token, ct0=ct0)

    @classmethod
    def from_cookie_string(cls, cookie_string: str) -> "AuthManager":
        """
        Parse credentials from a cookie header string.

        Args:
            cookie_string: Cookie string like "auth_token=xxx; ct0=yyy"
        """
        auth_token = None
        ct0 = None

        # Parse cookie string
        for part in cookie_string.split(";"):
            part = part.strip()
            if "=" in part:
                name, value = part.split("=", 1)
                name = name.strip()
                value = value.strip()

                if name == "auth_token":
                    auth_token = value
                elif name == "ct0":
                    ct0 = value

        if not auth_token or not ct0:
            raise AuthenticationError(
                "Could not find auth_token and ct0 in cookie string"
            )

        return cls(auth_token=auth_token, ct0=ct0)

    def get_headers(self) -> dict[str, str]:
        """
        Build authenticated request headers for Twitter API.

        Returns:
            Dictionary of HTTP headers
        """
        return {
            "Authorization": f"Bearer {get_ingest_settings().twitter_bearer_token}",
            "Cookie": f"auth_token={self.auth_token}; ct0={self.ct0}",
            "x-csrf-token": self.ct0,
            "x-twitter-auth-type": "OAuth2Session",
            "x-twitter-client-language": "en",
            "x-twitter-active-user": "yes",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://x.com/",
            "Origin": "https://x.com",
        }

    def get_cookie_string(self) -> str:
        """Get cookies as a string for tools like yt-dlp."""
        return f"auth_token={self.auth_token}; ct0={self.ct0}"
