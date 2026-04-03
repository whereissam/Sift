"""API routes for structured data extraction."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from .auth import verify_api_key
from .ratelimit import limiter
from .schemas import (
    ExtractRequest,
    ExtractedFieldResponse,
    ExtractionResponse,
    ExtractionAvailabilityResponse,
    ExtractionPresetInfo,
    JobStatus,
)
from ..core.extractor import (
    StructuredExtractor,
    ExtractionPreset,
    ExtractionResult,
    PRESET_INFO,
)
from .transcription_store import transcription_jobs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["Extraction"], dependencies=[Depends(verify_api_key)])

# In-memory storage for extraction results (keyed by job_id)
_extraction_storage: dict[str, dict] = {}


@router.get("/{job_id}/extract/available", response_model=ExtractionAvailabilityResponse)
async def check_extraction_availability(job_id: str):
    """Check if structured extraction is available for a job."""
    job = transcription_jobs.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.COMPLETED:
        return ExtractionAvailabilityResponse(
            available=False,
            reason=f"Job is not completed (status: {job.status.value})",
            has_transcript=False,
            ai_available=False,
        )

    has_transcript = bool(job.text)
    ai_available = StructuredExtractor.is_available()

    return ExtractionAvailabilityResponse(
        available=has_transcript and ai_available,
        reason=None
        if (has_transcript and ai_available)
        else (
            "No transcript text available"
            if not has_transcript
            else "No AI provider configured"
        ),
        has_transcript=has_transcript,
        ai_available=ai_available,
    )


@router.post("/{job_id}/extract", response_model=ExtractionResponse)
@limiter.limit("5/minute")
async def extract_structured_data(request: Request, job_id: str, body: ExtractRequest):
    """Extract structured data from a completed transcription.

    Uses AI to extract machine-readable data based on the selected preset.
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

    if not job.text:
        raise HTTPException(
            status_code=400,
            detail="Transcription has no text content.",
        )

    extractor = StructuredExtractor.from_settings()

    if not extractor.provider:
        raise HTTPException(
            status_code=503,
            detail="No AI provider configured. Please configure AI settings first.",
        )

    try:
        preset = ExtractionPreset(body.preset.value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown preset: {body.preset}")

    result = await extractor.extract(
        transcript=job.text,
        job_id=job_id,
        preset=preset,
        custom_schema=body.custom_schema,
    )

    if not result.success:
        return ExtractionResponse(
            success=False,
            job_id=job_id,
            preset=result.preset,
            fields=[],
            raw_output=None,
            model=result.model,
            provider=result.provider,
            tokens_used=result.tokens_used,
            error=result.error,
        )

    # Cache results
    _extraction_storage[job_id] = result.to_dict()

    return ExtractionResponse(
        success=True,
        job_id=job_id,
        preset=result.preset,
        fields=[
            ExtractedFieldResponse(key=f.key, value=f.value, field_type=f.field_type)
            for f in result.fields
        ],
        raw_output=result.raw_output,
        model=result.model,
        provider=result.provider,
        tokens_used=result.tokens_used,
    )


@router.get("/{job_id}/extract", response_model=ExtractionResponse)
async def get_extraction(job_id: str):
    """Get cached extraction results for a job.

    Returns previously computed extraction.
    Run POST /{job_id}/extract first if no results exist.
    """
    job = transcription_jobs.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    cached = _extraction_storage.get(job_id)
    if not cached:
        return ExtractionResponse(
            success=False,
            job_id=job_id,
        )

    result = ExtractionResult.from_dict(cached)

    return ExtractionResponse(
        success=result.success,
        job_id=result.job_id,
        preset=result.preset,
        fields=[
            ExtractedFieldResponse(key=f.key, value=f.value, field_type=f.field_type)
            for f in result.fields
        ],
        raw_output=result.raw_output,
        model=result.model,
        provider=result.provider,
        tokens_used=result.tokens_used,
        error=result.error,
    )


# This route has a unique prefix so it doesn't conflict with job_id routes
presets_router = APIRouter(prefix="/extract", tags=["Extraction"])


@presets_router.get("/presets", response_model=list[ExtractionPresetInfo])
async def get_extraction_presets():
    """Get list of available extraction presets with descriptions."""
    presets = []
    for preset, info in PRESET_INFO.items():
        presets.append(
            ExtractionPresetInfo(
                name=info["name"],
                value=preset.value,
                description=info["description"],
                example_fields=info["example_fields"],
            )
        )
    return presets
