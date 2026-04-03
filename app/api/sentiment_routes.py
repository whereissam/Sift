"""API routes for sentiment and vibe analysis."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from .auth import verify_api_key
from .ratelimit import limiter
from .schemas import (
    AnalyzeSentimentRequest,
    SentimentSegmentResponse,
    SentimentEmotions,
    TimeWindowResponse,
    EmotionalArcResponse,
    PeakMomentResponse,
    SentimentResponse,
    SentimentAvailabilityResponse,
    HeatedMomentsResponse,
    JobStatus,
)
from ..core.sentiment_analyzer import (
    SentimentAnalyzer,
    SegmentSentiment,
    TimeWindowAggregate,
    EmotionalArc,
    SentimentAnalysisResult,
)
from .transcription_store import transcription_jobs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["Sentiment"], dependencies=[Depends(verify_api_key)])

# In-memory storage for sentiment analysis results (keyed by job_id)
_sentiment_storage: dict[str, dict] = {}


def _segment_to_response(seg: SegmentSentiment) -> SentimentSegmentResponse:
    """Convert SegmentSentiment to response model."""
    return SentimentSegmentResponse(
        segment_index=seg.segment_index,
        start=seg.start,
        end=seg.end,
        text=seg.text,
        polarity=seg.polarity,
        energy=seg.energy,
        energy_score=seg.energy_score,
        excitement=seg.excitement,
        emotions=SentimentEmotions(**seg.emotions),
        heat_score=seg.heat_score,
        is_heated=seg.is_heated,
        speaker=seg.speaker,
    )


def _window_to_response(window: TimeWindowAggregate) -> TimeWindowResponse:
    """Convert TimeWindowAggregate to response model."""
    return TimeWindowResponse(
        window_index=window.window_index,
        start=window.start,
        end=window.end,
        avg_polarity=window.avg_polarity,
        avg_heat_score=window.avg_heat_score,
        dominant_emotion=window.dominant_emotion,
        segment_count=window.segment_count,
    )


def _arc_to_response(arc: EmotionalArc) -> EmotionalArcResponse:
    """Convert EmotionalArc to response model."""
    return EmotionalArcResponse(
        overall_sentiment=arc.overall_sentiment,
        avg_heat_score=arc.avg_heat_score,
        peak_moments=[
            PeakMomentResponse(
                timestamp=m["timestamp"],
                description=m["description"],
                heat_score=m["heat_score"],
            )
            for m in arc.peak_moments
        ],
        dominant_emotions=arc.dominant_emotions,
        emotional_journey=arc.emotional_journey,
        total_heated_segments=arc.total_heated_segments,
        heated_percentage=arc.heated_percentage,
    )


@router.get("/{job_id}/sentiment/available", response_model=SentimentAvailabilityResponse)
async def check_sentiment_availability(job_id: str):
    """Check if sentiment analysis is available for a job.

    Returns availability status and requirements.
    """
    job = transcription_jobs.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check if job is completed
    if job.status != JobStatus.COMPLETED:
        return SentimentAvailabilityResponse(
            available=False,
            reason=f"Job is not completed (status: {job.status.value})",
            has_transcript=False,
            has_segments=False,
            ai_available=False,
        )

    # Check for transcription
    has_transcript = bool(job.text)
    has_segments = bool(job.segments and len(job.segments) > 0)

    # Check AI availability
    ai_available = SentimentAnalyzer.is_available()

    return SentimentAvailabilityResponse(
        available=has_segments and ai_available,
        reason=None
        if (has_segments and ai_available)
        else (
            "No transcript segments available"
            if not has_segments
            else "No AI provider configured"
        ),
        has_transcript=has_transcript,
        has_segments=has_segments,
        ai_available=ai_available,
    )


@router.post("/{job_id}/analyze-sentiment", response_model=SentimentResponse)
@limiter.limit("5/minute")
async def analyze_sentiment(request: Request, job_id: str, body: AnalyzeSentimentRequest):
    """Analyze sentiment and emotional heat of a completed transcription.

    Uses AI to analyze each segment for:
    - Polarity (-1 to 1)
    - Energy level (aggressive/calm/neutral)
    - Excitement (0-100)
    - Emotions (joy, anger, fear, surprise, sadness)
    - Heat score (overall intensity 0-1)

    Results are cached for subsequent retrieval.
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

    # Convert segments to dict format
    segments = [
        {
            "start": seg.start,
            "end": seg.end,
            "text": seg.text,
            "speaker": seg.speaker,
        }
        for seg in job.segments
    ]

    # Create analyzer
    analyzer = SentimentAnalyzer.from_settings()

    if not analyzer.provider:
        raise HTTPException(
            status_code=503,
            detail="No AI provider configured. Please configure AI settings first.",
        )

    # Run analysis
    result = await analyzer.analyze_sentiment(
        segments=segments,
        job_id=job_id,
        window_size=body.window_size,
    )

    if not result.success:
        return SentimentResponse(
            success=False,
            job_id=job_id,
            segments=[],
            time_windows=[],
            emotional_arc=None,
            model=result.model,
            provider=result.provider,
            tokens_used=result.tokens_used,
            error=result.error,
        )

    # Cache results
    _sentiment_storage[job_id] = result.to_dict()

    return SentimentResponse(
        success=True,
        job_id=job_id,
        segments=[_segment_to_response(s) for s in result.segments],
        time_windows=[_window_to_response(w) for w in result.time_windows],
        emotional_arc=_arc_to_response(result.emotional_arc) if result.emotional_arc else None,
        model=result.model,
        provider=result.provider,
        tokens_used=result.tokens_used,
    )


