"""Job management API routes (list, retry, delete, cleanup, backup, storage)."""

import logging
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from .auth import verify_api_key
from .schemas import JobStatus

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(verify_api_key)])


@router.get("/jobs")
async def list_all_jobs(
    status: Optional[str] = None,
    job_type: Optional[str] = None,
    limit: int = 50,
):
    """List all jobs with optional filtering."""
    from ..core.job_store import get_job_store, JobStatus as StoreJobStatus

    job_store = get_job_store()

    if status:
        try:
            status_enum = StoreJobStatus(status)
            jobs = job_store.get_jobs_by_status(status_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    else:
        # Get all jobs (recent first)
        with job_store._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
            jobs = [job_store._row_to_dict(row) for row in rows]

    if job_type:
        jobs = [j for j in jobs if j["job_type"] == job_type]

    return {"jobs": jobs[:limit], "total": len(jobs)}


@router.get("/jobs/resumable")
async def list_resumable_jobs():
    """List all jobs that can be resumed (failed or interrupted)."""
    from ..core.job_store import get_job_store

    job_store = get_job_store()
    jobs = job_store.get_resumable_jobs()

    return {
        "resumable_jobs": jobs,
        "total": len(jobs),
    }


@router.post("/jobs/{job_id}/retry")
async def retry_job(
    job_id: str,
    background_tasks: BackgroundTasks,
):
    """Retry a failed or interrupted job from its last successful phase."""
    from ..core.job_store import get_job_store
    from ..core.workflow import WorkflowProcessor

    job_store = get_job_store()
    job = job_store.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] == "completed":
        raise HTTPException(status_code=400, detail="Job already completed")

    # Run retry in background
    async def _retry():
        processor = WorkflowProcessor(job_store)
        await processor.retry_job(job_id)

    background_tasks.add_task(_retry)

    return {
        "status": "retrying",
        "job_id": job_id,
        "previous_status": job["status"],
    }


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    """Delete a job and its associated files."""
    from ..core.job_store import get_job_store

    job_store = get_job_store()
    job = job_store.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Delete associated files
    for path_field in ["raw_file_path", "converted_file_path"]:
        if job.get(path_field):
            path = Path(job[path_field])
            if path.exists():
                path.unlink()

    # Delete from database
    job_store.delete_job(job_id)

    return {"status": "deleted", "job_id": job_id}


@router.post("/cleanup")
async def cleanup_storage(
    max_age_hours: int = 24,
    delete_all: bool = False,
):
    """
    Clean up old checkpoints and completed jobs.

    - max_age_hours: Delete checkpoints/jobs older than this (default: 24)
    - delete_all: If true, delete ALL checkpoints (use with caution)
    """
    from ..core.job_store import get_job_store
    from ..core.checkpoint import CheckpointManager

    job_store = get_job_store()
    checkpoint_manager = CheckpointManager()

    results = {
        "checkpoints_deleted": 0,
        "jobs_deleted": 0,
    }

    # Clean up checkpoints
    if delete_all:
        results["checkpoints_deleted"] = checkpoint_manager.cleanup_all()
    else:
        results["checkpoints_deleted"] = checkpoint_manager.cleanup_old_checkpoints(max_age_hours)

    # Clean up old completed/failed jobs
    results["jobs_deleted"] = job_store.cleanup_old_jobs(days=max_age_hours // 24 or 1)

    return results


@router.post("/backup")
async def create_backup():
    """Create a backup of the jobs database."""
    from ..core.job_store import get_job_store

    job_store = get_job_store()
    backup_path = job_store.backup()

    return {
        "status": "success",
        "backup_path": str(backup_path),
        "message": "Database backup created",
    }


@router.get("/backups")
async def list_backups():
    """List available database backups."""
    from ..core.job_store import get_job_store

    job_store = get_job_store()
    backups = job_store.list_backups()

    return {
        "backups": backups,
        "total": len(backups),
    }


@router.get("/storage")
async def get_storage_info():
    """Get storage usage information."""
    from ..core.job_store import get_job_store
    from ..core.checkpoint import CheckpointManager
    from ..config import get_settings

    settings = get_settings()
    job_store = get_job_store()
    checkpoint_manager = CheckpointManager()

    download_dir = Path(settings.download_dir)

    # Calculate download directory size
    download_size = 0
    file_count = 0
    if download_dir.exists():
        for f in download_dir.rglob("*"):
            if f.is_file():
                download_size += f.stat().st_size
                file_count += 1

    # Get disk usage
    disk = shutil.disk_usage(download_dir.parent if download_dir.exists() else "/tmp")

    return {
        "download_dir": str(download_dir),
        "download_size_mb": round(download_size / (1024 * 1024), 2),
        "file_count": file_count,
        "checkpoints": checkpoint_manager.get_storage_info(),
        "jobs_in_db": len(job_store.get_jobs_by_status()),
        "disk_free_gb": round(disk.free / (1024 ** 3), 2),
    }
