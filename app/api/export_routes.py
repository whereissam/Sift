"""P21: vault / note-app export routes.

Render an episode (transcript + P18 knowledge) into a templated markdown note
for Obsidian / Logseq / plain markdown, and either write it into a configured
vault or return the rendered content for preview (used by the MCP
``export_to_vault`` tool). Notion is deferred — it needs an external SDK + token.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.job_store import get_job_store
from ..core.note_exporter import (
    EXPORT_TARGETS,
    EXPORT_TEMPLATES,
    EpisodeNoteData,
    NoteTarget,
    NoteTemplate,
    render_episode_note,
    render_highlights_note,
    write_note_to_vault,
)
from .auth import verify_api_key
from .obsidian_routes import _validate_vault_path_scope

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Export"], dependencies=[Depends(verify_api_key)])

# Templates that a single-episode export can produce. Topic / digest notes are
# library/synthesis-scoped and exported via their own surfaces (future).
_JOB_TEMPLATES = {NoteTemplate.EPISODE, NoteTemplate.HIGHLIGHTS}


class ExportRequest(BaseModel):
    target: NoteTarget = NoteTarget.OBSIDIAN
    template: NoteTemplate = NoteTemplate.EPISODE
    vault_path: Optional[str] = Field(
        None, description="Vault folder to write into. Falls back to the configured Obsidian vault."
    )
    subfolder: Optional[str] = None
    min_confidence: float = Field(0.5, ge=0.0, le=1.0)
    max_segments: Optional[int] = Field(None, ge=0, description="Cap transcript lines in the note.")
    write: bool = Field(True, description="Write to the vault; if false, return rendered content only.")


class ExportResponse(BaseModel):
    success: bool
    template: str
    target: str
    written: bool
    file_path: Optional[str] = None
    note_name: Optional[str] = None
    content: Optional[str] = None
    error: Optional[str] = None


@router.get("/export-templates")
async def list_export_templates():
    """List available note templates + output targets."""
    return {"templates": EXPORT_TEMPLATES, "targets": EXPORT_TARGETS}


def _gather_episode_data(store, job: dict, job_id: str, min_confidence: float) -> EpisodeNoteData:
    tr = job.get("transcription_result") or {}
    segments = tr.get("segments") or []
    content_info = job.get("content_info") or {}
    title = content_info.get("title") or f"Transcription {job_id[:8]}"

    claims = store.get_claims_for_job(job_id, min_confidence=min_confidence)

    # Entities / topics are referenced by id on claims — resolve + dedup.
    entity_ids, topic_ids = [], []
    for c in claims:
        entity_ids += c.get("entity_ids") or []
        topic_ids += c.get("topic_ids") or []
    entities = _resolve_unique(entity_ids, store.get_entity_by_id)
    topics = _resolve_unique(topic_ids, store.get_topic_by_id)

    speakers = []
    for s in segments:
        spk = s.get("speaker")
        if spk and spk not in speakers:
            speakers.append(spk)

    return EpisodeNoteData(
        job_id=job_id,
        title=title,
        source_url=job.get("source_url"),
        platform=job.get("platform"),
        language=tr.get("language"),
        duration_seconds=tr.get("duration_seconds"),
        created_at=job.get("created_at"),
        speakers=speakers,
        claims=claims,
        entities=entities,
        topics=topics,
        segments=segments,
    )


def _resolve_unique(ids: list[str], getter) -> list[dict]:
    out, seen = [], set()
    for i in ids:
        if i in seen:
            continue
        seen.add(i)
        row = getter(i)
        if row:
            out.append(row)
    return out


@router.post("/jobs/{job_id}/export", response_model=ExportResponse)
async def export_job(job_id: str, body: ExportRequest):
    """Render an episode as a note and (optionally) write it into a vault."""
    if body.template not in _JOB_TEMPLATES:
        raise HTTPException(
            status_code=400,
            detail=f"Template '{body.template.value}' is not a single-episode template. "
            f"Use one of: {[t.value for t in _JOB_TEMPLATES]}",
        )

    store = get_job_store()
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if not job.get("transcription_result"):
        raise HTTPException(status_code=400, detail="Job has no transcription result to export")

    data = _gather_episode_data(store, job, job_id, body.min_confidence)
    if body.max_segments is not None:
        data.segments = data.segments[: body.max_segments]

    if body.template == NoteTemplate.HIGHLIGHTS:
        content = render_highlights_note(data, target=body.target)
        title = f"{data.title} — Highlights"
    else:
        content = render_episode_note(data, target=body.target)
        title = data.title

    if not body.write:
        return ExportResponse(
            success=True, template=body.template.value, target=body.target.value,
            written=False, content=content,
        )

    # Resolve the vault: explicit request path, else the configured Obsidian vault.
    vault_path = body.vault_path
    subfolder = body.subfolder
    if not vault_path:
        obs = store.get_obsidian_settings()
        if not obs or not obs.get("vault_path"):
            raise HTTPException(
                status_code=400,
                detail="No vault_path provided and no Obsidian vault configured.",
            )
        vault_path = obs["vault_path"]
        if subfolder is None:
            subfolder = obs.get("subfolder", "Sift")

    _validate_vault_path_scope(vault_path)
    result = write_note_to_vault(vault_path, title, content, subfolder=subfolder)
    if not result.success:
        raise HTTPException(status_code=500, detail=result.error)

    return ExportResponse(
        success=True, template=body.template.value, target=body.target.value,
        written=True, file_path=result.file_path, note_name=result.note_name,
    )