@router.get("/{job_id}/sentiment", response_model=SentimentResponse)
async def get_sentiment(job_id: str):
    """Get cached sentiment analysis results for a job.

    Returns previously computed sentiment analysis.
    Run POST /analyze-sentiment first if no results exist.
    """
    job = transcription_jobs.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    cached = _sentiment_storage.get(job_id)
    if not cached:
        raise HTTPException(
            status_code=404,
            detail="No sentiment analysis found. Run POST /analyze-sentiment first.",
        )

    result = SentimentAnalysisResult.from_dict(cached)

    return SentimentResponse(
        success=result.success,
        job_id=result.job_id,
        segments=[_segment_to_response(s) for s in result.segments],
        time_windows=[_window_to_response(w) for w in result.time_windows],
        emotional_arc=_arc_to_response(result.emotional_arc) if result.emotional_arc else None,
        model=result.model,
        provider=result.provider,
        tokens_used=result.tokens_used,
        error=result.error,
    )


@router.get("/{job_id}/sentiment/timeline", response_model=list[TimeWindowResponse])
async def get_sentiment_timeline(job_id: str):
    """Get sentiment timeline (time windows) for a job.

    Returns aggregated sentiment data for visualization as a heatmap.
    Each window contains average polarity, heat score, and dominant emotion.
    """
    job = transcription_jobs.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    cached = _sentiment_storage.get(job_id)
    if not cached:
        raise HTTPException(
            status_code=404,
            detail="No sentiment analysis found. Run POST /analyze-sentiment first.",
        )

    result = SentimentAnalysisResult.from_dict(cached)
    return [_window_to_response(w) for w in result.time_windows]


@router.get("/{job_id}/sentiment/heated-moments", response_model=HeatedMomentsResponse)
async def get_heated_moments(job_id: str, limit: int = 10):
    """Get top heated moments from sentiment analysis.

    Returns segments with highest heat scores (>= 0.6 threshold).
    Sorted by heat score descending.
    """
    job = transcription_jobs.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    cached = _sentiment_storage.get(job_id)
    if not cached:
        raise HTTPException(
            status_code=404,
            detail="No sentiment analysis found. Run POST /analyze-sentiment first.",
        )

    result = SentimentAnalysisResult.from_dict(cached)

    # Get heated moments
    analyzer = SentimentAnalyzer()
    heated = analyzer.get_heated_moments(result.segments, limit=limit)

    return HeatedMomentsResponse(
        job_id=job_id,
        moments=[_segment_to_response(s) for s in heated],
        total_heated=len([s for s in result.segments if s.is_heated]),
    )
