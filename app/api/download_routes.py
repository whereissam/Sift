"""Download API routes."""

import logging
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse

from .auth import verify_api_key
from .schemas import (
    DownloadRequest,
    DownloadJob,
    JobStatus,
    ContentInfo,
    Platform,
)
from ..core.downloader import DownloaderFactory
from ..core.converter import AudioConverter
from ..core.base import Platform as CorePlatform
from ..core.exceptions import ContentNotFoundError, UnsupportedPlatformError

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(verify_api_key)])

# In-memory job storage (use Redis/database for production)
jobs: Dict[str, DownloadJob] = {}


def _core_platform_to_schema(platform: CorePlatform) -> Platform:
    """Convert core Platform enum to schema Platform enum."""
    mapping = {
        CorePlatform.X_SPACES: Platform.X_SPACES,
        CorePlatform.APPLE_PODCASTS: Platform.APPLE_PODCASTS,
        CorePlatform.SPOTIFY: Platform.SPOTIFY,
        CorePlatform.YOUTUBE: Platform.YOUTUBE,
        CorePlatform.XIAOYUZHOU: Platform.XIAOYUZHOU,
        CorePlatform.DISCORD: Platform.DISCORD,
        CorePlatform.X_VIDEO: Platform.X_VIDEO,
        CorePlatform.YOUTUBE_VIDEO: Platform.YOUTUBE_VIDEO,
        CorePlatform.INSTAGRAM: Platform.INSTAGRAM,
        CorePlatform.XIAOHONGSHU: Platform.XIAOHONGSHU,
    }
    return mapping.get(platform, Platform.AUTO)


async def _process_download(job_id: str, request: DownloadRequest):
    """Background task to process a download."""
    job = jobs[job_id]
    job.status = JobStatus.PROCESSING
    job.progress = 0.1

    try:
        downloader = DownloaderFactory.get_downloader(request.url)

        result = await downloader.download(
            url=request.url,
            output_format=request.format.value,
            quality=request.quality.value,
        )

        if result.success and result.file_path:
            final_path = result.file_path

            # Move to custom output directory if specified
            output_dir = getattr(request, 'output_dir', None)
            if output_dir:
                try:
                    output_path = Path(output_dir).resolve()
                    # Prevent path traversal: must be within download_dir
                    from ..config import get_settings as _get_settings
                    _base_dir = Path(_get_settings().download_dir).resolve()
                    if not str(output_path).startswith(str(_base_dir) + "/") and output_path != _base_dir:
                        raise ValueError(f"output_dir must be within the download directory: {_base_dir}")
                    output_path.mkdir(parents=True, exist_ok=True)
                    new_path = output_path / result.file_path.name
                    shutil.move(str(result.file_path), str(new_path))
                    final_path = new_path
                    logger.info(f"[{job_id}] Moved file to {new_path}")
                except Exception as e:
                    logger.error(f"[{job_id}] Failed to move file: {e}")

            # Build content info from metadata
            if result.metadata:
                content_info = ContentInfo(
                    platform=_core_platform_to_schema(result.metadata.platform),
                    content_id=result.metadata.content_id,
                    title=result.metadata.title,
                    creator_name=result.metadata.creator_name,
                    creator_username=result.metadata.creator_username,
                    duration_seconds=int(result.metadata.duration_seconds) if result.metadata.duration_seconds else None,
                    show_name=result.metadata.show_name,
                    # Legacy fields for backward compatibility
                    host_username=result.metadata.creator_username,
                    host_display_name=result.metadata.creator_name,
                )
                job.content_info = content_info
                job.space_info = content_info  # Backward compatibility

            job.status = JobStatus.COMPLETED
            job.progress = 1.0
            job.completed_at = datetime.utcnow()

            # Store file path and size
            job._file_path = str(final_path)
            job.file_path = str(final_path)
            job.file_size_mb = round(final_path.stat().st_size / (1024 * 1024), 2)

            # Generate download URL
            job.download_url = f"/api/download/{job_id}/file"

            # Embed metadata if requested
            if request.embed_metadata and result.metadata:
                try:
                    from ..core.metadata import MetadataEmbedder
                    embedder = MetadataEmbedder()
                    await embedder.embed_metadata(final_path, result.metadata)
                    logger.info(f"[{job_id}] Metadata embedded successfully")
                except Exception as e:
                    logger.warning(f"[{job_id}] Failed to embed metadata: {e}")

            # Persist to job store
            try:
                from ..core.job_store import get_job_store, JobType
                job_store = get_job_store()
                job_store.create_job(
                    job_id=job_id,
                    job_type=JobType.DOWNLOAD,
                    source_url=request.url,
                    platform=job.platform.value if job.platform else None,
                    output_format=request.format.value,
                    quality=request.quality.value,
                    priority=request.priority,
                    batch_id=None,
                    webhook_url=request.webhook_url,
                )
                job_store.update_job(
                    job_id,
                    status="completed",
                    converted_file_path=str(final_path),
                    file_size_mb=job.file_size_mb,
                    content_info=result.metadata.__dict__ if result.metadata else None,
                )
            except Exception as e:
                logger.warning(f"[{job_id}] Failed to persist job: {e}")

            # Send webhook notification
            if request.webhook_url:
                try:
                    from ..core.webhook_notifier import get_webhook_notifier
                    notifier = get_webhook_notifier()
                    await notifier.notify_job_complete({
                        "job_id": job_id,
                        "job_type": "download",
                        "content_info": result.metadata.__dict__ if result.metadata else None,
                        "converted_file_path": str(final_path),
                        "file_size_mb": job.file_size_mb,
                        "webhook_url": request.webhook_url,
                    })
                except Exception as e:
                    logger.warning(f"[{job_id}] Webhook notification failed: {e}")

        else:
            job.status = JobStatus.FAILED
            job.error = result.error or "Download failed"

    except ContentNotFoundError as e:
        job.status = JobStatus.FAILED
        job.error = str(e)
    except UnsupportedPlatformError as e:
        job.status = JobStatus.FAILED
        job.error = str(e)
    except Exception as e:
        logger.exception(f"Download error for job {job_id}")
        job.status = JobStatus.FAILED
        error_msg = str(e) if e else "Download failed"
        job.error = error_msg if error_msg else "Download failed"


