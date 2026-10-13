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


def _subtitle_style(request_preset: str | None = None):
    """Configured (or per-request) subtitle style; None disables reflow."""
    from ..config import get_settings
    from sift_core.transcribe.subtitles import SubtitleStyle, style_from_settings

    if request_preset:
        return SubtitleStyle.preset(request_preset)
    return style_from_settings(get_settings())


def _format_srt(segments: list[dict], preset: str | None = None) -> str:
    """SRT via the shared reflow writer.

    Fetched captions are the case that most needs it: YouTube auto-captions
    arrive as 2-3 word cues that flicker, and merging them is what makes the
    output readable.
    """
    from sift_core.transcribe.subtitles import format_srt, reflow_to_srt

    style = _subtitle_style(preset)
    if style is None:
        return format_srt([c for seg in segments for c in _raw_cues(seg)])
    return reflow_to_srt(segments, style)


def _format_vtt(segments: list[dict], preset: str | None = None) -> str:
    """WebVTT via the shared reflow writer."""
    from sift_core.transcribe.subtitles import format_vtt, reflow_to_vtt

    style = _subtitle_style(preset)
    if style is None:
        return format_vtt([c for seg in segments for c in _raw_cues(seg)])
    return reflow_to_vtt(segments, style)


def _raw_cues(seg: dict):
    """One cue per source segment, verbatim (`subtitle_reflow=False`)."""
    from sift_core.transcribe.subtitles import SubtitleCue

    start = float(seg.get("start", 0.0) or 0.0)
    end = float(seg.get("end", 0.0) or 0.0)
    return [
        SubtitleCue(
            start=start,
            end=max(end, start),
            lines=(str(seg.get("text", "")),),
            source_start=start,
            source_end=max(end, start),
        )
    ]


@router.get("/transcript/check")
async def check_transcript_availability(url: str):
    """
    Check if a transcript can be fetched for the given URL.

    Returns availability status, platform, and available languages (YouTube).
    """
    import re
    from sift_core.fetch.transcript_fetcher import TranscriptFetcher

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
    from sift_core.fetch.transcript_fetcher import TranscriptFetcher

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
        formatted = _format_srt(result.segments, request.subtitle_style)
    elif request.output_format == TranscriptionOutputFormat.VTT:
        formatted = _format_vtt(result.segments, request.subtitle_style)
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
