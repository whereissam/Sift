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
from .extract_routes import router as extract_router, presets_router as extract_presets_router
from .obsidian_routes import router as obsidian_router
from .realtime_routes import router as realtime_router

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
router.include_router(obsidian_router)  # /obsidian/* routes
router.include_router(realtime_router)  # /transcribe/live WebSocket

__all__ = ["router"]
