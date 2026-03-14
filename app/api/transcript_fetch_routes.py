"""Transcript fetch API routes (YouTube/Spotify existing transcripts)."""

import json
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from .auth import verify_api_key
from .schemas import (
    JobStatus,
    TranscriptionJob,
    TranscriptionSegment as TranscriptionSegmentSchema,
    TranscriptionOutputFormat,
    FetchTranscriptRequest,
)
from .transcription_store import transcription_jobs

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(verify_api_key)])


def _format_srt(segments: list[dict]) -> str:
    """Format segments as SRT subtitle format."""
    lines = []
    for i, seg in enumerate(segments, 1):
        start = seg["start"]
        end = seg["end"]
        text = seg["text"]
        start_h, start_r = divmod(start, 3600)
        start_m, start_s = divmod(start_r, 60)
        end_h, end_r = divmod(end, 3600)
        end_m, end_s = divmod(end_r, 60)
        lines.append(str(i))
        lines.append(
            f"{int(start_h):02d}:{int(start_m):02d}:{start_s:06.3f}".replace(".", ",")
            + " --> "
            + f"{int(end_h):02d}:{int(end_m):02d}:{end_s:06.3f}".replace(".", ",")
        )
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def _format_vtt(segments: list[dict]) -> str:
    """Format segments as WebVTT subtitle format."""
    lines = ["WEBVTT", ""]
    for seg in segments:
        start = seg["start"]
        end = seg["end"]
        text = seg["text"]
        start_h, start_r = divmod(start, 3600)
        start_m, start_s = divmod(start_r, 60)
        end_h, end_r = divmod(end, 3600)
        end_m, end_s = divmod(end_r, 60)
        lines.append(
            f"{int(start_h):02d}:{int(start_m):02d}:{start_s:06.3f}"
            + " --> "
            + f"{int(end_h):02d}:{int(end_m):02d}:{end_s:06.3f}"
        )
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


@router.get("/transcript/check")
async def check_transcript_availability(url: str):
    """
    Check if a transcript can be fetched for the given URL.

    Returns availability status, platform, and available languages (YouTube).
    """
    import re
    from ..core.transcript_fetcher import TranscriptFetcher

    fetcher = TranscriptFetcher()

    if not fetcher.can_fetch_transcript(url):
        return {"available": False, "platform": None, "languages": []}

    # Determine platform
    if re.search(r"(youtube\.com|youtu\.be)", url):
        platform = "youtube"
    elif re.search(r"open\.spotify\.com/episode/", url):
        platform = "spotify"
    else:
        platform = None

    # List available languages (YouTube only)
    languages = []
    if platform == "youtube":
        try:
            languages = await fetcher.list_available_languages(url)
        except Exception:
            pass

    available = platform == "spotify" or len(languages) > 0

    return {
        "available": available,
        "platform": platform,
        "languages": languages,
    }


@router.post("/transcript/fetch", response_model=TranscriptionJob)
async def fetch_transcript(request: FetchTranscriptRequest):
    """
    Fetch an existing transcript from YouTube or Spotify.

    Returns a completed TranscriptionJob immediately (no background task needed).
    """
    from ..core.transcript_fetcher import TranscriptFetcher

    fetcher = TranscriptFetcher()

    if not fetcher.can_fetch_transcript(request.url):
        raise HTTPException(
            status_code=400,
            detail="URL does not support transcript fetching. Use Whisper transcription instead.",
        )

    result = await fetcher.fetch_transcript(request.url, request.language)

    if not result.success:
        raise HTTPException(status_code=422, detail=result.error or "Failed to fetch transcript")

    # Build segments
    segments = [
        TranscriptionSegmentSchema(start=s["start"], end=s["end"], text=s["text"])
        for s in result.segments
    ]

    # Format output
    if request.output_format == TranscriptionOutputFormat.SRT:
        formatted = _format_srt(result.segments)
    elif request.output_format == TranscriptionOutputFormat.VTT:
        formatted = _format_vtt(result.segments)
    elif request.output_format == TranscriptionOutputFormat.JSON:
        formatted = json.dumps(
            {
                "text": result.text,
                "language": result.language,
                "source": result.source,
                "segments": result.segments,
            },
            ensure_ascii=False,
            indent=2,
        )
    else:
        formatted = result.text

    # Create a completed transcription job
    job_id = str(uuid.uuid4())
    job = TranscriptionJob(
        job_id=job_id,
        status=JobStatus.COMPLETED,
        progress=1.0,
        text=result.text,
        segments=segments,
        language=result.language or None,
        duration_seconds=result.duration_seconds,
        formatted_output=formatted,
        output_format=request.output_format,
        source_url=request.url,
        created_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
    )
    transcription_jobs[job_id] = job

    return job
