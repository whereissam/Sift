"""API routes for social media clip generation and export."""

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from .auth import verify_api_key
from .ratelimit import limiter
from .schemas import (
    GenerateClipsRequest,
    ClipSuggestionResponse,
    ClipsResponse,
    ClipUpdateRequest,
    ClipExportRequest,
    ClipExportResponse,
    SocialPlatform,
    JobStatus,
)
from ..core.clip_generator import (
    ClipGenerator,
    ClipSuggestion,
    SocialPlatform as CoreSocialPlatform,
)
from ..core.clip_exporter import ClipExporter
from .transcription_store import transcription_jobs

logger = logging.getLogger(__name__)

# Separate router for clips-related endpoints that don't have {job_id} path parameter
clips_api_router = APIRouter(prefix="/clips", tags=["Clips"], dependencies=[Depends(verify_api_key)])

# Router for job-specific clip operations
router = APIRouter(prefix="/jobs", tags=["Clips"], dependencies=[Depends(verify_api_key)])

# In-memory storage for clips (keyed by job_id)
# This is separate from transcription_jobs to avoid modifying the schema
_clips_storage: dict[str, list[dict]] = {}


@clips_api_router.get("/transcriptions")
async def list_transcription_jobs(limit: int = 50):
    """List all transcription jobs for clip generation.

    Returns jobs from the in-memory transcription store.
    """
    jobs = []
    for job_id, job in transcription_jobs.items():
        jobs.append({
            "job_id": job_id,
            "status": job.status.value if hasattr(job.status, 'value') else str(job.status),
            "text": job.text[:200] if job.text else None,
            "language": job.language,
            "duration_seconds": job.duration_seconds,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "has_segments": bool(job.segments and len(job.segments) > 0),
        })

    # Sort by created_at descending
    jobs.sort(key=lambda x: x.get("created_at") or "", reverse=True)

    return {
        "jobs": jobs[:limit],
        "total": len(jobs),
    }


def _convert_platform(platform: SocialPlatform) -> CoreSocialPlatform:
    """Convert schema platform to core platform."""
    return CoreSocialPlatform(platform.value)


def _convert_platforms(platforms: list[SocialPlatform]) -> list[CoreSocialPlatform]:
    """Convert list of schema platforms to core platforms."""
    return [_convert_platform(p) for p in platforms]


def _clip_to_response(clip: ClipSuggestion) -> ClipSuggestionResponse:
    """Convert ClipSuggestion to response model."""
    return ClipSuggestionResponse(
        clip_id=clip.clip_id,
        start_time=clip.start_time,
        end_time=clip.end_time,
        duration=clip.duration,
        transcript_text=clip.transcript_text,
        hook=clip.hook,
        caption=clip.caption,
        hashtags=clip.hashtags,
        viral_score=clip.viral_score,
        engagement_factors=clip.engagement_factors,
        compatible_platforms=[SocialPlatform(p.value) for p in clip.compatible_platforms],
        exported_files=clip.exported_files if clip.exported_files else None,
    )


@router.get("/{job_id}/clips/available")
async def check_clips_availability(job_id: str):
    """Check if clip generation is available for a job.

    Returns availability status and requirements.
    """
    job = transcription_jobs.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check if job is completed
    if job.status != JobStatus.COMPLETED:
        return {
            "available": False,
            "reason": f"Job is not completed (status: {job.status.value})",
            "has_transcript": False,
            "has_segments": False,
            "ai_available": False,
        }

    # Check for transcription
    has_transcript = bool(job.text)
    has_segments = bool(job.segments and len(job.segments) > 0)

    # Check AI availability
    ai_available = ClipGenerator.is_available()

    return {
        "available": has_segments and ai_available,
        "reason": None if (has_segments and ai_available) else (
            "No transcript segments available" if not has_segments else
            "No AI provider configured"
        ),
        "has_transcript": has_transcript,
        "has_segments": has_segments,
        "ai_available": ai_available,
    }


