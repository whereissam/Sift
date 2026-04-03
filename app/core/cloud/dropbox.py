"""Dropbox storage provider."""

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

DROPBOX_AUTH_URL = "https://www.dropbox.com/oauth2/authorize"
DROPBOX_TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"

# Dropbox file size thresholds
CHUNK_SIZE = 150 * 1024 * 1024  # 150 MB chunks for large uploads
UPLOAD_SESSION_THRESHOLD = 150 * 1024 * 1024  # Use sessions for files > 150 MB


class DropboxProvider(OAuthProvider):
    """Dropbox cloud storage provider."""

    def __init__(self, config: ProviderConfig):
        """
        Initialize Dropbox provider.

        Config credentials should contain:
            - app_key: Dropbox app key
            - app_secret: Dropbox app secret
            - access_token: OAuth access token (after authorization)
            - refresh_token: OAuth refresh token (after authorization)

        Config settings can contain:
            - root_path: Default path prefix for uploads (default: /Sift)
        """
        super().__init__(config)
        self._client = None

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.DROPBOX

    @property
    def app_key(self) -> str:
        return self.config.credentials.get("app_key", "")

    @property
    def app_secret(self) -> str:
        return self.config.credentials.get("app_secret", "")

    @property
    def access_token(self) -> Optional[str]:
        return self.config.credentials.get("access_token")

    @property
    def refresh_token(self) -> Optional[str]:
        return self.config.credentials.get("refresh_token")

    @property
    def root_path(self) -> str:
        return self.config.settings.get("root_path", "/Sift")

    def get_auth_url(self, redirect_uri: str, state: Optional[str] = None) -> str:
        """Get Dropbox OAuth authorization URL."""
        params = {
            "client_id": self.app_key,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "token_access_type": "offline",
        }
        if state:
            params["state"] = state

        return f"{DROPBOX_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(
        self,
        code: str,
        redirect_uri: str,
    ) -> dict:
        """Exchange authorization code for tokens."""
        import httpx

        data = {
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                DROPBOX_TOKEN_URL,
                data=data,
                auth=(self.app_key, self.app_secret),
            )
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
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                DROPBOX_TOKEN_URL,
                data=data,
                auth=(self.app_key, self.app_secret),
            )
            response.raise_for_status()
            tokens = response.json()

            # Update access token in config
            self.config.credentials["access_token"] = tokens["access_token"]

            return tokens

    def _get_client(self):
        """Get or create Dropbox client."""
        if self._client is None:
            try:
                import dropbox
            except ImportError:
                raise ImportError(
                    "dropbox not installed. Install with: pip install dropbox"
                )

            if not self.access_token:
                raise ValueError("No access token configured. Please authorize first.")

            self._client = dropbox.Dropbox(
                oauth2_access_token=self.access_token,
                oauth2_refresh_token=self.refresh_token,
                app_key=self.app_key,
                app_secret=self.app_secret,
            )

        return self._client

    async def validate_credentials(self) -> bool:
        """Validate Dropbox credentials."""
        try:
            client = self._get_client()
            await asyncio.to_thread(client.users_get_current_account)
            return True
        except Exception as e:
            logger.error(f"Dropbox credential validation failed: {e}")
            return False

    async def upload_file(
        self,
        local_path: Path,
        remote_path: str,
        progress_callback: Optional[Callable[[UploadProgress], None]] = None,
    ) -> CloudUploadResult:
        """Upload file to Dropbox with chunked upload for large files."""
        start_time = time.time()

        if not local_path.exists():
            return CloudUploadResult(
                success=False,
                provider_type=self.provider_type,
                error=f"Local file not found: {local_path}",
            )

        try:
            import dropbox
        except ImportError:
            return CloudUploadResult(
                success=False,
                provider_type=self.provider_type,
                error="dropbox not installed",
            )

        file_size = local_path.stat().st_size

        # Ensure path starts with root_path
        if not remote_path.startswith("/"):
            remote_path = f"/{remote_path}"
        if not remote_path.startswith(self.root_path):
            remote_path = f"{self.root_path}{remote_path}"

        try:
            client = self._get_client()

            if file_size <= UPLOAD_SESSION_THRESHOLD:
                # Simple upload for small files
                result = await self._simple_upload(
                    client, local_path, remote_path, file_size, progress_callback, start_time
                )
            else:
                # Chunked upload for large files
                result = await self._chunked_upload(
                    client, local_path, remote_path, file_size, progress_callback, start_time
                )

            return result

        except Exception as e:
            logger.exception(f"Dropbox upload error: {e}")
            return CloudUploadResult(
                success=False,
                provider_type=self.provider_type,
                error=str(e),
            )

    async def _simple_upload(
        self,
        client,
        local_path: Path,
        remote_path: str,
        file_size: int,
        progress_callback: Optional[Callable[[UploadProgress], None]],
        start_time: float,
    ) -> CloudUploadResult:
        """Simple upload for files under threshold."""
        import dropbox

        with open(local_path, "rb") as f:
            data = f.read()

        result = await asyncio.to_thread(
            client.files_upload,
            data,
            remote_path,
            mode=dropbox.files.WriteMode.overwrite,
        )

        if progress_callback:
            elapsed = time.time() - start_time
            progress_callback(
                UploadProgress(
                    bytes_uploaded=file_size,
                    total_bytes=file_size,
                    percentage=100.0,
                    speed_bytes_per_sec=file_size / elapsed if elapsed > 0 else 0,
                )
            )

        # Get shared link
        try:
            link_result = await asyncio.to_thread(
                client.sharing_create_shared_link_with_settings,
                remote_path,
            )
            cloud_url = link_result.url
        except Exception:
            cloud_url = None

        elapsed = time.time() - start_time
        logger.info(
            f"Uploaded to Dropbox: {remote_path} "
            f"({file_size / (1024**2):.1f} MB in {elapsed:.1f}s)"
        )

        return CloudUploadResult(
            success=True,
            provider_type=self.provider_type,
            cloud_url=cloud_url,
            cloud_path=f"dropbox://{remote_path}",
            file_id=result.id,
            bytes_uploaded=file_size,
            upload_time_seconds=elapsed,
        )

    async def _chunked_upload(
        self,
        client,
        local_path: Path,
        remote_path: str,
        file_size: int,
        progress_callback: Optional[Callable[[UploadProgress], None]],
        start_time: float,
    ) -> CloudUploadResult:
        """Chunked upload for large files."""
        import dropbox

        bytes_uploaded = 0

        with open(local_path, "rb") as f:
            # Start upload session
            session_start = await asyncio.to_thread(
                client.files_upload_session_start,
                f.read(CHUNK_SIZE),
            )
            session_id = session_start.session_id
            bytes_uploaded = CHUNK_SIZE

            if progress_callback:
                elapsed = time.time() - start_time
                progress_callback(
                    UploadProgress(
                        bytes_uploaded=bytes_uploaded,
                        total_bytes=file_size,
                        percentage=(bytes_uploaded / file_size) * 100,
                        speed_bytes_per_sec=bytes_uploaded / elapsed if elapsed > 0 else 0,
                    )
                )

            # Upload remaining chunks
            cursor = dropbox.files.UploadSessionCursor(
                session_id=session_id,
                offset=bytes_uploaded,
            )

            while bytes_uploaded < file_size:
                remaining = file_size - bytes_uploaded
                chunk = f.read(min(CHUNK_SIZE, remaining))

                if not chunk:
                    break

                if bytes_uploaded + len(chunk) >= file_size:
                    # Final chunk - finish the session
                    commit = dropbox.files.CommitInfo(
                        path=remote_path,
                        mode=dropbox.files.WriteMode.overwrite,
                    )
                    result = await asyncio.to_thread(
                        client.files_upload_session_finish,
                        chunk,
                        cursor,
                        commit,
                    )
                else:
                    # Intermediate chunk
                    await asyncio.to_thread(
                        client.files_upload_session_append_v2,
                        chunk,
                        cursor,
                    )
                    cursor.offset += len(chunk)

                bytes_uploaded += len(chunk)

                if progress_callback:
                    elapsed = time.time() - start_time
                    progress_callback(
                        UploadProgress(
                            bytes_uploaded=bytes_uploaded,
                            total_bytes=file_size,
                            percentage=(bytes_uploaded / file_size) * 100,
                            speed_bytes_per_sec=bytes_uploaded / elapsed if elapsed > 0 else 0,
                        )
                    )

        # Get shared link
        try:
            link_result = await asyncio.to_thread(
                client.sharing_create_shared_link_with_settings,
                remote_path,
            )
            cloud_url = link_result.url
        except Exception:
            cloud_url = None

        elapsed = time.time() - start_time
        logger.info(
            f"Uploaded to Dropbox (chunked): {remote_path} "
            f"({file_size / (1024**2):.1f} MB in {elapsed:.1f}s)"
        )

        return CloudUploadResult(
            success=True,
            provider_type=self.provider_type,
            cloud_url=cloud_url,
            cloud_path=f"dropbox://{remote_path}",
            file_id=result.id,
            bytes_uploaded=file_size,
            upload_time_seconds=elapsed,
        )

    async def delete_file(self, remote_path: str) -> bool:
        """Delete a file from Dropbox."""
        try:
            client = self._get_client()

            path = remote_path
            if remote_path.startswith("dropbox://"):
                path = remote_path.replace("dropbox://", "")

            await asyncio.to_thread(client.files_delete_v2, path)
            return True

        except Exception as e:
            logger.error(f"Dropbox delete error: {e}")
            return False

    async def list_files(
        self,
        remote_path: str = "",
        limit: int = 100,
    ) -> list[dict]:
        """List files in Dropbox folder."""
        try:
            client = self._get_client()

            path = remote_path or self.root_path
            if not path.startswith("/"):
                path = f"/{path}"

            result = await asyncio.to_thread(
                client.files_list_folder,
                path,
                limit=limit,
            )

            files = []
            for entry in result.entries:
                file_info = {
                    "id": entry.id,
                    "name": entry.name,
                    "path": entry.path_display,
                }

                # Check if it's a file (has size) or folder
                if hasattr(entry, "size"):
                    file_info["size"] = entry.size
                    file_info["is_folder"] = False
                else:
                    file_info["is_folder"] = True

                if hasattr(entry, "server_modified"):
                    file_info["modified_time"] = entry.server_modified.isoformat()

                files.append(file_info)

            return files

        except Exception as e:
            logger.error(f"Dropbox list error: {e}")
            return []

    async def get_file_url(
        self,
        remote_path: str,
        expires_in_seconds: int = 3600,
    ) -> Optional[str]:
        """Get temporary download URL for Dropbox file."""
        try:
            client = self._get_client()

            path = remote_path
            if remote_path.startswith("dropbox://"):
                path = remote_path.replace("dropbox://", "")

            result = await asyncio.to_thread(
                client.files_get_temporary_link,
                path,
            )

            return result.link

        except Exception as e:
            logger.error(f"Dropbox get URL error: {e}")
            return None


def create_dropbox_provider_from_env() -> Optional[DropboxProvider]:
    """Create Dropbox provider from environment variables."""
    from ...config import get_settings
    settings = get_settings()

    if not settings.dropbox_app_key or not settings.dropbox_app_secret:
        return None

    config = ProviderConfig(
        id="env-dropbox",
        provider_type=ProviderType.DROPBOX,
        name="Dropbox (from environment)",
        credentials={
            "app_key": settings.dropbox_app_key,
            "app_secret": settings.dropbox_app_secret,
        },
        settings={},
    )

    return DropboxProvider(config)
