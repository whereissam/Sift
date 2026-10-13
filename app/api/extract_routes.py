"""API routes for structured data extraction."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from .auth import verify_api_key
from ..knowledge.knowledge_budget import record_llm_spend
from .ratelimit import limiter
from .schemas import (
    ExtractRequest,
    ExtractedFieldResponse,
    ExtractionResponse,
    ExtractionAvailabilityResponse,
    ExtractionPresetInfo,
    JobStatus,
)
from ..knowledge.extractor import (
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

    custom_schema = body.custom_schema
    if body.schema_id:
        # P17: run a saved schema as the CUSTOM preset.
        from ..store import get_job_store

        saved = get_job_store().get_extraction_schema(body.schema_id)
        if not saved:
            raise HTTPException(
                status_code=404,
                detail=f"Extraction schema '{body.schema_id}' not found",
            )
        preset = ExtractionPreset.CUSTOM
        custom_schema = {"fields": saved["fields"]}
    elif body.preset:
        try:
            preset = ExtractionPreset(body.preset.value)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown preset: {body.preset}")
    else:
        raise HTTPException(
            status_code=400, detail="Provide either `preset` or `schema_id`."
        )

    result = await extractor.extract(
        transcript=job.text,
        job_id=job_id,
        preset=preset,
        custom_schema=custom_schema,
    )
    record_llm_spend(result)

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


@router.get("/{job_id}/extract/export")
async def export_extraction(job_id: str, format: str = "json"):
    """Export the cached extraction as json, markdown, or csv (P17).

    Deterministic rendering of the stored result — no LLM call. 404 when no
    extraction has been run for the job yet.
    """
    from fastapi.responses import Response

    from ..knowledge.extractor import (
        render_extraction_csv,
        render_extraction_markdown,
    )

    cached = _extraction_storage.get(job_id)
    if not cached:
        raise HTTPException(
            status_code=404,
            detail=f"No cached extraction for job {job_id}. "
            "Run POST /jobs/{id}/extract first.",
        )
    result = ExtractionResult.from_dict(cached)

    if format == "json":
        return cached
    if format == "markdown":
        return Response(
            content=render_extraction_markdown(result),
            media_type="text/markdown; charset=utf-8",
        )
    if format == "csv":
        return Response(
            content=render_extraction_csv(result),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="extraction_{job_id}.csv"'
            },
        )
    raise HTTPException(
        status_code=400,
        detail=f"Unknown format '{format}'. Valid: json, markdown, csv.",
    )


# This route has a unique prefix so it doesn't conflict with job_id routes
presets_router = APIRouter(prefix="/extract", tags=["Extraction"], dependencies=[Depends(verify_api_key)])


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


# ===== P17: named, reusable custom extraction schemas =====

schemas_router = APIRouter(
    prefix="/extraction-schemas",
    tags=["Extraction"],
    dependencies=[Depends(verify_api_key)],
)


from pydantic import BaseModel, Field as _Field  # noqa: E402


class SchemaFieldDef(BaseModel):
    name: str = _Field(min_length=1)
    type: str = "string"
    description: str = ""


class CreateSchemaRequest(BaseModel):
    name: str = _Field(min_length=1, max_length=100)
    description: str | None = None
    fields: list[SchemaFieldDef] = _Field(min_length=1)


class SchemaResponse(BaseModel):
    schema_id: str
    name: str
    description: str | None = None
    fields: list[SchemaFieldDef]
    created_at: str


@schemas_router.post("", response_model=SchemaResponse)
async def create_extraction_schema(body: CreateSchemaRequest):
    """Save a named custom extraction schema for reuse via `schema_id`."""
    from ..store import get_job_store

    try:
        row = get_job_store().create_extraction_schema(
            name=body.name,
            description=body.description,
            fields=[f.model_dump() for f in body.fields],
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return SchemaResponse(**row)


@schemas_router.get("", response_model=list[SchemaResponse])
async def list_extraction_schemas():
    """List saved extraction schemas, newest first."""
    from ..store import get_job_store

    return [SchemaResponse(**r) for r in get_job_store().list_extraction_schemas()]


@schemas_router.get("/{id_or_name}", response_model=SchemaResponse)
async def get_extraction_schema(id_or_name: str):
    """Fetch one saved schema by id or name."""
    from ..store import get_job_store

    row = get_job_store().get_extraction_schema(id_or_name)
    if not row:
        raise HTTPException(
            status_code=404, detail=f"Extraction schema '{id_or_name}' not found"
        )
    return SchemaResponse(**row)


@schemas_router.delete("/{id_or_name}")
async def delete_extraction_schema(id_or_name: str):
    """Delete a saved schema by id or name."""
    from ..store import get_job_store

    if not get_job_store().delete_extraction_schema(id_or_name):
        raise HTTPException(
            status_code=404, detail=f"Extraction schema '{id_or_name}' not found"
        )
    return {"deleted": id_or_name}
