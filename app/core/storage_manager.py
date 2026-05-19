"""Storage management for automatic cleanup and disk space monitoring."""

import asyncio
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class StorageStats:
    """Storage statistics."""

    total_bytes: int
    used_bytes: int
    free_bytes: int
    download_dir_bytes: int
    download_file_count: int

    @property
    def total_gb(self) -> float:
        return self.total_bytes / (1024**3)

    @property
    def used_gb(self) -> float:
        return self.used_bytes / (1024**3)

    @property
    def free_gb(self) -> float:
        return self.free_bytes / (1024**3)

    @property
    def download_dir_gb(self) -> float:
        return self.download_dir_bytes / (1024**3)

    @property
    def usage_percent(self) -> float:
        if self.total_bytes == 0:
            return 0.0
        return (self.used_bytes / self.total_bytes) * 100

    def to_dict(self) -> dict:
        return {
            "total_gb": round(self.total_gb, 2),
            "used_gb": round(self.used_gb, 2),
            "free_gb": round(self.free_gb, 2),
            "download_dir_gb": round(self.download_dir_gb, 2),
            "download_file_count": self.download_file_count,
            "usage_percent": round(self.usage_percent, 1),
        }


@dataclass
class CleanupResult:
    """Result of a cleanup operation."""

    files_deleted: int
    bytes_freed: int
    errors: list[str]

    @property
    def mb_freed(self) -> float:
        return self.bytes_freed / (1024**2)

    @property
    def gb_freed(self) -> float:
        return self.bytes_freed / (1024**3)

    def to_dict(self) -> dict:
        return {
            "files_deleted": self.files_deleted,
            "bytes_freed": self.bytes_freed,
            "mb_freed": round(self.mb_freed, 2),
            "gb_freed": round(self.gb_freed, 3),
            "errors": self.errors,
        }


