"""Storage management API routes."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import verify_api_key
from ..core.storage_manager import get_storage_manager

router = APIRouter(prefix="/storage", tags=["storage"], dependencies=[Depends(verify_api_key)])


class StorageStatsResponse(BaseModel):
    """Storage statistics response."""

    total_gb: float
    used_gb: float
    free_gb: float
    download_dir_gb: float
    download_file_count: int
    usage_percent: float


class CleanupRequest(BaseModel):
    """Manual cleanup request."""

    max_age_hours: Optional[float] = None
    max_size_gb: Optional[float] = None
    min_free_gb: Optional[float] = None


class CleanupResponse(BaseModel):
    """Cleanup result response."""

    files_deleted: int
    bytes_freed: int
    mb_freed: float
    gb_freed: float
    errors: list[str]


class PoliciesResponse(BaseModel):
    """Cleanup policies response."""

    cleanup_after_hours: Optional[int]
    max_storage_gb: Optional[float]
    min_free_space_gb: Optional[float]
    cleanup_interval_seconds: int
    cleanup_enabled: bool


@router.get("/stats", response_model=StorageStatsResponse)
async def get_storage_stats():
    """
    Get current storage statistics.

    Returns disk usage information and download directory statistics.
    """
    manager = get_storage_manager()
    stats = manager.get_stats()
    return StorageStatsResponse(**stats.to_dict())


@router.post("/cleanup", response_model=CleanupResponse)
async def run_cleanup(request: CleanupRequest):
    """
    Run manual cleanup with specified policies.

    If no policies are specified, uses the default policies from configuration.
    """
    manager = get_storage_manager()

    # Use request values or fall back to config
    max_age = request.max_age_hours
    max_size = request.max_size_gb
    min_free = request.min_free_gb

    # If nothing specified, use default age cleanup
    if max_age is None and max_size is None and min_free is None:
        from ..config import get_settings
        settings = get_settings()
        max_age = float(settings.cleanup_after_hours) if settings.cleanup_after_hours else 24.0

    result = await manager.run_cleanup(
        max_age_hours=max_age,
        max_size_gb=max_size,
        min_free_gb=min_free,
    )

    return CleanupResponse(**result.to_dict())


@router.get("/policies", response_model=PoliciesResponse)
async def get_policies():
    """
    Get current cleanup policies from configuration.

    Returns the configured cleanup thresholds and intervals.
    """
    manager = get_storage_manager()
    policies = manager.get_policies()
    return PoliciesResponse(**policies)


@router.get("/files")
async def list_files(
    min_age_hours: float = 0,
    limit: int = 100,
):
    """
    List files in download directory sorted by age.

    Args:
        min_age_hours: Only show files older than this
        limit: Maximum number of files to return
    """
    manager = get_storage_manager()
    files = manager.get_files_by_age(min_age_hours=min_age_hours)[:limit]

    return {
        "files": [
            {
                "name": path.name,
                "path": str(path),
                "age_hours": round(age, 2),
                "size_mb": round(size / (1024**2), 2),
            }
            for path, age, size in files
        ],
        "total_count": len(files),
    }
