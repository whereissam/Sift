"""API routes for Obsidian integration."""

import logging
from fastapi import APIRouter, Depends, HTTPException

from .auth import verify_api_key
from .schemas import (
    ObsidianSettingsRequest,
    ObsidianSettingsResponse,
    ObsidianExportRequest,
    ObsidianExportResponse,
    ObsidianValidateResponse,
)
from ..core.job_store import get_job_store
from ..core.obsidian_exporter import ObsidianExporter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/obsidian", tags=["Obsidian"], dependencies=[Depends(verify_api_key)])


@router.get("/settings", response_model=ObsidianSettingsResponse)
async def get_obsidian_settings() -> ObsidianSettingsResponse:
    """Get current Obsidian settings."""
    store = get_job_store()
    settings = store.get_obsidian_settings()

    if settings:
        return ObsidianSettingsResponse(
            vault_path=settings["vault_path"],
            subfolder=settings.get("subfolder", "Sift"),
            template=settings.get("template"),
            default_tags=settings.get("default_tags", ["sift", "transcript"]),
            is_configured=True,
        )

    return ObsidianSettingsResponse(
        vault_path="",
        subfolder="Sift",
        template=None,
        default_tags=["sift", "transcript"],
        is_configured=False,
    )


@router.post("/settings", response_model=ObsidianSettingsResponse)
async def save_obsidian_settings(
    request: ObsidianSettingsRequest,
) -> ObsidianSettingsResponse:
    """Save Obsidian settings."""
    # Validate the vault path first
    exporter = ObsidianExporter(request.vault_path)
    is_valid, error = exporter.validate_vault()

    if not is_valid:
        raise HTTPException(status_code=400, detail=error)

    store = get_job_store()
    settings = store.save_obsidian_settings(
        vault_path=request.vault_path,
        subfolder=request.subfolder,
        template=request.template,
        default_tags=request.default_tags,
    )

    return ObsidianSettingsResponse(
        vault_path=settings["vault_path"],
        subfolder=settings.get("subfolder", "Sift"),
        template=settings.get("template"),
        default_tags=settings.get("default_tags", ["sift", "transcript"]),
        is_configured=True,
    )


@router.post("/validate", response_model=ObsidianValidateResponse)
async def validate_vault(vault_path: str) -> ObsidianValidateResponse:
    """Validate that a vault path is accessible and writable."""
    exporter = ObsidianExporter(vault_path)
    is_valid, error = exporter.validate_vault()

    return ObsidianValidateResponse(valid=is_valid, error=error)


@router.post("/export", response_model=ObsidianExportResponse)
async def export_to_obsidian(request: ObsidianExportRequest) -> ObsidianExportResponse:
    """Export a transcription to Obsidian vault."""
    store = get_job_store()

    # Check Obsidian settings
    settings = store.get_obsidian_settings()
    if not settings:
        raise HTTPException(
            status_code=400,
            detail="Obsidian not configured. Please set up your vault path in Settings.",
        )

    # Get the transcription job
    job = store.get_job(request.job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {request.job_id} not found")

    # Check if job has transcription result
    transcription_result = job.get("transcription_result")
    if not transcription_result:
        raise HTTPException(
            status_code=400,
            detail="Job does not have a transcription result",
        )

    # Extract transcript text
    transcript = transcription_result.get("formatted_output") or transcription_result.get("text")
    if not transcript:
        raise HTTPException(
            status_code=400,
            detail="Transcription has no text content",
        )

    # Determine title
    content_info = job.get("content_info", {})
    title = request.title
    if not title:
        title = content_info.get("title") if content_info else None
    if not title:
        title = f"Transcription {request.job_id[:8]}"

    # Merge tags
    default_tags = settings.get("default_tags", ["sift", "transcript"])
    tags = list(set(default_tags + (request.tags or [])))

    # Determine subfolder
    subfolder = request.subfolder or settings.get("subfolder", "Sift")

    # Export
    exporter = ObsidianExporter(settings["vault_path"])
    result = await exporter.export_transcription(
        job_id=request.job_id,
        transcript=transcript,
        title=title,
        source_url=job.get("source_url"),
        duration_seconds=transcription_result.get("duration_seconds"),
        language=transcription_result.get("language"),
        tags=tags,
        subfolder=subfolder,
        created_at=job.get("created_at"),
    )

    if not result.success:
        raise HTTPException(status_code=500, detail=result.error)

    return ObsidianExportResponse(
        success=True,
        file_path=result.file_path,
        note_name=result.note_name,
    )
