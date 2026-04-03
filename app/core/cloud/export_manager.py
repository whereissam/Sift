"""Export manager for cloud storage uploads."""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from .base import CloudProvider, CloudUploadResult, ProviderConfig, ProviderType, UploadProgress
from .s3 import S3Provider, create_s3_provider_from_env
from .google_drive import GoogleDriveProvider, create_google_drive_provider_from_env
from .dropbox import DropboxProvider, create_dropbox_provider_from_env

logger = logging.getLogger(__name__)


@dataclass
class ExportJob:
    """Represents a cloud export job."""

    id: str
    job_id: Optional[str]  # Related download/transcribe job ID
    file_path: str
    provider_id: str
    destination_path: str
    status: str = "pending"  # pending, uploading, completed, failed
    progress: float = 0.0
    bytes_uploaded: int = 0
    total_bytes: int = 0
    cloud_url: Optional[str] = None
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "job_id": self.job_id,
            "file_path": self.file_path,
            "provider_id": self.provider_id,
            "destination_path": self.destination_path,
            "status": self.status,
            "progress": round(self.progress, 2),
            "bytes_uploaded": self.bytes_uploaded,
            "total_bytes": self.total_bytes,
            "cloud_url": self.cloud_url,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class ExportManager:
    """Manages cloud storage exports."""

    def __init__(self):
        """Initialize the export manager."""
        self._providers: dict[str, CloudProvider] = {}
        self._export_jobs: dict[str, ExportJob] = {}
        self._processing_queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        self._running = False

        # Load providers from environment
        self._load_env_providers()

    def _load_env_providers(self):
        """Load cloud providers from environment variables."""
        # Try to load S3 provider
        s3_provider = create_s3_provider_from_env()
        if s3_provider:
            self._providers[s3_provider.provider_id] = s3_provider
            logger.info("Loaded S3 provider from environment")

        # Try to load Google Drive provider
        gdrive_provider = create_google_drive_provider_from_env()
        if gdrive_provider:
            self._providers[gdrive_provider.provider_id] = gdrive_provider
            logger.info("Loaded Google Drive provider from environment")

        # Try to load Dropbox provider
        dropbox_provider = create_dropbox_provider_from_env()
        if dropbox_provider:
            self._providers[dropbox_provider.provider_id] = dropbox_provider
            logger.info("Loaded Dropbox provider from environment")

    def register_provider(self, config: ProviderConfig) -> CloudProvider:
        """
        Register a new cloud storage provider.

        Args:
            config: Provider configuration

        Returns:
            The created provider instance
        """
        if config.provider_type == ProviderType.S3:
            provider = S3Provider(config)
        elif config.provider_type == ProviderType.GOOGLE_DRIVE:
            provider = GoogleDriveProvider(config)
        elif config.provider_type == ProviderType.DROPBOX:
            provider = DropboxProvider(config)
        else:
            raise ValueError(f"Unsupported provider type: {config.provider_type}")

        self._providers[config.id] = provider
        logger.info(f"Registered cloud provider: {config.name} ({config.provider_type.value})")
        return provider

    def unregister_provider(self, provider_id: str) -> bool:
        """
        Unregister a cloud storage provider.

        Args:
            provider_id: ID of the provider to remove

        Returns:
            True if provider was removed
        """
        if provider_id in self._providers:
            del self._providers[provider_id]
            logger.info(f"Unregistered cloud provider: {provider_id}")
            return True
        return False

    def get_provider(self, provider_id: str) -> Optional[CloudProvider]:
        """Get a provider by ID."""
        return self._providers.get(provider_id)

    def list_providers(self) -> list[dict]:
        """List all registered providers."""
        return [p.get_status() for p in self._providers.values()]

    def get_default_provider(self) -> Optional[CloudProvider]:
        """Get the default provider."""
        for provider in self._providers.values():
            if provider.config.is_default:
                return provider
        # Return first provider if no default set
        return next(iter(self._providers.values()), None)

    async def create_export(
        self,
        file_path: str,
        provider_id: Optional[str] = None,
        destination_path: Optional[str] = None,
        job_id: Optional[str] = None,
    ) -> ExportJob:
        """
        Create a new export job.

        Args:
            file_path: Path to the local file to export
            provider_id: ID of the provider to use (default if not specified)
            destination_path: Remote path (filename if not specified)
            job_id: Related job ID for tracking

        Returns:
            The created export job
        """
        # Resolve provider
        if provider_id:
            provider = self.get_provider(provider_id)
            if not provider:
                raise ValueError(f"Provider not found: {provider_id}")
        else:
            provider = self.get_default_provider()
            if not provider:
                raise ValueError("No cloud providers configured")
            provider_id = provider.provider_id

        # Verify file exists and is within allowed directory
        from ...config import get_settings as _get_settings
        path = Path(file_path).resolve()
        _base_dir = Path(_get_settings().download_dir).resolve()
        if not str(path).startswith(str(_base_dir) + "/") and path != _base_dir:
            raise ValueError(f"file_path must be within the download directory: {_base_dir}")
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # Set destination path
        if not destination_path:
            destination_path = path.name

        # Create export job
        export_id = str(uuid.uuid4())[:8]
        export_job = ExportJob(
            id=export_id,
            job_id=job_id,
            file_path=str(path.absolute()),
            provider_id=provider_id,
            destination_path=destination_path,
            total_bytes=path.stat().st_size,
            created_at=datetime.utcnow(),
        )

        self._export_jobs[export_id] = export_job

        # Queue for processing
        await self._processing_queue.put(export_id)

        logger.info(f"Created export job {export_id}: {path.name} -> {provider_id}")
        return export_job

    def get_export(self, export_id: str) -> Optional[ExportJob]:
        """Get an export job by ID."""
        return self._export_jobs.get(export_id)

    def list_exports(
        self,
        status: Optional[str] = None,
        job_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[ExportJob]:
        """List export jobs with optional filtering."""
        jobs = list(self._export_jobs.values())

        if status:
            jobs = [j for j in jobs if j.status == status]
        if job_id:
            jobs = [j for j in jobs if j.job_id == job_id]

        # Sort by creation time (newest first)
        jobs.sort(key=lambda j: j.created_at or datetime.min, reverse=True)

        return jobs[:limit]

    async def _process_export(self, export_id: str):
        """Process a single export job."""
        export_job = self._export_jobs.get(export_id)
        if not export_job:
            return

        provider = self.get_provider(export_job.provider_id)
        if not provider:
            export_job.status = "failed"
            export_job.error = f"Provider not found: {export_job.provider_id}"
            return

        export_job.status = "uploading"

        def progress_callback(progress: UploadProgress):
            export_job.progress = progress.percentage
            export_job.bytes_uploaded = progress.bytes_uploaded

        try:
            result = await provider.upload_file(
                local_path=Path(export_job.file_path),
                remote_path=export_job.destination_path,
                progress_callback=progress_callback,
            )

            if result.success:
                export_job.status = "completed"
                export_job.progress = 100.0
                export_job.cloud_url = result.cloud_url
                export_job.completed_at = datetime.utcnow()
                logger.info(f"Export completed: {export_id} -> {result.cloud_url}")
            else:
                export_job.status = "failed"
                export_job.error = result.error
                logger.error(f"Export failed: {export_id} - {result.error}")

        except Exception as e:
            export_job.status = "failed"
            export_job.error = str(e)
            logger.exception(f"Export error: {export_id}")

    async def _worker_loop(self):
        """Background worker for processing export queue."""
        while self._running:
            try:
                # Wait for export job with timeout
                try:
                    export_id = await asyncio.wait_for(
                        self._processing_queue.get(),
                        timeout=1.0,
                    )
                except asyncio.TimeoutError:
                    continue

                await self._process_export(export_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Export worker error: {e}")
                await asyncio.sleep(1)

    async def start(self):
        """Start the export worker."""
        if self._running:
            return

        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("Export manager started")

    async def stop(self):
        """Stop the export worker."""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        logger.info("Export manager stopped")


# Global instance
_export_manager: Optional[ExportManager] = None


def get_export_manager() -> ExportManager:
    """Get or create the global export manager instance."""
    global _export_manager
    if _export_manager is None:
        _export_manager = ExportManager()
    return _export_manager
