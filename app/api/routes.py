"""Core API routes (health, readiness, quick-add)."""

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from .auth import verify_api_key
from .schemas import (
    DownloadRequest,
    DownloadJob,
    JobStatus,
    HealthResponse,
    TranscriptionJob,
    TranscriptionOutputFormat,
)
from ..core.downloader import DownloaderFactory
from ..core.converter import AudioConverter

logger = logging.getLogger(__name__)

# Apply optional API key auth to all routes
router = APIRouter(dependencies=[Depends(verify_api_key)])


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint (liveness probe)."""
    from ..core.platforms import (
        XSpacesDownloader,
        ApplePodcastsDownloader,
        SpotifyDownloader,
        YouTubeDownloader,
        XiaoyuzhouDownloader,
        DiscordAudioDownloader,
        XVideoDownloader,
        YouTubeVideoDownloader,
        InstagramVideoDownloader,
        XiaohongshuVideoDownloader,
    )
    from ..core.transcriber import AudioTranscriber
    from ..core.diarizer import SpeakerDiarizer
    from ..core.summarizer import TranscriptSummarizer
    from ..core.enhancer import AudioEnhancer

    return HealthResponse(
        status="healthy",
        platforms={
            "x_spaces": XSpacesDownloader.is_available(),
            "apple_podcasts": ApplePodcastsDownloader.is_available(),
            "spotify": SpotifyDownloader.is_available(),
            "youtube": YouTubeDownloader.is_available(),
            "xiaoyuzhou": XiaoyuzhouDownloader.is_available(),
            "discord": DiscordAudioDownloader.is_available(),
            "x_video": XVideoDownloader.is_available(),
            "youtube_video": YouTubeVideoDownloader.is_available(),
            "instagram": InstagramVideoDownloader.is_available(),
            "xiaohongshu": XiaohongshuVideoDownloader.is_available(),
        },
        ffmpeg_available=AudioConverter.is_ffmpeg_available(),
        whisper_available=AudioTranscriber.is_available(),
        diarization_available=SpeakerDiarizer.is_available(),
        summarization_available=TranscriptSummarizer.is_available(),
        enhancement_available=AudioEnhancer.is_available(),
        version="0.3.0",
    )


@router.get("/readyz")
async def readiness_check():
    """
    Readiness probe - checks if the service is ready to accept traffic.

    Verifies:
    - Database connection is working
    - Download directory is writable
    """
    from ..core.job_store import get_job_store
    from ..config import get_settings
    from pathlib import Path

    errors = []

    # Check database connection
    try:
        job_store = get_job_store()
        # Try a simple query
        job_store.get_jobs_by_status()
    except Exception as e:
        errors.append(f"Database: {str(e)}")

    # Check download directory is writable
    try:
        settings = get_settings()
        download_dir = Path(settings.download_dir)
        download_dir.mkdir(parents=True, exist_ok=True)
        test_file = download_dir / ".write_test"
        test_file.write_text("test")
        test_file.unlink()
    except Exception as e:
        errors.append(f"Download directory: {str(e)}")

    if errors:
        raise HTTPException(
            status_code=503,
            detail={"status": "not ready", "errors": errors},
        )

    return {"status": "ready"}


@router.get("/add")
async def quick_add(
    url: str,
    action: str = "transcribe",
    background_tasks: BackgroundTasks = None,
):
    """
    Quick add endpoint for browser extension and bookmarklet.

    Accepts a URL and action (transcribe or download) via query parameters.
    Starts the appropriate job and returns the job ID.

    Example: /api/add?url=https://youtube.com/watch?v=abc&action=transcribe
    """
    from fastapi import BackgroundTasks as BT
    from .download_routes import jobs, _process_download, _core_platform_to_schema
    from .transcription_routes import _process_transcription
    from .transcription_store import transcription_jobs

    if background_tasks is None:
        background_tasks = BT()

    # Detect platform from URL
    detected_platform = DownloaderFactory.detect_platform(url)

    if not detected_platform:
        raise HTTPException(
            status_code=400,
            detail="Unsupported URL. Supported: X Spaces, YouTube, Apple Podcasts, Spotify, Discord, 小宇宙",
        )

    job_id = str(uuid.uuid4())

    if action == "download":
        # Create download job
        job = DownloadJob(
            job_id=job_id,
            status=JobStatus.PENDING,
            platform=_core_platform_to_schema(detected_platform),
            progress=0.0,
            created_at=datetime.utcnow(),
        )
        jobs[job_id] = job

        # Create download request
        request = DownloadRequest(url=url)
        background_tasks.add_task(_process_download, job_id, request)

        return {
            "job_id": job_id,
            "action": "download",
            "status": "pending",
            "message": f"Download started for {detected_platform.value}",
        }
    else:
        # Create transcription job (default action)
        job = TranscriptionJob(
            job_id=job_id,
            status=JobStatus.PENDING,
            progress=0.0,
            source_url=url,
            created_at=datetime.utcnow(),
        )
        transcription_jobs[job_id] = job

        # Create transcribe request with defaults
        from .schemas import WhisperModelSize

        class QuickTranscribeRequest:
            def __init__(self):
                self.url = url
                self.model = WhisperModelSize.BASE
                self.output_format = TranscriptionOutputFormat.TEXT
                self.language = None
                self.translate = False
                self.diarize = False
                self.num_speakers = None

        request = QuickTranscribeRequest()
        background_tasks.add_task(_process_transcription, job_id, request, None)

        return {
            "job_id": job_id,
            "action": "transcribe",
            "status": "pending",
            "message": f"Transcription started for {detected_platform.value}",
        }