@router.post("/download", response_model=DownloadJob)
async def start_download(
    request: DownloadRequest,
    background_tasks: BackgroundTasks,
):
    """
    Start a download job for audio content.

    Supports X Spaces, Apple Podcasts, and Spotify.
    Platform is auto-detected from URL if not specified.

    Returns a job ID that can be used to check status and retrieve the file.
    """
    logger.info(f"Download request: platform={request.platform}, format={request.format}")

    # Validate URL scheme
    from urllib.parse import urlparse as _urlparse
    _parsed_url = _urlparse(request.url)
    if _parsed_url.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=400,
            detail="Invalid URL scheme. Only http and https URLs are supported.",
        )

    # Validate URL and detect platform
    detected_platform = DownloaderFactory.detect_platform(request.url)

    if not detected_platform:
        raise HTTPException(
            status_code=400,
            detail="Unsupported URL. Supported platforms: X Spaces, Apple Podcasts, Spotify, Discord",
        )

    # Create job
    job_id = str(uuid.uuid4())
    job = DownloadJob(
        job_id=job_id,
        status=JobStatus.PENDING,
        platform=_core_platform_to_schema(detected_platform),
        progress=0.0,
        created_at=datetime.utcnow(),
    )
    jobs[job_id] = job

    # Start background download
    background_tasks.add_task(_process_download, job_id, request)

    return job


