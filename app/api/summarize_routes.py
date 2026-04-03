"""Summarization API routes."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from .auth import verify_api_key
from .ratelimit import limiter
from .schemas import JobStatus, SummarizeRequest
from .transcription_store import transcription_jobs

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(verify_api_key)])


@router.post("/summarize")
@limiter.limit("5/minute")
async def summarize_text(request: Request, body: SummarizeRequest):
    """
    Summarize text using an LLM.

    Supports multiple summary types:
    - bullet_points: Main ideas as bullet points
    - chapters: Chapter markers with timestamps (for transcripts)
    - key_topics: Major themes and topics
    - action_items: Tasks and follow-ups (for meetings)
    - full: Comprehensive summary with all elements
    """
    from ..core.summarizer import TranscriptSummarizer, SummaryType as CoreSummaryType

    text = body.text
    summary_type_str = body.summary_type.value

    if not text:
        raise HTTPException(status_code=400, detail="Text is required")

    try:
        summary_type = CoreSummaryType(summary_type_str)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid summary type. Valid types: {[t.value for t in CoreSummaryType]}",
        )

    summarizer = TranscriptSummarizer.from_settings()

    if not summarizer.provider:
        raise HTTPException(
            status_code=503,
            detail="No LLM provider configured. Set LLM_PROVIDER and required API keys in .env",
        )

    if not summarizer.provider.is_available():
        raise HTTPException(
            status_code=503,
            detail=f"LLM provider '{summarizer.provider.name}' is not available",
        )

    try:
        result = await summarizer.summarize(text, summary_type)
        return {
            "summary_type": result.summary_type.value,
            "content": result.content,
            "model": result.model,
            "provider": result.provider,
            "tokens_used": result.tokens_used,
        }
    except Exception as e:
        logger.exception("Summarization failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/summarize/job/{job_id}")
@limiter.limit("5/minute")
async def summarize_job(request: Request, job_id: str, summary_type: str = "bullet_points"):
    """
    Summarize a completed transcription job.

    Takes the job_id of a completed transcription and generates a summary.
    """
    from ..core.summarizer import TranscriptSummarizer, SummaryType as CoreSummaryType

    # Find the transcription job
    job = transcription_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Transcription job not found")

    if job.status != JobStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=f"Job is not completed. Current status: {job.status.value}",
        )

    if not job.text:
        raise HTTPException(status_code=400, detail="Job has no transcription text")

    try:
        summary_type_enum = CoreSummaryType(summary_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid summary type. Valid types: {[t.value for t in CoreSummaryType]}",
        )

    summarizer = TranscriptSummarizer.from_settings()

    if not summarizer.provider:
        raise HTTPException(
            status_code=503,
            detail="No LLM provider configured. Set LLM_PROVIDER and required API keys in .env",
        )

    if not summarizer.provider.is_available():
        raise HTTPException(
            status_code=503,
            detail=f"LLM provider '{summarizer.provider.name}' is not available",
        )

    try:
        result = await summarizer.summarize(job.text, summary_type_enum)
        return {
            "job_id": job_id,
            "summary_type": result.summary_type.value,
            "content": result.content,
            "model": result.model,
            "provider": result.provider,
            "tokens_used": result.tokens_used,
        }
    except Exception as e:
        logger.exception("Summarization failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summarize/providers")
async def list_summarization_providers():
    """
    List available LLM providers and their status.
    """
    from ..config import get_settings
    from ..core.summarizer import OllamaProvider

    settings = get_settings()

    providers = []

    # Check Ollama
    ollama = OllamaProvider(settings.ollama_base_url, settings.ollama_model)
    providers.append({
        "name": "ollama",
        "available": ollama.is_available(),
        "model": settings.ollama_model,
        "configured": True,
        "is_default": settings.llm_provider == "ollama",
    })

    # Check OpenAI
    providers.append({
        "name": "openai",
        "available": bool(settings.openai_api_key),
        "model": settings.openai_model,
        "configured": bool(settings.openai_api_key),
        "is_default": settings.llm_provider == "openai",
    })

    # Check OpenAI-compatible
    providers.append({
        "name": "openai_compatible",
        "available": bool(settings.openai_api_key and settings.openai_base_url),
        "model": settings.openai_model,
        "base_url": settings.openai_base_url,
        "configured": bool(settings.openai_api_key and settings.openai_base_url),
        "is_default": settings.llm_provider == "openai_compatible",
    })

    # Check Anthropic
    providers.append({
        "name": "anthropic",
        "available": bool(settings.anthropic_api_key),
        "model": settings.anthropic_model,
        "configured": bool(settings.anthropic_api_key),
        "is_default": settings.llm_provider == "anthropic",
    })

    return {
        "default_provider": settings.llm_provider,
        "providers": providers,
    }