class StorageManager:
    """Manages storage cleanup and monitoring."""

    def __init__(self, download_dir: Optional[Path] = None):
        """
        Initialize storage manager.

        Args:
            download_dir: Directory for downloads. Uses config if not provided.
        """
        if download_dir:
            self.download_dir = Path(download_dir)
        else:
            from ..config import get_settings
            self.download_dir = get_settings().get_download_path()

        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

    def get_stats(self) -> StorageStats:
        """Get current storage statistics."""
        # Get disk usage for the volume containing download_dir
        try:
            disk_usage = shutil.disk_usage(self.download_dir)
            total_bytes = disk_usage.total
            used_bytes = disk_usage.used
            free_bytes = disk_usage.free
        except OSError:
            total_bytes = used_bytes = free_bytes = 0

        # Calculate download directory size
        download_dir_bytes = 0
        download_file_count = 0

        if self.download_dir.exists():
            for entry in self.download_dir.rglob("*"):
                if entry.is_file():
                    try:
                        download_dir_bytes += entry.stat().st_size
                        download_file_count += 1
                    except OSError:
                        pass

        return StorageStats(
            total_bytes=total_bytes,
            used_bytes=used_bytes,
            free_bytes=free_bytes,
            download_dir_bytes=download_dir_bytes,
            download_file_count=download_file_count,
        )

    def get_files_by_age(self, min_age_hours: float = 0) -> list[tuple[Path, float, int]]:
        """
        Get files sorted by age (oldest first).

        Returns:
            List of (path, age_hours, size_bytes) tuples
        """
        now = datetime.now()
        files = []

        if not self.download_dir.exists():
            return files

        for entry in self.download_dir.rglob("*"):
            if entry.is_file() and entry.suffix not in [".db", ".db-journal", ".db-wal"]:
                try:
                    stat = entry.stat()
                    mtime = datetime.fromtimestamp(stat.st_mtime)
                    age_hours = (now - mtime).total_seconds() / 3600

                    if age_hours >= min_age_hours:
                        files.append((entry, age_hours, stat.st_size))
                except OSError:
                    pass

        # Sort by age (oldest first)
        files.sort(key=lambda x: x[1], reverse=True)
        return files

    def cleanup_by_age(self, max_age_hours: float) -> CleanupResult:
        """
        Delete files older than specified hours.

        Args:
            max_age_hours: Maximum age in hours before deletion

        Returns:
            CleanupResult with statistics
        """
        files_deleted = 0
        bytes_freed = 0
        errors = []

        files = self.get_files_by_age(min_age_hours=max_age_hours)

        for path, age_hours, size in files:
            try:
                path.unlink()
                files_deleted += 1
                bytes_freed += size
                logger.debug(f"Deleted old file: {path.name} (age: {age_hours:.1f}h)")
            except OSError as e:
                errors.append(f"Failed to delete {path.name}: {e}")

        if files_deleted > 0:
            logger.info(
                f"Age cleanup: deleted {files_deleted} files, "
                f"freed {bytes_freed / (1024**2):.1f} MB"
            )

        return CleanupResult(
            files_deleted=files_deleted,
            bytes_freed=bytes_freed,
            errors=errors,
        )

    def cleanup_by_size(self, max_size_gb: float) -> CleanupResult:
        """
        Delete oldest files to reduce download directory below max size.

        Args:
            max_size_gb: Maximum size of download directory in GB

        Returns:
            CleanupResult with statistics
        """
        files_deleted = 0
        bytes_freed = 0
        errors = []

        stats = self.get_stats()
        current_size = stats.download_dir_bytes
        max_size_bytes = max_size_gb * (1024**3)

        if current_size <= max_size_bytes:
            return CleanupResult(files_deleted=0, bytes_freed=0, errors=[])

        bytes_to_free = current_size - max_size_bytes
        files = self.get_files_by_age()

        for path, age_hours, size in files:
            if bytes_freed >= bytes_to_free:
                break

            try:
                path.unlink()
                files_deleted += 1
                bytes_freed += size
                logger.debug(f"Deleted file for size limit: {path.name}")
            except OSError as e:
                errors.append(f"Failed to delete {path.name}: {e}")

        if files_deleted > 0:
            logger.info(
                f"Size cleanup: deleted {files_deleted} files, "
                f"freed {bytes_freed / (1024**2):.1f} MB"
            )

        return CleanupResult(
            files_deleted=files_deleted,
            bytes_freed=bytes_freed,
            errors=errors,
        )

    def cleanup_for_free_space(self, min_free_gb: float) -> CleanupResult:
        """
        Delete oldest files to maintain minimum free disk space.

        Args:
            min_free_gb: Minimum free space to maintain in GB

        Returns:
            CleanupResult with statistics
        """
        files_deleted = 0
        bytes_freed = 0
        errors = []

        stats = self.get_stats()
        min_free_bytes = min_free_gb * (1024**3)

        if stats.free_bytes >= min_free_bytes:
            return CleanupResult(files_deleted=0, bytes_freed=0, errors=[])

        bytes_to_free = min_free_bytes - stats.free_bytes
        files = self.get_files_by_age()

        for path, age_hours, size in files:
            if bytes_freed >= bytes_to_free:
                break

            try:
                path.unlink()
                files_deleted += 1
                bytes_freed += size
                logger.debug(f"Deleted file for free space: {path.name}")
            except OSError as e:
                errors.append(f"Failed to delete {path.name}: {e}")

        if files_deleted > 0:
            logger.info(
                f"Free space cleanup: deleted {files_deleted} files, "
                f"freed {bytes_freed / (1024**2):.1f} MB"
            )

        return CleanupResult(
            files_deleted=files_deleted,
            bytes_freed=bytes_freed,
            errors=errors,
        )

    def cleanup_empty_dirs(self) -> int:
        """
        Remove empty directories in the download folder.

        Returns:
            Number of directories removed
        """
        removed = 0

        if not self.download_dir.exists():
            return 0

        # Walk from bottom up to handle nested empty dirs
        for entry in sorted(self.download_dir.rglob("*"), reverse=True):
            if entry.is_dir():
                try:
                    # Check if directory is empty
                    if not any(entry.iterdir()):
                        entry.rmdir()
                        removed += 1
                        logger.debug(f"Removed empty directory: {entry}")
                except OSError:
                    pass

        return removed

    async def run_cleanup(
        self,
        max_age_hours: Optional[float] = None,
        max_size_gb: Optional[float] = None,
        min_free_gb: Optional[float] = None,
    ) -> CleanupResult:
        """
        Run cleanup with specified policies.

        Args:
            max_age_hours: Delete files older than this
            max_size_gb: Keep download dir under this size
            min_free_gb: Maintain at least this much free disk space

        Returns:
            Combined CleanupResult
        """
        total_files = 0
        total_bytes = 0
        all_errors = []

        # Apply policies in order of priority
        if min_free_gb is not None:
            result = self.cleanup_for_free_space(min_free_gb)
            total_files += result.files_deleted
            total_bytes += result.bytes_freed
            all_errors.extend(result.errors)

        if max_size_gb is not None:
            result = self.cleanup_by_size(max_size_gb)
            total_files += result.files_deleted
            total_bytes += result.bytes_freed
            all_errors.extend(result.errors)

        if max_age_hours is not None:
            result = self.cleanup_by_age(max_age_hours)
            total_files += result.files_deleted
            total_bytes += result.bytes_freed
            all_errors.extend(result.errors)

        # Clean up empty directories
        self.cleanup_empty_dirs()

        return CleanupResult(
            files_deleted=total_files,
            bytes_freed=total_bytes,
            errors=all_errors,
        )

    async def _background_cleanup_loop(self, interval_seconds: int):
        """Background cleanup loop."""
        from ..config import get_settings
        settings = get_settings()

        while self._running:
            try:
                await asyncio.sleep(interval_seconds)

                if not self._running:
                    break

                # Get cleanup settings
                max_age_hours = float(settings.cleanup_after_hours) if settings.cleanup_after_hours else None
                max_size_gb = settings.max_storage_gb
                min_free_gb = settings.min_free_space_gb

                # Run cleanup if any policy is configured
                if any([max_age_hours, max_size_gb, min_free_gb]):
                    result = await self.run_cleanup(
                        max_age_hours=max_age_hours,
                        max_size_gb=max_size_gb,
                        min_free_gb=min_free_gb,
                    )

                    if result.files_deleted > 0:
                        logger.info(
                            f"Background cleanup: deleted {result.files_deleted} files, "
                            f"freed {result.gb_freed:.2f} GB"
                        )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Background cleanup error: {e}")
                await asyncio.sleep(60)  # Wait a bit before retrying

    async def start_background_cleanup(self, interval_seconds: Optional[int] = None):
        """Start background cleanup task."""
        if self._running:
            return

        from ..config import get_settings
        settings = get_settings()

        if interval_seconds is None:
            interval_seconds = settings.storage_cleanup_interval

        self._running = True
        self._cleanup_task = asyncio.create_task(
            self._background_cleanup_loop(interval_seconds)
        )
        logger.info(f"Started background storage cleanup (interval: {interval_seconds}s)")

    async def stop_background_cleanup(self):
        """Stop background cleanup task."""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
        logger.info("Stopped background storage cleanup")

    def get_policies(self) -> dict:
        """Get current cleanup policies from config."""
        from ..config import get_settings
        settings = get_settings()

        return {
            "cleanup_after_hours": settings.cleanup_after_hours,
            "max_storage_gb": settings.max_storage_gb,
            "min_free_space_gb": settings.min_free_space_gb,
            "cleanup_interval_seconds": settings.storage_cleanup_interval,
            "cleanup_enabled": settings.storage_cleanup_enabled,
        }


# Global instance
_storage_manager: Optional[StorageManager] = None


def get_storage_manager() -> StorageManager:
    """Get or create the global storage manager instance."""
    global _storage_manager
    if _storage_manager is None:
        _storage_manager = StorageManager()
    return _storage_manager