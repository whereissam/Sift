"""Embed metadata into audio files using mutagen."""

import logging
from pathlib import Path
from typing import Optional

from .base import AudioMetadata
from .url_validator import safe_get

logger = logging.getLogger(__name__)


class MetadataTagger:
    """Embed metadata into audio files using mutagen."""

    async def tag_file(
        self,
        file_path: Path,
        metadata: AudioMetadata,
        embed_artwork: bool = True,
    ) -> bool:
        """
        Embed metadata tags into audio file.

        Args:
            file_path: Path to the audio file
            metadata: AudioMetadata with tag information
            embed_artwork: Whether to download and embed artwork

        Returns:
            True if tagging succeeded, False otherwise
        """
        if not file_path.exists():
            logger.error(f"File not found: {file_path}")
            return False

        suffix = file_path.suffix.lower()

        # Download artwork if available
        artwork = None
        if embed_artwork and metadata.artwork_url:
            artwork = await self._download_artwork(metadata.artwork_url)

        try:
            if suffix == ".mp3":
                self._tag_mp3(file_path, metadata, artwork)
            elif suffix in (".m4a", ".mp4", ".aac"):
                self._tag_m4a(file_path, metadata, artwork)
            elif suffix == ".ogg":
                self._tag_ogg(file_path, metadata, artwork)
            elif suffix == ".flac":
                self._tag_flac(file_path, metadata, artwork)
            else:
                logger.warning(f"Unsupported format for tagging: {suffix}")
                return False

            logger.info(f"Successfully tagged: {file_path.name}")
            return True

        except Exception as e:
            logger.error(f"Failed to tag {file_path}: {e}")
            return False

    async def _download_artwork(self, url: str) -> Optional[bytes]:
        """Download artwork from URL (SSRF-safe)."""
        try:
            response = await safe_get(url, timeout=30)
            if response.status_code == 200:
                return response.content
            logger.warning(f"Failed to download artwork: HTTP {response.status_code}")
        except ValueError as e:
            logger.warning(f"Blocked artwork download: {e}")
        except Exception as e:
            logger.warning(f"Failed to download artwork: {e}")
        return None

    def _tag_mp3(
        self, file_path: Path, metadata: AudioMetadata, artwork: Optional[bytes]
    ):
        """Tag MP3 file using ID3."""
        from mutagen.id3 import ID3, TIT2, TPE1, TALB, COMM, TDRC, APIC, ID3NoHeaderError

        try:
            tags = ID3(file_path)
        except ID3NoHeaderError:
            tags = ID3()

        # Title
        if metadata.title:
            tags["TIT2"] = TIT2(encoding=3, text=metadata.title)

        # Artist (creator name)
        if metadata.creator_name:
            tags["TPE1"] = TPE1(encoding=3, text=metadata.creator_name)

        # Album (show name)
        if metadata.show_name:
            tags["TALB"] = TALB(encoding=3, text=metadata.show_name)

        # Comment (description)
        if metadata.description:
            tags["COMM"] = COMM(
                encoding=3, lang="eng", desc="", text=metadata.description[:1000]
            )

        # Year (published date)
        if metadata.published_at:
            tags["TDRC"] = TDRC(encoding=3, text=str(metadata.published_at.year))

        # Artwork
        if artwork:
            # Detect image type
            mime_type = "image/jpeg"
            if artwork[:8] == b"\x89PNG\r\n\x1a\n":
                mime_type = "image/png"

            tags["APIC"] = APIC(
                encoding=3,
                mime=mime_type,
                type=3,  # Front cover
                desc="Cover",
                data=artwork,
            )

        tags.save(file_path)

    def _tag_m4a(
        self, file_path: Path, metadata: AudioMetadata, artwork: Optional[bytes]
    ):
        """Tag M4A/MP4 file using MP4Tags."""
        from mutagen.mp4 import MP4, MP4Cover

        audio = MP4(file_path)

        # Title
        if metadata.title:
            audio["\xa9nam"] = [metadata.title]

        # Artist
        if metadata.creator_name:
            audio["\xa9ART"] = [metadata.creator_name]

        # Album (show name)
        if metadata.show_name:
            audio["\xa9alb"] = [metadata.show_name]

        # Description/Comment
        if metadata.description:
            audio["desc"] = [metadata.description[:1000]]

        # Year
        if metadata.published_at:
            audio["\xa9day"] = [str(metadata.published_at.year)]

        # Artwork
        if artwork:
            # Detect image type
            image_format = MP4Cover.FORMAT_JPEG
            if artwork[:8] == b"\x89PNG\r\n\x1a\n":
                image_format = MP4Cover.FORMAT_PNG

            audio["covr"] = [MP4Cover(artwork, imageformat=image_format)]

        audio.save()

    def _tag_ogg(
        self, file_path: Path, metadata: AudioMetadata, artwork: Optional[bytes]
    ):
        """Tag OGG file using VorbisComment."""
        from mutagen.oggvorbis import OggVorbis
        import base64

        audio = OggVorbis(file_path)

        # Title
        if metadata.title:
            audio["title"] = metadata.title

        # Artist
        if metadata.creator_name:
            audio["artist"] = metadata.creator_name

        # Album
        if metadata.show_name:
            audio["album"] = metadata.show_name

        # Description
        if metadata.description:
            audio["description"] = metadata.description[:1000]

        # Year
        if metadata.published_at:
            audio["date"] = str(metadata.published_at.year)

        # Artwork (as base64-encoded METADATA_BLOCK_PICTURE)
        if artwork:
            from mutagen.flac import Picture

            picture = Picture()
            picture.type = 3  # Front cover
            picture.desc = "Cover"
            picture.data = artwork

            if artwork[:8] == b"\x89PNG\r\n\x1a\n":
                picture.mime = "image/png"
            else:
                picture.mime = "image/jpeg"

            # Encode as base64 for Vorbis comment
            audio["metadata_block_picture"] = [
                base64.b64encode(picture.write()).decode("ascii")
            ]

        audio.save()

    def _tag_flac(
        self, file_path: Path, metadata: AudioMetadata, artwork: Optional[bytes]
    ):
        """Tag FLAC file."""
        from mutagen.flac import FLAC, Picture

        audio = FLAC(file_path)

        # Title
        if metadata.title:
            audio["title"] = metadata.title

        # Artist
        if metadata.creator_name:
            audio["artist"] = metadata.creator_name

        # Album
        if metadata.show_name:
            audio["album"] = metadata.show_name

        # Description
        if metadata.description:
            audio["description"] = metadata.description[:1000]

        # Year
        if metadata.published_at:
            audio["date"] = str(metadata.published_at.year)

        # Artwork
        if artwork:
            picture = Picture()
            picture.type = 3  # Front cover
            picture.desc = "Cover"
            picture.data = artwork

            if artwork[:8] == b"\x89PNG\r\n\x1a\n":
                picture.mime = "image/png"
            else:
                picture.mime = "image/jpeg"

            audio.add_picture(picture)

        audio.save()