@router.post("/{job_id}/clips", response_model=ClipsResponse)
@limiter.limit("5/minute")
async def generate_clips(request: Request, job_id: str, body: GenerateClipsRequest):
    """Generate viral clip suggestions for a completed transcription job.

    Uses AI to analyze the transcript and identify segments with high
    viral potential for social media platforms.

    Platforms supported:
    - TikTok (max 180s)
    - Instagram Reels (max 90s)
    - YouTube Shorts (max 60s)
    - Twitter/X (max 140s)
    """
    job = transcription_jobs.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=f"Job is not completed (status: {job.status.value})",
        )

    # Get transcription segments
    if not job.segments or len(job.segments) == 0:
        raise HTTPException(
            status_code=400,
            detail="Transcription has no segments. Re-run with segment output.",
        )

    # Convert segments to dict format for clip generator
    segments = [
        {
            "start": seg.start,
            "end": seg.end,
            "text": seg.text,
            "speaker": seg.speaker,
        }
        for seg in job.segments
    ]

    # Create clip generator
    generator = ClipGenerator.from_settings()

    if not generator.provider:
        raise HTTPException(
            status_code=503,
            detail="No AI provider configured. Please configure AI settings first.",
        )

    # Generate clips
    result = await generator.generate_clips(
        segments=segments,
        job_id=job_id,
        max_clips=body.max_clips,
        target_duration=body.target_duration,
        platforms=_convert_platforms(body.platforms),
        min_viral_score=body.min_viral_score,
    )

    if not result.success:
        return ClipsResponse(
            success=False,
            job_id=job_id,
            clips=[],
            model=result.model,
            provider=result.provider,
            tokens_used=result.tokens_used,
            error=result.error,
        )

    # Save clips to in-memory storage
    clips_data = [clip.to_dict() for clip in result.clips]
    _clips_storage[job_id] = clips_data

    return ClipsResponse(
        success=True,
        job_id=job_id,
        clips=[_clip_to_response(clip) for clip in result.clips],
        model=result.model,
        provider=result.provider,
        tokens_used=result.tokens_used,
    )


@router.get("/{job_id}/clips", response_model=ClipsResponse)
async def list_clips(job_id: str):
    """List all generated clips for a job."""
    job = transcription_jobs.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    clips_data = _clips_storage.get(job_id, [])
    clips = [ClipSuggestion.from_dict(c) for c in clips_data]

    return ClipsResponse(
        success=True,
        job_id=job_id,
        clips=[_clip_to_response(clip) for clip in clips],
    )


@router.get("/{job_id}/clips/{clip_id}", response_model=ClipSuggestionResponse)
async def get_clip(job_id: str, clip_id: str):
    """Get a specific clip by ID."""
    job = transcription_jobs.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    clips_data = _clips_storage.get(job_id, [])
    for clip_data in clips_data:
        if clip_data.get("clip_id") == clip_id:
            clip = ClipSuggestion.from_dict(clip_data)
            return _clip_to_response(clip)

    raise HTTPException(status_code=404, detail="Clip not found")


@router.patch("/{job_id}/clips/{clip_id}", response_model=ClipSuggestionResponse)
async def update_clip(job_id: str, clip_id: str, request: ClipUpdateRequest):
    """Update clip boundaries or metadata.

    Allows adjusting start/end times, hook, caption, and hashtags.
    """
    job = transcription_jobs.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    clips_data = _clips_storage.get(job_id, [])
    clip_index = None
    clip_data = None

    for i, c in enumerate(clips_data):
        if c.get("clip_id") == clip_id:
            clip_index = i
            clip_data = c
            break

    if clip_data is None:
        raise HTTPException(status_code=404, detail="Clip not found")

    # Apply updates
    if request.start_time is not None:
        clip_data["start_time"] = request.start_time
    if request.end_time is not None:
        clip_data["end_time"] = request.end_time
    if request.hook is not None:
        clip_data["hook"] = request.hook
    if request.caption is not None:
        clip_data["caption"] = request.caption
    if request.hashtags is not None:
        clip_data["hashtags"] = request.hashtags

    # Recalculate duration if times changed
    if request.start_time is not None or request.end_time is not None:
        clip_data["duration"] = clip_data["end_time"] - clip_data["start_time"]

        # Recalculate compatible platforms based on new duration
        duration = clip_data["duration"]
        platform_limits = {
            "tiktok": 180,
            "reels": 90,
            "shorts": 60,
            "twitter": 140,
        }
        compatible = [p for p, limit in platform_limits.items() if duration <= limit]
        clip_data["compatible_platforms"] = compatible

    # Save updated clips
    clips_data[clip_index] = clip_data
    _clips_storage[job_id] = clips_data

    clip = ClipSuggestion.from_dict(clip_data)
    return _clip_to_response(clip)


