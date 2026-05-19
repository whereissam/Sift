"""Base classes for cloud storage providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Optional


class ProviderType(str, Enum):
    """Supported cloud storage provider types."""

    S3 = "s3"
    GOOGLE_DRIVE = "google_drive"
    DROPBOX = "dropbox"


@dataclass
class UploadProgress:
    """Progress information during upload."""

    bytes_uploaded: int
    total_bytes: int
    percentage: float
    speed_bytes_per_sec: Optional[float] = None

    @property
    def mb_uploaded(self) -> float:
        return self.bytes_uploaded / (1024**2)

    @property
    def total_mb(self) -> float:
        return self.total_bytes / (1024**2)


@dataclass
class CloudUploadResult:
    """Result of a cloud upload operation."""

    success: bool
    provider_type: ProviderType
    cloud_url: Optional[str] = None
    cloud_path: Optional[str] = None
    file_id: Optional[str] = None
    bytes_uploaded: int = 0
    error: Optional[str] = None
    upload_time_seconds: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "provider_type": self.provider_type.value,
            "cloud_url": self.cloud_url,
            "cloud_path": self.cloud_path,
            "file_id": self.file_id,
            "bytes_uploaded": self.bytes_uploaded,
            "error": self.error,
            "upload_time_seconds": self.upload_time_seconds,
        }


@dataclass
class ProviderConfig:
    """Configuration for a cloud storage provider."""

    id: str
    provider_type: ProviderType
    name: str
    credentials: dict = field(default_factory=dict)
    settings: dict = field(default_factory=dict)
    is_default: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CloudProvider(ABC):
    """Abstract base class for cloud storage providers."""

    def __init__(self, config: ProviderConfig):
        """
        Initialize the provider with configuration.

        Args:
            config: Provider configuration including credentials
        """
        self.config = config

    @property
    @abstractmethod
    def provider_type(self) -> ProviderType:
        """Return the provider type."""
        pass

    @property
    def provider_id(self) -> str:
        """Return the provider ID."""
        return self.config.id

    @property
    def provider_name(self) -> str:
        """Return the provider display name."""
        return self.config.name

    @abstractmethod
    async def validate_credentials(self) -> bool:
        """
        Validate that the credentials are correct.

        Returns:
            True if credentials are valid
        """
        pass

    @abstractmethod
    async def upload_file(
        self,
        local_path: Path,
        remote_path: str,
        progress_callback: Optional[Callable[[UploadProgress], None]] = None,
    ) -> CloudUploadResult:
        """
        Upload a file to cloud storage.

        Args:
            local_path: Path to the local file
            remote_path: Destination path in cloud storage
            progress_callback: Optional callback for progress updates

        Returns:
            CloudUploadResult with upload details
        """
        pass

    @abstractmethod
    async def delete_file(self, remote_path: str) -> bool:
        """
        Delete a file from cloud storage.

        Args:
            remote_path: Path to the file in cloud storage

        Returns:
            True if deletion was successful
        """
        pass

    @abstractmethod
    async def list_files(
        self,
        remote_path: str = "",
        limit: int = 100,
    ) -> list[dict]:
        """
        List files in a cloud storage path.

        Args:
            remote_path: Path to list (root if empty)
            limit: Maximum number of files to return

        Returns:
            List of file metadata dictionaries
        """
        pass

    @abstractmethod
    async def get_file_url(
        self,
        remote_path: str,
        expires_in_seconds: int = 3600,
    ) -> Optional[str]:
        """
        Get a temporary URL for a file.

        Args:
            remote_path: Path to the file
            expires_in_seconds: URL expiration time

        Returns:
            Temporary download URL or None if not supported
        """
        pass

    def get_status(self) -> dict:
        """Get provider status information."""
        return {
            "id": self.provider_id,
            "name": self.provider_name,
            "type": self.provider_type.value,
            "is_default": self.config.is_default,
        }


class OAuthProvider(CloudProvider):
    """Base class for OAuth-based cloud providers."""

    @abstractmethod
    def get_auth_url(self, redirect_uri: str, state: Optional[str] = None) -> str:
        """
        Get the OAuth authorization URL.

        Args:
            redirect_uri: OAuth callback URL
            state: Optional state parameter for CSRF protection

        Returns:
            Authorization URL to redirect user to
        """
        pass

    @abstractmethod
    async def exchange_code(
        self,
        code: str,
        redirect_uri: str,
    ) -> dict:
        """
        Exchange authorization code for tokens.

        Args:
            code: Authorization code from OAuth callback
            redirect_uri: OAuth callback URL (must match auth request)

        Returns:
            Dictionary with access_token, refresh_token, etc.
        """
        pass

    @abstractmethod
    async def refresh_tokens(self) -> dict:
        """
        Refresh access token using refresh token.

        Returns:
            Dictionary with new access_token and optionally refresh_token
        """
        pass
