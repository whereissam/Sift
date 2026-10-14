"""Amazon S3 and S3-compatible storage provider."""

import asyncio
import logging
import time
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlsplit

from sift_core.fetch.url_validator import pinned_sync_client, validate_url_ssrf

from ...config import get_settings
from .base import (
    CloudProvider,
    CloudUploadResult,
    ProviderConfig,
    ProviderType,
    UploadProgress,
)

logger = logging.getLogger(__name__)


def _operator_allowed(netloc: str, host: str) -> bool:
    allowed = {
        e.strip().lower() for e in get_settings().s3_allowed_endpoints.split(",") if e.strip()
    }
    return netloc.lower() in allowed or host in allowed


def validate_endpoint_url(endpoint_url: Optional[str]) -> None:
    """Refuse an S3 endpoint_url that points at a private or internal address.

    endpoint_url comes from API input, and every S3 call (validate, list,
    upload, delete) sends a signed request to it. Self-hosted endpoints on
    private addresses are allowed only through S3_ALLOWED_ENDPOINTS.

    Raises:
        ValueError: if the endpoint is malformed or not allowed.
    """
    if endpoint_url is None:
        return
    if not isinstance(endpoint_url, str):
        raise ValueError("endpoint_url must be a string")
    parts = urlsplit(endpoint_url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("endpoint_url must be an http(s) URL")
    if _operator_allowed(parts.netloc, parts.hostname.lower()):
        return
    ok, error = validate_url_ssrf(endpoint_url)
    if not ok:
        raise ValueError(
            f"endpoint_url not allowed: {error}. "
            "Add it to S3_ALLOWED_ENDPOINTS to use a private endpoint."
        )


def endpoint_needs_pinning(endpoint_url: Optional[str]) -> bool:
    """A caller-supplied endpoint the operator has not allowlisted."""
    if not endpoint_url:
        return False  # AWS itself
    parts = urlsplit(endpoint_url)
    return not _operator_allowed(parts.netloc, (parts.hostname or "").lower())


class _BufferedRaw:
    """The minimal raw-stream interface botocore reads a response through."""

    def __init__(self, content: bytes):
        self._content = content
        self._pos = 0

    def read(self, amt: Optional[int] = None) -> bytes:
        end = len(self._content) if amt is None else self._pos + amt
        chunk = self._content[self._pos:end]
        self._pos += len(chunk)
        return chunk

    def stream(self, **kwargs):
        while chunk := self.read(65536):
            yield chunk

    def close(self) -> None:
        pass


def _send_pinned(request, **kwargs):
    """botocore before-send hook: perform the request through a pinned client.

    Validating endpoint_url once is not enough: botocore resolves the name
    again for every connection, so a DNS-rebinding name could pass the check
    and then reach an internal address. The pinned client validates the IP
    it actually connects to. Returning a response here makes botocore skip
    its own HTTP send. The request is already signed; the Host header and
    TLS SNI keep the hostname.
    """
    from botocore.awsrequest import AWSResponse

    body = request.body
    if hasattr(body, "read"):
        body = body.read()
    headers = {
        k: v.decode() if isinstance(v, bytes) else v
        for k, v in request.headers.items()
        if k.lower() != "expect"  # httpx does not do 100-continue
    }
    with pinned_sync_client(timeout=120.0) as client:
        resp = client.request(request.method, request.url, headers=headers, content=body)
        content = resp.content  # decoded, so drop the encoding header below
    resp_headers = {
        k: v for k, v in resp.headers.items() if k.lower() != "content-encoding"
    }
    return AWSResponse(request.url, resp.status_code, resp_headers, _BufferedRaw(content))


class S3Provider(CloudProvider):
    """Amazon S3 and S3-compatible cloud storage provider."""

    def __init__(self, config: ProviderConfig):
        """
        Initialize S3 provider.

        Config credentials should contain:
            - access_key_id: AWS access key ID
            - secret_access_key: AWS secret access key

        Config settings can contain:
            - bucket: S3 bucket name
            - region: AWS region (default: us-east-1)
            - endpoint_url: Custom endpoint for S3-compatible services
        """
        super().__init__(config)
        self._client = None

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.S3

    def _get_client(self):
        """Get or create boto3 S3 client."""
        if self._client is None:
            try:
                import boto3
                from botocore.config import Config as BotoConfig
            except ImportError:
                raise ImportError(
                    "boto3 not installed. Install with: pip install boto3"
                )

            credentials = self.config.credentials
            settings = self.config.settings
            # Providers also load from the DB and env, not only the API.
            validate_endpoint_url(settings.get("endpoint_url"))

            boto_config = BotoConfig(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
            )

            self._client = boto3.client(
                "s3",
                aws_access_key_id=credentials.get("access_key_id"),
                aws_secret_access_key=credentials.get("secret_access_key"),
                region_name=settings.get("region", "us-east-1"),
                endpoint_url=settings.get("endpoint_url"),
                config=boto_config,
            )
            if endpoint_needs_pinning(settings.get("endpoint_url")):
                self._client.meta.events.register("before-send.s3", _send_pinned)

        return self._client

    @property
    def bucket(self) -> str:
        """Get the configured S3 bucket name."""
        return self.config.settings.get("bucket", "")

    async def validate_credentials(self) -> bool:
        """Validate S3 credentials by listing buckets."""
        try:
            client = self._get_client()
            await asyncio.to_thread(client.list_buckets)
            return True
        except Exception as e:
            logger.error(f"S3 credential validation failed: {e}")
            return False

    async def upload_file(
        self,
        local_path: Path,
        remote_path: str,
        progress_callback: Optional[Callable[[UploadProgress], None]] = None,
    ) -> CloudUploadResult:
        """Upload file to S3 with multipart support for large files."""
        start_time = time.time()

        if not local_path.exists():
            return CloudUploadResult(
                success=False,
                provider_type=self.provider_type,
                error=f"Local file not found: {local_path}",
            )

        file_size = local_path.stat().st_size
        bytes_uploaded = 0

        def progress_handler(bytes_amount):
            nonlocal bytes_uploaded
            bytes_uploaded += bytes_amount
            if progress_callback:
                elapsed = time.time() - start_time
                speed = bytes_uploaded / elapsed if elapsed > 0 else 0
                progress_callback(
                    UploadProgress(
                        bytes_uploaded=bytes_uploaded,
                        total_bytes=file_size,
                        percentage=(bytes_uploaded / file_size) * 100,
                        speed_bytes_per_sec=speed,
                    )
                )

        try:
            client = self._get_client()

            # Use multipart upload for files > 100MB
            transfer_config = None
            if file_size > 100 * 1024 * 1024:
                try:
                    from boto3.s3.transfer import TransferConfig
                    transfer_config = TransferConfig(
                        multipart_threshold=100 * 1024 * 1024,
                        max_concurrency=10,
                        multipart_chunksize=100 * 1024 * 1024,
                    )
                except ImportError:
                    pass

            await asyncio.to_thread(
                client.upload_file,
                str(local_path),
                self.bucket,
                remote_path,
                Callback=progress_handler,
                Config=transfer_config,
            )

            # Generate URL
            endpoint_url = self.config.settings.get("endpoint_url")
            region = self.config.settings.get("region", "us-east-1")

            if endpoint_url:
                cloud_url = f"{endpoint_url}/{self.bucket}/{remote_path}"
            else:
                cloud_url = f"https://{self.bucket}.s3.{region}.amazonaws.com/{remote_path}"

            elapsed = time.time() - start_time
            logger.info(f"Uploaded to S3: {remote_path} ({file_size / (1024**2):.1f} MB in {elapsed:.1f}s)")

            return CloudUploadResult(
                success=True,
                provider_type=self.provider_type,
                cloud_url=cloud_url,
                cloud_path=f"s3://{self.bucket}/{remote_path}",
                bytes_uploaded=file_size,
                upload_time_seconds=elapsed,
            )

        except Exception as e:
            logger.exception(f"S3 upload error: {e}")
            return CloudUploadResult(
                success=False,
                provider_type=self.provider_type,
                error=str(e),
            )

    async def delete_file(self, remote_path: str) -> bool:
        """Delete a file from S3."""
        try:
            client = self._get_client()
            await asyncio.to_thread(
                client.delete_object,
                Bucket=self.bucket,
                Key=remote_path,
            )
            return True
        except Exception as e:
            logger.error(f"S3 delete error: {e}")
            return False

    async def list_files(
        self,
        remote_path: str = "",
        limit: int = 100,
    ) -> list[dict]:
        """List files in S3 bucket."""
        try:
            client = self._get_client()

            params = {
                "Bucket": self.bucket,
                "MaxKeys": limit,
            }
            if remote_path:
                params["Prefix"] = remote_path

            response = await asyncio.to_thread(client.list_objects_v2, **params)

            files = []
            for obj in response.get("Contents", []):
                files.append({
                    "key": obj["Key"],
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"].isoformat(),
                    "etag": obj.get("ETag", "").strip('"'),
                })

            return files

        except Exception as e:
            logger.error(f"S3 list error: {e}")
            return []

    async def get_file_url(
        self,
        remote_path: str,
        expires_in_seconds: int = 3600,
    ) -> Optional[str]:
        """Generate a pre-signed URL for S3 file."""
        try:
            client = self._get_client()

            url = await asyncio.to_thread(
                client.generate_presigned_url,
                "get_object",
                Params={"Bucket": self.bucket, "Key": remote_path},
                ExpiresIn=expires_in_seconds,
            )

            return url

        except Exception as e:
            logger.error(f"S3 presigned URL error: {e}")
            return None


def create_s3_provider_from_env() -> Optional[S3Provider]:
    """Create S3 provider from environment variables."""
    from ...config import get_settings
    settings = get_settings()

    if not settings.s3_access_key_id or not settings.s3_secret_access_key:
        return None

    config = ProviderConfig(
        id="env-s3",
        provider_type=ProviderType.S3,
        name="S3 (from environment)",
        credentials={
            "access_key_id": settings.s3_access_key_id,
            "secret_access_key": settings.s3_secret_access_key,
        },
        settings={
            "bucket": settings.s3_bucket or "",
            "region": settings.s3_region,
            "endpoint_url": settings.s3_endpoint_url,
        },
    )

    return S3Provider(config)
