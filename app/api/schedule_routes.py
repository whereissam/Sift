"""API routes for scheduled downloads."""

import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from .auth import verify_api_key
from .schemas import (
    ScheduleDownloadRequest,
    ScheduledJob,
)
from ..store import get_job_store, JobType, JobStatus
from sift_core.fetch.downloader import DownloaderFactory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/schedule", tags=["schedule"], dependencies=[Depends(verify_api_key)])


@router.post("/download", response_model=ScheduledJob)
async def schedule_download(request: ScheduleDownloadRequest):
    """
    Schedule a download for a specific time.

    The download will automatically start when the scheduled time arrives.
    """
    # Validate URL
    detected_platform = DownloaderFactory.detect_platform(request.url)
    if not detected_platform:
        raise HTTPException(
            status_code=400,
            detail="Unsupported URL. Supported platforms: X Spaces, YouTube, Apple Podcasts, Spotify",
        )

    # Validate scheduled time is in the future
    now = datetime.utcnow()
    scheduled_at = request.scheduled_at
    if scheduled_at.tzinfo is None:
        # Assume UTC if no timezone
        pass
    else:
        # Convert to UTC
        scheduled_at = scheduled_at.replace(tzinfo=None)

    if scheduled_at <= now:
        raise HTTPException(
            status_code=400,
            detail="Scheduled time must be in the future",
        )

    job_store = get_job_store()
    job_id = str(uuid.uuid4())

    # Create scheduled job
    job_store.create_job(
        job_id=job_id,
        job_type=JobType.DOWNLOAD,
        source_url=request.url,
        platform=detected_platform.value,
        output_format=request.format.value,
        quality=request.quality.value,
        priority=request.priority,
        scheduled_at=scheduled_at.isoformat(),
        webhook_url=request.webhook_url,
    )

    job = job_store.get_job(job_id)

    return ScheduledJob(
        job_id=job_id,
        url=request.url,
        scheduled_at=scheduled_at,
        priority=request.priority,
        status=job["status"],
        created_at=datetime.fromisoformat(job["created_at"]),
    )


@router.get("")
async def list_scheduled_jobs(limit: int = 50):
    """List all scheduled jobs that haven't started yet."""
    job_store = get_job_store()

    with job_store._get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM jobs
            WHERE status = ? AND scheduled_at IS NOT NULL
            ORDER BY scheduled_at ASC
            LIMIT ?
        """, (JobStatus.PENDING.value, limit)).fetchall()

        jobs = [job_store._row_to_dict(row) for row in rows]

    scheduled = []
    for job in jobs:
        scheduled.append({
            "job_id": job["job_id"],
            "url": job["source_url"],
            "scheduled_at": job["scheduled_at"],
            "priority": job.get("priority", 5),
            "status": job["status"],
            "created_at": job["created_at"],
        })

    return {
        "scheduled_jobs": scheduled,
        "total": len(scheduled),
    }


@router.delete("/{job_id}")
async def cancel_scheduled_job(job_id: str):
    """Cancel a scheduled job."""
    job_store = get_job_store()
    job = job_store.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != JobStatus.PENDING.value:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel job with status: {job['status']}",
        )

    if not job.get("scheduled_at"):
        raise HTTPException(
            status_code=400,
            detail="Job is not a scheduled job",
        )

    # Delete the job
    job_store.delete_job(job_id)

    return {
        "job_id": job_id,
        "status": "cancelled",
        "message": "Scheduled job cancelled",
    }


@router.patch("/{job_id}")
async def update_scheduled_job(
    job_id: str,
    scheduled_at: Optional[datetime] = None,
    priority: Optional[int] = None,
):
    """Update a scheduled job's time or priority."""
    job_store = get_job_store()
    job = job_store.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != JobStatus.PENDING.value:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot update job with status: {job['status']}",
        )

    if not job.get("scheduled_at"):
        raise HTTPException(
            status_code=400,
            detail="Job is not a scheduled job",
        )

    updates = {}

    if scheduled_at is not None:
        now = datetime.utcnow()
        if scheduled_at.tzinfo:
            scheduled_at = scheduled_at.replace(tzinfo=None)

        if scheduled_at <= now:
            raise HTTPException(
                status_code=400,
                detail="Scheduled time must be in the future",
            )
        updates["scheduled_at"] = scheduled_at.isoformat()

    if priority is not None:
        if priority < 1 or priority > 10:
            raise HTTPException(
                status_code=400,
                detail="Priority must be between 1 and 10",
            )
        updates["priority"] = priority

    if updates:
        job = job_store.update_job(job_id, **updates)

    return {
        "job_id": job_id,
        "scheduled_at": job.get("scheduled_at"),
        "priority": job.get("priority", 5),
        "status": "updated",
    }
