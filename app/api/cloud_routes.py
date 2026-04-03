"""Cloud storage API routes."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from .auth import verify_api_key
from ..core.cloud import (
    ExportManager,
    get_export_manager,
    ProviderConfig,
    ProviderType,
)

router = APIRouter(prefix="/cloud", tags=["cloud"], dependencies=[Depends(verify_api_key)])


class ProviderCreateRequest(BaseModel):
    """Request to create/configure a cloud provider."""

    id: str
    provider_type: str  # s3, google_drive, dropbox
    name: str
    credentials: dict = {}
    settings: dict = {}
    is_default: bool = False


class ProviderResponse(BaseModel):
    """Cloud provider information."""

    id: str
    name: str
    type: str
    is_default: bool


class ExportRequest(BaseModel):
    """Request to start a cloud export."""

    file_path: str
    provider_id: Optional[str] = None
    destination_path: Optional[str] = None
    job_id: Optional[str] = None


class ExportResponse(BaseModel):
    """Export job information."""

    id: str
    job_id: Optional[str]
    file_path: str
    provider_id: str
    destination_path: str
    status: str
    progress: float
    bytes_uploaded: int
    total_bytes: int
    cloud_url: Optional[str]
    error: Optional[str]
    created_at: Optional[str]
    completed_at: Optional[str]


class OAuthUrlResponse(BaseModel):
    """OAuth authorization URL response."""

    authorization_url: str
    state: Optional[str] = None


class OAuthCallbackRequest(BaseModel):
    """OAuth callback request."""

    code: str
    redirect_uri: str
    state: Optional[str] = None


# ============ Provider Management ============


@router.post("/providers", response_model=ProviderResponse)
async def create_provider(request: ProviderCreateRequest):
    """
    Configure a new cloud storage provider.

    Supported provider types:
    - s3: Amazon S3 or S3-compatible storage
    - google_drive: Google Drive
    - dropbox: Dropbox
    """
    try:
        provider_type = ProviderType(request.provider_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider type: {request.provider_type}. "
                   f"Supported: s3, google_drive, dropbox",
        )

    manager = get_export_manager()

    config = ProviderConfig(
        id=request.id,
        provider_type=provider_type,
        name=request.name,
        credentials=request.credentials,
        settings=request.settings,
        is_default=request.is_default,
    )

    try:
        provider = manager.register_provider(config)
        status = provider.get_status()
        return ProviderResponse(**status)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/providers", response_model=list[ProviderResponse])
async def list_providers():
    """List all configured cloud storage providers."""
    manager = get_export_manager()
    providers = manager.list_providers()
    return [ProviderResponse(**p) for p in providers]


@router.get("/providers/{provider_id}", response_model=ProviderResponse)
async def get_provider(provider_id: str):
    """Get a specific cloud provider."""
    manager = get_export_manager()
    provider = manager.get_provider(provider_id)

    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    return ProviderResponse(**provider.get_status())


@router.delete("/providers/{provider_id}")
async def delete_provider(provider_id: str):
    """Remove a cloud storage provider."""
    manager = get_export_manager()

    if not manager.unregister_provider(provider_id):
        raise HTTPException(status_code=404, detail="Provider not found")

    return {"status": "deleted", "provider_id": provider_id}


@router.post("/providers/{provider_id}/validate")
async def validate_provider(provider_id: str):
    """Validate a provider's credentials."""
    manager = get_export_manager()
    provider = manager.get_provider(provider_id)

    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    try:
        is_valid = await provider.validate_credentials()
        return {
            "provider_id": provider_id,
            "valid": is_valid,
        }
    except Exception as e:
        return {
            "provider_id": provider_id,
            "valid": False,
            "error": str(e),
        }


# ============ OAuth Routes ============


