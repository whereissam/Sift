"""Custom exceptions for Sift."""


class SiftError(Exception):
    """Base exception for all Sift errors."""

    pass


# Backward compatibility aliases
XDownloaderError = SiftError
AudioGrabError = SiftError


class AuthenticationError(SiftError):
    """Invalid or expired authentication credentials."""

    pass


class ContentNotFoundError(SiftError):
    """Content not found (Space, episode, track)."""

    pass


# Backward compatibility alias
SpaceNotFoundError = ContentNotFoundError


class ContentNotAvailableError(SiftError):
    """Content exists but not available for download."""

    pass


# Backward compatibility alias
SpaceNotAvailableError = ContentNotAvailableError


class DownloadError(SiftError):
    """Failed to download audio."""

    pass


class FFmpegError(SiftError):
    """FFmpeg processing failed."""

    pass


class ToolNotFoundError(SiftError):
    """Required external tool not found (yt-dlp, spotdl, ffmpeg)."""

    pass


class RateLimitError(SiftError):
    """API rate limit exceeded."""

    pass


class UnsupportedPlatformError(SiftError):
    """URL does not match any supported platform."""

    pass
