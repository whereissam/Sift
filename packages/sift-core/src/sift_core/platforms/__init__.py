"""Platform-specific downloader implementations.

`DOWNLOADERS` is the one list of adapters. `DownloaderFactory` derives URL
detection, lookup by `Platform`, and the available-platform list from it, so
adding a platform means writing the adapter and adding it here — nowhere else.
"""

from ..base import PlatformDownloader
from .xspaces import XSpacesDownloader
from .apple_podcasts import ApplePodcastsDownloader
from .spotify import SpotifyDownloader
from .youtube import YouTubeDownloader
from .x_video import XVideoDownloader
from .youtube_video import YouTubeVideoDownloader
from .xiaoyuzhou import XiaoyuzhouDownloader
from .ximalaya import XimalayaDownloader
from .instagram_video import InstagramVideoDownloader
from .xiaohongshu_video import XiaohongshuVideoDownloader
from .discord_audio import DiscordAudioDownloader

# Order is URL-detection order: the first adapter whose `can_handle_url`
# matches wins. Audio adapters come before video ones on purpose — a YouTube
# URL means audio unless the caller asks for the video platform, and an X
# Spaces link must not fall through to the X video adapter.
DOWNLOADERS: tuple[type[PlatformDownloader], ...] = (
    # Audio
    XSpacesDownloader,
    ApplePodcastsDownloader,
    SpotifyDownloader,
    YouTubeDownloader,
    XiaoyuzhouDownloader,
    XimalayaDownloader,
    DiscordAudioDownloader,
    # Video
    XVideoDownloader,
    YouTubeVideoDownloader,
    InstagramVideoDownloader,
    XiaohongshuVideoDownloader,
)

__all__ = [
    "DOWNLOADERS",
    # Audio
    "XSpacesDownloader",
    "ApplePodcastsDownloader",
    "SpotifyDownloader",
    "YouTubeDownloader",
    "XiaoyuzhouDownloader",
    "XimalayaDownloader",
    "DiscordAudioDownloader",
    # Video
    "XVideoDownloader",
    "YouTubeVideoDownloader",
    "InstagramVideoDownloader",
    "XiaohongshuVideoDownloader",
]