@router.get("/oauth/{provider_id}/authorize", response_model=OAuthUrlResponse)
async def get_oauth_url(
    provider_id: str,
    redirect_uri: str = Query(..., description="OAuth callback URL"),
    state: Optional[str] = Query(None, description="Optional CSRF state"),
):
    """
    Get OAuth authorization URL for a provider.

    Only applicable for OAuth-based providers (google_drive, dropbox).
    """
    from ..core.cloud.base import OAuthProvider

    manager = get_export_manager()
    provider = manager.get_provider(provider_id)

    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    if not isinstance(provider, OAuthProvider):
        raise HTTPException(
            status_code=400,
            detail="Provider does not support OAuth authorization",
        )

    auth_url = provider.get_auth_url(redirect_uri, state)
    return OAuthUrlResponse(authorization_url=auth_url, state=state)


@router.post("/oauth/{provider_id}/callback")
async def oauth_callback(provider_id: str, request: OAuthCallbackRequest):
    """
    Exchange OAuth authorization code for tokens.

    Call this after user completes OAuth authorization.
    """
    from ..core.cloud.base import OAuthProvider

    manager = get_export_manager()
    provider = manager.get_provider(provider_id)

    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    if not isinstance(provider, OAuthProvider):
        raise HTTPException(
            status_code=400,
            detail="Provider does not support OAuth",
        )

    try:
        tokens = await provider.exchange_code(request.code, request.redirect_uri)
        return {
            "provider_id": provider_id,
            "authorized": True,
            "has_refresh_token": "refresh_token" in tokens,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============ Export Jobs ============


@router.post("/export", response_model=ExportResponse)
async def create_export(request: ExportRequest):
    """
    Start exporting a file to cloud storage.

    The file will be uploaded asynchronously. Use GET /cloud/export/{id}
    to check status and get the cloud URL when complete.
    """
    manager = get_export_manager()

    # Start manager if not running
    if not manager._running:
        await manager.start()

    try:
        export_job = await manager.create_export(
            file_path=request.file_path,
            provider_id=request.provider_id,
            destination_path=request.destination_path,
            job_id=request.job_id,
        )
        return ExportResponse(**export_job.to_dict())

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/export/{export_id}", response_model=ExportResponse)
async def get_export(export_id: str):
    """Get export job status."""
    manager = get_export_manager()
    export_job = manager.get_export(export_id)

    if not export_job:
        raise HTTPException(status_code=404, detail="Export job not found")

    return ExportResponse(**export_job.to_dict())


@router.get("/exports", response_model=list[ExportResponse])
async def list_exports(
    status: Optional[str] = Query(None, description="Filter by status"),
    job_id: Optional[str] = Query(None, description="Filter by related job ID"),
    limit: int = Query(50, ge=1, le=200),
):
    """List export jobs with optional filtering."""
    manager = get_export_manager()
    exports = manager.list_exports(status=status, job_id=job_id, limit=limit)
    return [ExportResponse(**e.to_dict()) for e in exports]


# ============ Provider File Operations ============


@router.get("/providers/{provider_id}/files")
async def list_provider_files(
    provider_id: str,
    path: str = Query("", description="Remote path to list"),
    limit: int = Query(100, ge=1, le=500),
):
    """List files in a cloud storage provider."""
    manager = get_export_manager()
    provider = manager.get_provider(provider_id)

    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    try:
        files = await provider.list_files(path, limit)
        return {"files": files, "path": path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/providers/{provider_id}/url")
async def get_file_url(
    provider_id: str,
    path: str = Query(..., description="Remote file path"),
    expires_in: int = Query(3600, ge=60, le=86400, description="URL expiration in seconds"),
):
    """Get a temporary download URL for a cloud file."""
    manager = get_export_manager()
    provider = manager.get_provider(provider_id)

    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    try:
        url = await provider.get_file_url(path, expires_in)
        if not url:
            raise HTTPException(status_code=404, detail="Could not generate URL")
        return {"url": url, "expires_in": expires_in}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/providers/{provider_id}/files")
async def delete_provider_file(
    provider_id: str,
    path: str = Query(..., description="Remote file path to delete"),
):
    """Delete a file from cloud storage."""
    manager = get_export_manager()
    provider = manager.get_provider(provider_id)

    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    try:
        success = await provider.delete_file(path)
        if not success:
            raise HTTPException(status_code=500, detail="Delete failed")
        return {"status": "deleted", "path": path}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
