"""One known-good link per platform, checked against the real site.

Platforms break without any change on our side: a site reshuffles its page,
or a yt-dlp release changes an extractor. These links are the canaries — if
one stops working, the adapter (or the pinned yt-dlp) needs attention.

Every URL can be replaced without editing this file by setting
``SIFT_CANARY_<PLATFORM>`` (for example ``SIFT_CANARY_SPOTIFY``). That is the
only way to check the four platforms whose links expire (see
docs/test-links.md) — set it to a fresh URL before the run.
"""

import os
from dataclasses import dataclass
from typing import Mapping

from sift_core import Platform


@dataclass(frozen=True)
class Canary:
    platform: Platform
    url: str | None
    # Download the whole file on every run. Only for short media: a podcast
    # episode is ~100 MB, and metadata already proves the extractor works.
    download: bool = False
    # At least one of these must be set, or the canary skips (auth-gated sites).
    requires_any_env: tuple[str, ...] = ()
    # Same, but only on CI: the site works from a home connection and
    # bot-checks datacenter IPs such as GitHub's runners.
    ci_requires_any_env: tuple[str, ...] = ()

    @property
    def env_var(self) -> str:
        return f"SIFT_CANARY_{self.platform.name}"

    @property
    def resolved_url(self) -> str | None:
        override = os.environ.get(self.env_var, "").strip()
        return override or self.url

    @property
    def is_video(self) -> bool:
        return self.platform in VIDEO_PLATFORMS

    def skip_reason(self, environ: Mapping[str, str] = os.environ) -> str | None:
        """Why this canary can't run here, or None if it can."""
        if not self.resolved_url:
            return f"no stable link for {self.platform.value}; set {self.env_var}"
        if self.requires_any_env and not any(environ.get(v) for v in self.requires_any_env):
            return f"{self.platform.value} needs one of {', '.join(self.requires_any_env)}"
        if (
            environ.get("CI")
            and self.ci_requires_any_env
            and not any(environ.get(v) for v in self.ci_requires_any_env)
        ):
            return (
                f"{self.platform.value} bot-checks CI runner IPs; add a cookies secret "
                f"so one of {', '.join(self.ci_requires_any_env)} is set"
            )
        return None


VIDEO_PLATFORMS = frozenset(
    {Platform.X_VIDEO, Platform.YOUTUBE_VIDEO, Platform.INSTAGRAM, Platform.XIAOHONGSHU}
)

# "Me at the zoo": 19 seconds, the first YouTube upload, never coming down.
_SHORT_YOUTUBE = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
# From a GitHub runner YouTube answers "Sign in to confirm you're not a bot".
_YOUTUBE_COOKIES = ("YOUTUBE_COOKIES_FILE", "YOUTUBE_COOKIES_FROM_BROWSER")

CANARIES: tuple[Canary, ...] = (
    # Audio
    Canary(Platform.YOUTUBE, _SHORT_YOUTUBE, download=True, ci_requires_any_env=_YOUTUBE_COOKIES),
    Canary(
        Platform.APPLE_PODCASTS,
        "https://podcasts.apple.com/de/podcast/351-rache-ist-kein-sch%C3%B6nes-ferd-sommerhack"
        "/id1292709842?i=1000774914977",
    ),
    Canary(Platform.XIAOYUZHOU, "https://www.xiaoyuzhoufm.com/episode/6a4123349d2f5743683f2bd6"),
    Canary(Platform.XIMALAYA, "https://www.ximalaya.com/sound/998052123"),
    # Links to these expire; set SIFT_CANARY_<PLATFORM> to a fresh one.
    Canary(Platform.SPOTIFY, None),
    Canary(Platform.X_SPACES, None),
    Canary(Platform.DISCORD, None),
    # Video
    Canary(
        Platform.YOUTUBE_VIDEO, _SHORT_YOUTUBE, download=True, ci_requires_any_env=_YOUTUBE_COOKIES
    ),
    Canary(Platform.X_VIDEO, "https://x.com/SpaceX/status/2072695632104468543", download=True),
    Canary(
        Platform.INSTAGRAM,
        "https://www.instagram.com/reel/DZKus9XB34d/",
        download=True,
        requires_any_env=("INSTAGRAM_COOKIES_FILE", "INSTAGRAM_COOKIES_FROM_BROWSER"),
    ),
    Canary(Platform.XIAOHONGSHU, None),
)
