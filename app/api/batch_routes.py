"""API routes for batch download operations."""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File

from .auth import verify_api_key
from .schemas import (
    BatchDownloadRequest,
    BatchResponse,
    BatchStatus,
)
from ..core.batch_manager import get_batch_manager
from ..core.queue_manager import get_queue_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/batch", tags=["batch"], dependencies=[Depends(verify_api_key)])


@router.post("/download", response_model=BatchResponse)
async def create_batch_download(
    request: BatchDownloadRequest,
    background_tasks: BackgroundTasks,
):
    """
    Create a batch download from a list of URLs.

    All URLs in the batch will be processed with the same settings.
    Progress can be tracked via the batch status endpoint.
    """
    batch_manager = get_batch_manager()

    batch_id, job_ids = batch_manager.create_batch(
        urls=request.urls,
        name=request.name,
        priority=request.priority,
        webhook_url=request.webhook_url,
        output_format=request.format.value,
        quality=request.quality.value,
    )

    # Enqueue jobs in the background
    async def enqueue_jobs():
        await batch_manager.enqueue_batch_jobs(batch_id)

    background_tasks.add_task(enqueue_jobs)

    batch = batch_manager.get_batch_status(batch_id)

    return BatchResponse(
        batch_id=batch_id,
        name=batch.get("name"),
        total_jobs=len(job_ids),
        job_ids=job_ids,
        status=batch.get("status", "pending"),
        created_at=datetime.fromisoformat(batch["created_at"]),
    )


@router.post("/upload", response_model=BatchResponse)
async def create_batch_from_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    name: Optional[str] = None,
    priority: int = 5,
    format: str = "m4a",
    quality: str = "high",
    webhook_url: Optional[str] = None,
):
    """
    Create a batch download from an uploaded file containing URLs.

    The file should contain one URL per line.
    Empty lines and lines starting with # are ignored.
    """
    # Read with size limit (10MB max for URL list files)
    MAX_BATCH_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    content = await file.read(MAX_BATCH_FILE_SIZE + 1)
    if len(content) > MAX_BATCH_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size: {MAX_BATCH_FILE_SIZE // (1024*1024)}MB",
        )
    text = content.decode("utf-8")

    # Parse URLs from file
    urls = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)

    if not urls:
        raise HTTPException(
            status_code=400,
            detail="No valid URLs found in the uploaded file",
        )

    batch_manager = get_batch_manager()

    batch_id, job_ids = batch_manager.create_batch(
        urls=urls,
        name=name or f"Uploaded batch ({len(urls)} URLs)",
        priority=priority,
        webhook_url=webhook_url,
        output_format=format,
        quality=quality,
    )

    # Enqueue jobs in the background
    async def enqueue_jobs():
        await batch_manager.enqueue_batch_jobs(batch_id)

    background_tasks.add_task(enqueue_jobs)

    batch = batch_manager.get_batch_status(batch_id)

    return BatchResponse(
        batch_id=batch_id,
        name=batch.get("name"),
        total_jobs=len(job_ids),
        job_ids=job_ids,
        status=batch.get("status", "pending"),
        created_at=datetime.fromisoformat(batch["created_at"]),
    )


@router.get("/{batch_id}", response_model=BatchStatus)
async def get_batch_status(batch_id: str):
    """Get the status of a batch."""
    batch_manager = get_batch_manager()
    batch = batch_manager.get_batch_status(batch_id)

    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    return BatchStatus(
        batch_id=batch["batch_id"],
        name=batch.get("name"),
        total_jobs=batch.get("total_jobs", 0),
        completed_jobs=batch.get("completed_jobs", 0),
        failed_jobs=batch.get("failed_jobs", 0),
        status=batch.get("status", "unknown"),
        webhook_url=batch.get("webhook_url"),
        created_at=datetime.fromisoformat(batch["created_at"]),
        updated_at=datetime.fromisoformat(batch["updated_at"]),
    )


@router.get("/{batch_id}/jobs")
async def get_batch_jobs(batch_id: str):
    """Get all jobs in a batch."""
    batch_manager = get_batch_manager()

    # Check batch exists
    batch = batch_manager.get_batch_status(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    jobs = batch_manager.get_batch_jobs(batch_id)

    return {
        "batch_id": batch_id,
        "jobs": jobs,
        "total": len(jobs),
    }


@router.delete("/{batch_id}")
async def cancel_batch(batch_id: str):
    """Cancel all pending jobs in a batch."""
    batch_manager = get_batch_manager()

    # Check batch exists
    batch = batch_manager.get_batch_status(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    cancelled = batch_manager.cancel_batch(batch_id)

    return {
        "batch_id": batch_id,
        "cancelled_jobs": cancelled,
        "message": f"Cancelled {cancelled} pending jobs",
    }


@router.get("")
async def list_batches(
    status: Optional[str] = None,
    limit: int = 50,
):
    """List all batches with optional status filter."""
    batch_manager = get_batch_manager()
    batches = batch_manager.list_batches(status=status, limit=limit)

    return {
        "batches": batches,
        "total": len(batches),
    }
