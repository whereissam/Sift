"""Google Drive storage provider."""

import asyncio
import logging
import time
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlencode

from .base import (
    CloudUploadResult,
    OAuthProvider,
    ProviderConfig,
    ProviderType,
    UploadProgress,
)

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"


class GoogleDriveProvider(OAuthProvider):
    """Google Drive cloud storage provider."""

    def __init__(self, config: ProviderConfig):
        """
        Initialize Google Drive provider.

        Config credentials should contain:
            - client_id: Google OAuth client ID
            - client_secret: Google OAuth client secret
            - access_token: OAuth access token (after authorization)
            - refresh_token: OAuth refresh token (after authorization)

        Config settings can contain:
            - folder_id: Default folder ID to upload to
        """
        super().__init__(config)
        self._service = None

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.GOOGLE_DRIVE

    @property
    def client_id(self) -> str:
        return self.config.credentials.get("client_id", "")

    @property
    def client_secret(self) -> str:
        return self.config.credentials.get("client_secret", "")

    @property
    def access_token(self) -> Optional[str]:
        return self.config.credentials.get("access_token")

    @property
    def refresh_token(self) -> Optional[str]:
        return self.config.credentials.get("refresh_token")

    def get_auth_url(self, redirect_uri: str, state: Optional[str] = None) -> str:
        """Get Google OAuth authorization URL."""
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": GOOGLE_DRIVE_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
        }
        if state:
            params["state"] = state

        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(
        self,
        code: str,
        redirect_uri: str,
    ) -> dict:
        """Exchange authorization code for tokens."""
        import httpx

        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(GOOGLE_TOKEN_URL, data=data)
            response.raise_for_status()
            tokens = response.json()

            # Update credentials in config
            self.config.credentials["access_token"] = tokens["access_token"]
            if "refresh_token" in tokens:
                self.config.credentials["refresh_token"] = tokens["refresh_token"]

            return tokens

    async def refresh_tokens(self) -> dict:
        """Refresh access token using refresh token."""
        import httpx

        if not self.refresh_token:
            raise ValueError("No refresh token available")

        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(GOOGLE_TOKEN_URL, data=data)
            response.raise_for_status()
            tokens = response.json()

            # Update access token in config
            self.config.credentials["access_token"] = tokens["access_token"]

            return tokens

    def _get_service(self):
        """Get or create Google Drive API service."""
        if self._service is None:
            try:
                from google.oauth2.credentials import Credentials
                from googleapiclient.discovery import build
            except ImportError:
                raise ImportError(
                    "Google API client not installed. Install with: "
                    "pip install google-api-python-client google-auth-oauthlib"
                )

            if not self.access_token:
                raise ValueError("No access token configured. Please authorize first.")

            creds = Credentials(
                token=self.access_token,
                refresh_token=self.refresh_token,
                token_uri=GOOGLE_TOKEN_URL,
                client_id=self.client_id,
                client_secret=self.client_secret,
            )

            self._service = build("drive", "v3", credentials=creds)

        return self._service

    async def validate_credentials(self) -> bool:
        """Validate Google Drive credentials."""
        try:
            service = self._get_service()
            await asyncio.to_thread(service.about().get(fields="user").execute)
            return True
        except Exception as e:
            logger.error(f"Google Drive credential validation failed: {e}")
            return False

    async def upload_file(
        self,
        local_path: Path,
        remote_path: str,
        progress_callback: Optional[Callable[[UploadProgress], None]] = None,
    ) -> CloudUploadResult:
        """Upload file to Google Drive using resumable upload."""
        start_time = time.time()

        if not local_path.exists():
            return CloudUploadResult(
                success=False,
                provider_type=self.provider_type,
                error=f"Local file not found: {local_path}",
            )

        try:
            from googleapiclient.http import MediaFileUpload
        except ImportError:
            return CloudUploadResult(
                success=False,
                provider_type=self.provider_type,
                error="Google API client not installed",
            )

        file_size = local_path.stat().st_size
        bytes_uploaded = 0

        try:
            service = self._get_service()

            # Prepare file metadata
            file_metadata = {
                "name": remote_path.split("/")[-1] if "/" in remote_path else remote_path,
            }

            # Set parent folder if configured or specified in path
            folder_id = self.config.settings.get("folder_id")
            if folder_id:
                file_metadata["parents"] = [folder_id]

            # Create resumable upload
            media = MediaFileUpload(
                str(local_path),
                resumable=True,
                chunksize=10 * 1024 * 1024,  # 10MB chunks
            )

            request = service.files().create(
                body=file_metadata,
                media_body=media,
                fields="id,name,webViewLink,webContentLink",
            )

            response = None
            while response is None:
                status, response = await asyncio.to_thread(request.next_chunk)
                if status:
                    bytes_uploaded = int(status.progress() * file_size)
                    if progress_callback:
                        elapsed = time.time() - start_time
                        speed = bytes_uploaded / elapsed if elapsed > 0 else 0
                        progress_callback(
                            UploadProgress(
                                bytes_uploaded=bytes_uploaded,
                                total_bytes=file_size,
                                percentage=status.progress() * 100,
                                speed_bytes_per_sec=speed,
                            )
                        )

            elapsed = time.time() - start_time
            file_id = response.get("id")
            cloud_url = response.get("webViewLink")

            logger.info(
                f"Uploaded to Google Drive: {file_metadata['name']} "
                f"({file_size / (1024**2):.1f} MB in {elapsed:.1f}s)"
            )

            return CloudUploadResult(
                success=True,
                provider_type=self.provider_type,
                cloud_url=cloud_url,
                cloud_path=f"gdrive://{file_id}",
                file_id=file_id,
                bytes_uploaded=file_size,
                upload_time_seconds=elapsed,
            )

        except Exception as e:
            logger.exception(f"Google Drive upload error: {e}")
            return CloudUploadResult(
                success=False,
                provider_type=self.provider_type,
                error=str(e),
            )

    async def delete_file(self, remote_path: str) -> bool:
        """Delete a file from Google Drive."""
        try:
            service = self._get_service()

            # remote_path is expected to be file ID or gdrive://file_id
            file_id = remote_path
            if remote_path.startswith("gdrive://"):
                file_id = remote_path.replace("gdrive://", "")

            await asyncio.to_thread(service.files().delete(fileId=file_id).execute)
            return True

        except Exception as e:
            logger.error(f"Google Drive delete error: {e}")
            return False

    async def list_files(
        self,
        remote_path: str = "",
        limit: int = 100,
    ) -> list[dict]:
        """List files in Google Drive folder."""
        try:
            service = self._get_service()

            query = "trashed = false"
            if remote_path:
                # remote_path is folder ID
                query += f" and '{remote_path}' in parents"

            response = await asyncio.to_thread(
                service.files()
                .list(
                    q=query,
                    pageSize=limit,
                    fields="files(id, name, size, mimeType, modifiedTime, webViewLink)",
                )
                .execute
            )

            files = []
            for item in response.get("files", []):
                files.append({
                    "id": item["id"],
                    "name": item["name"],
                    "size": int(item.get("size", 0)),
                    "mime_type": item.get("mimeType"),
                    "modified_time": item.get("modifiedTime"),
                    "url": item.get("webViewLink"),
                })

            return files

        except Exception as e:
            logger.error(f"Google Drive list error: {e}")
            return []

    async def get_file_url(
        self,
        remote_path: str,
        expires_in_seconds: int = 3600,
    ) -> Optional[str]:
        """Get shareable URL for Google Drive file."""
        try:
            service = self._get_service()

            file_id = remote_path
            if remote_path.startswith("gdrive://"):
                file_id = remote_path.replace("gdrive://", "")

            # Get file info
            file_info = await asyncio.to_thread(
                service.files()
                .get(fileId=file_id, fields="webViewLink,webContentLink")
                .execute
            )

            return file_info.get("webViewLink") or file_info.get("webContentLink")

        except Exception as e:
            logger.error(f"Google Drive get URL error: {e}")
            return None


def create_google_drive_provider_from_env() -> Optional[GoogleDriveProvider]:
    """Create Google Drive provider from environment variables."""
    from ...config import get_settings
    settings = get_settings()

    if not settings.google_drive_client_id or not settings.google_drive_client_secret:
        return None

    config = ProviderConfig(
        id="env-google-drive",
        provider_type=ProviderType.GOOGLE_DRIVE,
        name="Google Drive (from environment)",
        credentials={
            "client_id": settings.google_drive_client_id,
            "client_secret": settings.google_drive_client_secret,
        },
        settings={},
    )

    return GoogleDriveProvider(config)