@router.get("/download/{job_id}", response_model=DownloadJob)
async def get_download_status(job_id: str):
    """Get the status of a download job."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]


@router.patch("/download/{job_id}/priority")
async def update_download_priority(job_id: str, priority: int):
    """
    Update the priority of a pending download job.

    Priority levels: 1 (lowest) to 10 (highest).
    Only affects jobs that are still in the queue.
    """
    from .schemas import PriorityUpdate
    from ..core.queue_manager import get_queue_manager

    queue_manager = get_queue_manager()

    if not queue_manager:
        raise HTTPException(status_code=503, detail="Queue manager not available")

    success = await queue_manager.update_priority(job_id, priority)

    if not success:
        raise HTTPException(status_code=404, detail="Job not found or not in queue")

    return {"status": "updated", "job_id": job_id, "priority": priority}


@router.get("/queue")
async def get_queue_status():
    """Get the current queue status."""
    from ..core.queue_manager import get_queue_manager

    queue_manager = get_queue_manager()
    if not queue_manager:
        return {"pending": 0, "processing": 0, "max_concurrent": 5, "processing_jobs": [], "jobs": []}

    return queue_manager.get_queue_status()


@router.get("/download/{job_id}/file")
async def get_download_file(job_id: str):
    """Download the completed file for a job."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]

    if job.status != JobStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=f"Job not completed (status: {job.status.value})",
        )

    file_path = getattr(job, "_file_path", None)
    if not file_path or not Path(file_path).exists():
        raise HTTPException(status_code=404, detail="File not found")

    # Determine filename and media type
    path = Path(file_path)
    filename = path.name

    media_type_map = {
        ".m4a": "audio/mp4",
        ".mp3": "audio/mpeg",
        ".mp4": "video/mp4",
        ".aac": "audio/aac",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
    }
    media_type = media_type_map.get(path.suffix.lower(), "application/octet-stream")

    return FileResponse(
        path=file_path,
        filename=filename,
        media_type=media_type,
    )


@router.delete("/download/{job_id}")
async def cancel_download(job_id: str):
    """Cancel and remove a download job."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]

    # Clean up file if exists
    file_path = getattr(job, "_file_path", None)
    if file_path:
        try:
            Path(file_path).unlink(missing_ok=True)
        except Exception:
            pass

    del jobs[job_id]
    return {"status": "deleted", "job_id": job_id}


@router.get("/platforms")
async def get_platforms():
    """Get list of supported platforms and their availability."""
    from ..core.platforms import (
        XSpacesDownloader,
        ApplePodcastsDownloader,
        SpotifyDownloader,
        YouTubeDownloader,
        XiaoyuzhouDownloader,
        DiscordAudioDownloader,
        XVideoDownloader,
        YouTubeVideoDownloader,
    )

    return {
        "audio": [
            {
                "id": "x_spaces",
                "name": "X Spaces",
                "available": XSpacesDownloader.is_available(),
                "url_pattern": "x.com/i/spaces/...",
            },
            {
                "id": "apple_podcasts",
                "name": "Apple Podcasts",
                "available": ApplePodcastsDownloader.is_available(),
                "url_pattern": "podcasts.apple.com/...",
            },
            {
                "id": "spotify",
                "name": "Spotify",
                "available": SpotifyDownloader.is_available(),
                "url_pattern": "open.spotify.com/...",
            },
            {
                "id": "youtube",
                "name": "YouTube Audio",
                "available": YouTubeDownloader.is_available(),
                "url_pattern": "youtube.com/watch?v=...",
            },
            {
                "id": "xiaoyuzhou",
                "name": "小宇宙",
                "available": XiaoyuzhouDownloader.is_available(),
                "url_pattern": "xiaoyuzhoufm.com/episode/...",
            },
            {
                "id": "discord",
                "name": "Discord Audio",
                "available": DiscordAudioDownloader.is_available(),
                "url_pattern": "cdn.discordapp.com/attachments/...",
            },
        ],
        "video": [
            {
                "id": "x_video",
                "name": "X/Twitter Video",
                "available": XVideoDownloader.is_available(),
                "url_pattern": "x.com/user/status/...",
            },
            {
                "id": "youtube_video",
                "name": "YouTube Video",
                "available": YouTubeVideoDownloader.is_available(),
                "url_pattern": "youtube.com/watch?v=...",
            },
        ],
    }
