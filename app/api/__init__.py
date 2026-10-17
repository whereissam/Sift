"""FastAPI REST API for X Spaces Downloader."""

from fastapi import APIRouter

from .routes import router as main_router
from .download_routes import router as download_router
from .transcription_routes import router as transcription_router
from .transcript_fetch_routes import router as transcript_fetch_router
from .job_management_routes import router as job_management_router
from .summarize_routes import router as summarize_router
from .subscription_routes import router as subscription_router
from .batch_routes import router as batch_router
from .schedule_routes import router as schedule_router
from .webhook_routes import router as webhook_router
from .annotation_routes import router as annotation_router
from .storage_routes import router as storage_router
from .cloud_routes import router as cloud_router
from .ai_settings_routes import router as ai_settings_router
from .translation_routes import router as translation_router
from .clip_routes import router as clip_router, clips_api_router
from .sentiment_routes import router as sentiment_router
from .extract_routes import (
    router as extract_router,
    presets_router as extract_presets_router,
    schemas_router as extraction_schemas_router,
)
from .obsidian_routes import router as obsidian_router
from .realtime_routes import router as realtime_router
from .model_routes import router as model_router
from .knowledge_routes import router as knowledge_router
from .entity_routes import router as entity_router
from .topic_routes import router as topic_router
from .prediction_routes import router as prediction_router
from .kol_routes import router as kol_router
from .digest_routes import router as digest_router
from .export_routes import router as export_router
from .search_routes import router as search_router
from .ask_routes import router as ask_router
from .ingest_routes import router as ingest_router
from .contradiction_routes import router as contradiction_router
from .distill_routes import router as distill_router
from .principal_routes import router as principal_router

# Create combined router
router = APIRouter()
router.include_router(main_router)
router.include_router(download_router)
router.include_router(transcription_router)
router.include_router(transcript_fetch_router)
router.include_router(job_management_router)
router.include_router(summarize_router)
router.include_router(subscription_router)
router.include_router(batch_router)
router.include_router(schedule_router)
router.include_router(webhook_router)
router.include_router(annotation_router)
router.include_router(storage_router)
router.include_router(cloud_router)
router.include_router(ai_settings_router)
router.include_router(translation_router)
router.include_router(clips_api_router)  # /clips/* routes (must be before clip_router)
router.include_router(clip_router)  # /jobs/{job_id}/clips/* routes
router.include_router(sentiment_router)  # /jobs/{job_id}/sentiment/* routes
router.include_router(extract_presets_router)  # /extract/presets route
router.include_router(extract_router)  # /jobs/{job_id}/extract/* routes
router.include_router(extraction_schemas_router)  # P17: /extraction-schemas CRUD
router.include_router(obsidian_router)  # /obsidian/* routes
router.include_router(realtime_router)  # /transcribe/live WebSocket
router.include_router(model_router)  # /models/* routes (desktop model management)
router.include_router(knowledge_router)  # P18: /jobs/{id}/knowledge, /jobs/{id}/extract-knowledge, /claims
router.include_router(entity_router)  # P18 Phase B: /entities, /entities/{id_or_slug}[/mentions]
router.include_router(topic_router)  # P18 Phase C.1: /topics, /topics/{id}[/claims]
router.include_router(prediction_router)  # P18 Phase C.2: /predictions, /predictions/{claim_id}[/resolve|/review]
router.include_router(kol_router)  # KOL scorecard: /kols, /episodes/{id}/speakers
router.include_router(digest_router)  # P20: /digests[/{id}[/run|/runs]], /topics/{id}/synthesis
router.include_router(export_router)  # P21: /export-templates, /jobs/{id}/export
router.include_router(search_router)  # P10: /search, /search/status, /jobs/{id}/search-index
router.include_router(ask_router)  # P11: /ask, /jobs/{id}/ask, /jobs/{id}/chat-history
router.include_router(ingest_router)  # P12: /ingest, /jobs/{id}/pipeline, /pipelines
router.include_router(contradiction_router)  # P13: /jobs/{id}/[analyze-]contradictions, /contradictions
router.include_router(distill_router)  # P14: /distill, /distill/{id}[/markdown], /distillations
router.include_router(principal_router)  # P22 S4: /principals, /usage

__all__ = ["router"]
