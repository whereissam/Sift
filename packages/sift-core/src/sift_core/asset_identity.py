"""Asset identity: URL canonicalization and source fingerprinting.

Turns a submitted source (URL or uploaded file) into a stable canonical
form so the same content maps to one asset (see
docs/ingestion-api-migration.md §4).

Conservatism rule: when in doubt, do NOT merge. Unknown query parameters
are preserved — an over-eager canonicalizer would incorrectly merge
distinct content, which is much worse than under-merging.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Tracking parameters that never select different content. Kept short and
# explicit on purpose (blocklist, not allowlist).
_TRACKING_PARAMS = {"fbclid", "gclid", "igshid", "si", "ref", "ref_src"}
_TRACKING_PREFIXES = ("utm_",)

# Host-specific tracking params (e.g. x.com share tokens). Keyed by host
# suffix; only applied when the host matches, because the same name can be
# meaningful elsewhere (YouTube's t= is a timestamp, not tracking).
_HOST_TRACKING_PARAMS = {
    "x.com": {"s", "t"},
    "twitter.com": {"s", "t"},
}

_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "www.youtube-nocookie.com",
    "youtube-nocookie.com",
}
_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YOUTUBE_PATH_ID = re.compile(r"^/(?:shorts|embed|live|v)/([A-Za-z0-9_-]{11})")


@dataclass(frozen=True)
class CanonicalSource:
    """Canonical identity for a submitted source."""

    source_type: str  # 'url' | 'upload'
    canonical_source: str
    platform: Optional[str] = None

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.canonical_source.encode("utf-8")).hexdigest()


def _youtube_video_id(parts) -> Optional[str]:
    host = parts.hostname or ""
    if host == "youtu.be":
        candidate = parts.path.lstrip("/").split("/")[0]
        return candidate if _YOUTUBE_ID.match(candidate) else None
    if host in _YOUTUBE_HOSTS:
        if parts.path == "/watch":
            for key, value in parse_qsl(parts.query, keep_blank_values=True):
                if key == "v" and _YOUTUBE_ID.match(value):
                    return value
            return None
        match = _YOUTUBE_PATH_ID.match(parts.path)
        if match:
            return match.group(1)
    return None


def _strip_tracking(host: str, query: str) -> str:
    host_specific = set()
    for suffix, params in _HOST_TRACKING_PARAMS.items():
        if host == suffix or host.endswith("." + suffix):
            host_specific = params
            break

    kept = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        lowered = key.lower()
        if lowered in _TRACKING_PARAMS or lowered in host_specific:
            continue
        if any(lowered.startswith(p) for p in _TRACKING_PREFIXES):
            continue
        kept.append((key, value))

    kept.sort()
    return urlencode(kept)


def canonicalize_url(url: str) -> CanonicalSource:
    """Canonicalize a source URL.

    Platform-specific canonicalizers first (currently YouTube); everything
    else gets conservative generic normalization.
    """
    parts = urlsplit(url.strip())

    video_id = _youtube_video_id(parts)
    if video_id:
        return CanonicalSource(
            source_type="url",
            canonical_source=f"youtube:video:{video_id}",
            platform="youtube",
        )

    scheme = (parts.scheme or "https").lower()
    host = (parts.hostname or "").lower()

    port = parts.port
    if port and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        netloc = f"{host}:{port}"
    else:
        netloc = host

    path = parts.path
    if path not in ("", "/"):
        path = path.rstrip("/")

    query = _strip_tracking(host, parts.query)

    return CanonicalSource(
        source_type="url",
        canonical_source=urlunsplit((scheme, netloc, path, query, "")),
        platform=None,
    )


def fingerprint_file(path: Path) -> CanonicalSource:
    """Canonical identity for an uploaded file: SHA-256 of its content.

    Never fingerprint by filename — same bytes under different names are
    the same asset.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            digest.update(chunk)
    return upload_source_from_sha256(digest.hexdigest())


def upload_source_from_sha256(hex_digest: str) -> CanonicalSource:
    return CanonicalSource(
        source_type="upload",
        canonical_source=f"upload:sha256:{hex_digest}",
        platform=None,
    )


def legacy_upload_source(source_url: str) -> CanonicalSource:
    """Backfill fallback for historical upload rows whose file content is
    no longer available: fingerprint the literal source string. Never
    merges with content-hashed uploads."""
    return CanonicalSource(
        source_type="upload",
        canonical_source=f"upload:legacy:{source_url}",
        platform=None,
    )


def canonical_source_for_job(
    source_url: Optional[str],
    content_sha256: Optional[str] = None,
) -> Optional[CanonicalSource]:
    """Resolve the canonical source for a job submission, or None when the
    source has no durable identity (e.g. resume:// pseudo-URLs)."""
    if content_sha256:
        return upload_source_from_sha256(content_sha256)
    if not source_url:
        return None
    if source_url.startswith("resume://"):
        return None
    if source_url.startswith("upload://"):
        # Upload without a content hash (legacy callers): literal identity.
        return legacy_upload_source(source_url)
    if source_url.startswith(("http://", "https://")):
        return canonicalize_url(source_url)
    return None