@router.delete("/{job_id}/clips/{clip_id}")
async def delete_clip(job_id: str, clip_id: str):
    """Delete a clip."""
    job = transcription_jobs.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    clips_data = _clips_storage.get(job_id, [])
    original_count = len(clips_data)

    clips_data = [c for c in clips_data if c.get("clip_id") != clip_id]

    if len(clips_data) == original_count:
        raise HTTPException(status_code=404, detail="Clip not found")

    _clips_storage[job_id] = clips_data

    return {"success": True, "message": "Clip deleted"}


@router.post("/{job_id}/clips/{clip_id}/export", response_model=ClipExportResponse)
async def export_clip(job_id: str, clip_id: str, request: ClipExportRequest):
    """Export a clip for a specific social media platform.

    Extracts the audio segment and prepares it for the target platform.
    """
    job = transcription_jobs.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Find the clip
    clips_data = _clips_storage.get(job_id, [])
    clip_data = None
    clip_index = None

    for i, c in enumerate(clips_data):
        if c.get("clip_id") == clip_id:
            clip_data = c
            clip_index = i
            break

    if clip_data is None:
        raise HTTPException(status_code=404, detail="Clip not found")

    # Get source audio file from the transcription job
    audio_path = job.audio_file
    if not audio_path:
        raise HTTPException(
            status_code=400,
            detail="No audio file available. Re-transcribe with 'Keep Audio' enabled to export clips.",
        )

    if not Path(audio_path).exists():
        raise HTTPException(
            status_code=400,
            detail=f"Audio file not found: {audio_path}",
        )

    # Check FFmpeg availability
    if not ClipExporter.is_ffmpeg_available():
        raise HTTPException(
            status_code=503,
            detail="FFmpeg not available. Please install it.",
        )

    # Export the clip
    exporter = ClipExporter()
    result = await exporter.export_clip(
        audio_path=audio_path,
        clip_id=clip_id,
        start_time=clip_data["start_time"],
        end_time=clip_data["end_time"],
        platform=_convert_platform(request.platform),
        output_format=request.format.value,
        quality=request.quality.value,
    )

    if not result.success:
        return ClipExportResponse(
            success=False,
            clip_id=clip_id,
            platform=request.platform,
            error=result.error,
        )

    # Save exported file path to clip
    if "exported_files" not in clip_data:
        clip_data["exported_files"] = {}
    clip_data["exported_files"][request.platform.value] = result.file_path

    clips_data[clip_index] = clip_data
    _clips_storage[job_id] = clips_data

    return ClipExportResponse(
        success=True,
        clip_id=clip_id,
        platform=request.platform,
        file_path=result.file_path,
        file_size_mb=result.file_size_mb,
        duration=result.duration,
        format=result.format,
    )


@router.get("/{job_id}/clips/{clip_id}/download/{platform}")
async def download_clip(job_id: str, clip_id: str, platform: str):
    """Download an exported clip file.

    The clip must have been previously exported for the specified platform.
    """
    job = transcription_jobs.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Find the clip
    clips_data = _clips_storage.get(job_id, [])
    clip_data = None

    for c in clips_data:
        if c.get("clip_id") == clip_id:
            clip_data = c
            break

    if clip_data is None:
        raise HTTPException(status_code=404, detail="Clip not found")

    # Get exported file
    exported_files = clip_data.get("exported_files", {})
    file_path = exported_files.get(platform)

    if not file_path:
        raise HTTPException(
            status_code=404,
            detail=f"Clip not exported for platform: {platform}",
        )

    if not Path(file_path).exists():
        raise HTTPException(
            status_code=404,
            detail="Exported file not found",
        )

    # Return file
    return FileResponse(
        path=file_path,
        filename=Path(file_path).name,
        media_type="audio/mpeg",
    )
