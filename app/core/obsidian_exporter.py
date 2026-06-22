"""Obsidian vault exporter for transcriptions."""

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


def _yaml_scalar(value: object) -> str:
    """Serialize a value as a single-line, YAML-safe scalar.

    Prevents YAML injection from user-controlled strings (e.g. a ``source_url``
    containing newlines or other YAML control characters).
    """
    # Collapse any newlines first so a malicious value can't break out of the
    # frontmatter onto its own line; PyYAML then quotes/escapes as needed.
    if isinstance(value, str):
        value = re.sub(r"\s*\n\s*", " ", value)
    dumped = yaml.safe_dump(
        value, default_flow_style=True, allow_unicode=True, width=float("inf")
    ).strip()
    # safe_dump appends a trailing "\n..." document-end marker for plain scalars.
    if dumped.endswith("\n..."):
        dumped = dumped[:-4].strip()
    return dumped


@dataclass
class ObsidianExportResult:
    """Result of an Obsidian export operation."""

    success: bool
    file_path: Optional[str] = None
    vault_path: Optional[str] = None
    note_name: Optional[str] = None
    error: Optional[str] = None


class ObsidianExporter:
    """Export transcriptions to Obsidian vault as markdown notes."""

    def __init__(self, vault_path: str):
        self.vault_path = Path(vault_path)

    def validate_vault(self) -> tuple[bool, Optional[str]]:
        """
        Check if vault path exists and is writable.

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not self.vault_path.exists():
            return False, f"Vault path does not exist: {self.vault_path}"

        if not self.vault_path.is_dir():
            return False, f"Vault path is not a directory: {self.vault_path}"

        # Check if writable by attempting to create a test file
        test_file = self.vault_path / ".sift_write_test"
        try:
            test_file.touch()
            test_file.unlink()
        except PermissionError:
            return False, f"Vault is not writable: {self.vault_path}"
        except Exception as e:
            return False, f"Cannot write to vault: {e}"

        return True, None

    def sanitize_filename(self, title: str, max_length: int = 100) -> str:
        """
        Remove invalid characters for filenames.

        Args:
            title: Original title
            max_length: Maximum filename length (default 100)

        Returns:
            Sanitized filename (without extension)
        """
        # Remove invalid filename characters
        invalid_chars = r'[<>:"/\\|?*\x00-\x1f]'
        sanitized = re.sub(invalid_chars, "", title)

        # Replace multiple spaces with single space
        sanitized = re.sub(r"\s+", " ", sanitized)

        # Trim whitespace
        sanitized = sanitized.strip()

        # Truncate to max length
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length].strip()

        # Ensure we have a valid filename
        if not sanitized:
            sanitized = "Untitled"

        return sanitized

    def generate_frontmatter(
        self,
        title: str,
        source_url: Optional[str] = None,
        duration_seconds: Optional[float] = None,
        language: Optional[str] = None,
        tags: Optional[list[str]] = None,
        created_at: Optional[str] = None,
    ) -> str:
        """
        Generate YAML frontmatter for the note.

        Args:
            title: Note title
            source_url: Original content URL
            duration_seconds: Content duration
            language: Detected language
            tags: List of tags
            created_at: Creation timestamp

        Returns:
            YAML frontmatter string
        """
        lines = ["---"]

        # Title (user-controlled — YAML-safe quote/escape)
        lines.append(f"title: {_yaml_scalar(title)}")

        # Source URL (user-controlled — YAML-safe quote/escape)
        if source_url:
            lines.append(f"source: {_yaml_scalar(source_url)}")

        # Date
        if created_at:
            lines.append(f"date: {_yaml_scalar(created_at)}")
        else:
            lines.append(f"date: {datetime.utcnow().isoformat()}")

        # Duration
        if duration_seconds:
            minutes = int(duration_seconds // 60)
            seconds = int(duration_seconds % 60)
            lines.append(f"duration: {minutes}m {seconds}s")

        # Language (user-controlled — YAML-safe quote/escape)
        if language:
            lines.append(f"language: {_yaml_scalar(language)}")

        # Tags
        if tags:
            # Each tag is user-controlled — serialize the list as a YAML-safe
            # flow sequence (handles commas, brackets, newlines).
            lines.append(f"tags: {_yaml_scalar(list(tags))}")

        lines.append("---")
        lines.append("")  # Empty line after frontmatter

        return "\n".join(lines)

    def _format_duration(self, seconds: float) -> str:
        """Format duration in human-readable format."""
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        if minutes > 60:
            hours = minutes // 60
            minutes = minutes % 60
            return f"{hours}h {minutes}m {secs}s"
        return f"{minutes}m {secs}s"

    async def export_transcription(
        self,
        job_id: str,
        transcript: str,
        title: str,
        source_url: Optional[str] = None,
        duration_seconds: Optional[float] = None,
        language: Optional[str] = None,
        tags: Optional[list[str]] = None,
        subfolder: Optional[str] = None,
        created_at: Optional[str] = None,
    ) -> ObsidianExportResult:
        """
        Export transcript as a markdown note to Obsidian vault.

        Args:
            job_id: Unique job identifier
            transcript: The transcript text
            title: Note title
            source_url: Original content URL
            duration_seconds: Content duration in seconds
            language: Detected language
            tags: List of tags for the note
            subfolder: Subfolder within vault (default: root)
            created_at: Creation timestamp

        Returns:
            ObsidianExportResult with success status and file path
        """
        # Validate vault
        is_valid, error = self.validate_vault()
        if not is_valid:
            return ObsidianExportResult(success=False, error=error)

        # Determine target directory with path traversal protection
        target_dir = self.vault_path
        if subfolder:
            # Sanitize subfolder to prevent path traversal
            safe_subfolder = Path(subfolder)
            # Reject absolute paths and ".." components
            if safe_subfolder.is_absolute() or ".." in safe_subfolder.parts:
                return ObsidianExportResult(
                    success=False,
                    error=f"Invalid subfolder: path traversal detected in '{subfolder}'",
                )
            target_dir = (self.vault_path / safe_subfolder).resolve()
            # Verify resolved path is within vault
            if not str(target_dir).startswith(str(self.vault_path.resolve())):
                return ObsidianExportResult(
                    success=False,
                    error="Subfolder resolves outside of vault directory",
                )
            target_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename
        sanitized_title = self.sanitize_filename(title)
        note_name = f"{sanitized_title}.md"
        file_path = target_dir / note_name

        # Handle duplicate filenames by appending timestamp
        if file_path.exists():
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            note_name = f"{sanitized_title}_{timestamp}.md"
            file_path = target_dir / note_name

        # Generate content
        frontmatter = self.generate_frontmatter(
            title=title,
            source_url=source_url,
            duration_seconds=duration_seconds,
            language=language,
            tags=tags,
            created_at=created_at,
        )

        content = frontmatter + transcript

        # Write file
        try:
            file_path.write_text(content, encoding="utf-8")
            logger.info(f"Exported transcription to Obsidian: {file_path}")

            return ObsidianExportResult(
                success=True,
                file_path=str(file_path),
                vault_path=str(self.vault_path),
                note_name=note_name,
            )
        except PermissionError:
            return ObsidianExportResult(
                success=False,
                error=f"Permission denied writing to: {file_path}",
            )
        except Exception as e:
            logger.error(f"Failed to export to Obsidian: {e}")
            return ObsidianExportResult(
                success=False,
                error=f"Failed to write note: {e}",
            )
