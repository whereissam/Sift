"""API routes for translation."""

import logging
from fastapi import APIRouter, Depends, HTTPException

from .auth import verify_api_key
from .schemas import (
    TranslateRequest,
    TranslateFromJobRequest,
    TranslateResponse,
    LanguageInfo,
    SupportedLanguagesResponse,
    TranslatorType,
)
from ..core.translator import (
    TranslateGemmaTranslator,
    AITranslator,
    get_supported_languages,
    normalize_language_code,
    get_language_name,
    SUPPORTED_LANGUAGES,
    COMMON_LANGUAGES,
)
from ..core.job_store import get_job_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/translate", tags=["Translation"], dependencies=[Depends(verify_api_key)])


@router.get("/languages", response_model=SupportedLanguagesResponse)
async def get_languages(all: bool = False):
    """Get list of supported languages for translation.

    By default returns only common languages. Set all=true to get all 55 supported languages.
    """
    lang_dict = SUPPORTED_LANGUAGES if all else COMMON_LANGUAGES
    languages = [
        LanguageInfo(code=code, name=name)
        for code, name in sorted(lang_dict.items(), key=lambda x: x[1])
    ]
    return SupportedLanguagesResponse(
        languages=languages,
        total=len(languages),
    )


@router.get("/available")
async def check_availability():
    """Check which translation backends are available.

    Returns availability status for both TranslateGemma and AI provider.
    """
    from ..config import get_settings
    settings = get_settings()

    result = {
        "available": False,
        "translategemma": {
            "available": False,
            "models": [],
        },
        "ai_provider": {
            "available": False,
            "provider": None,
            "model": None,
        },
        "ollama_url": settings.ollama_base_url,
    }

    # Check TranslateGemma
    try:
        import httpx
        with httpx.Client(timeout=5.0) as client:
            response = client.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
            if response.status_code == 200:
                data = response.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                translate_models = [m for m in models if "translategemma" in m.lower()]
                result["translategemma"]["available"] = len(translate_models) > 0
                result["translategemma"]["models"] = translate_models
    except Exception as e:
        result["translategemma"]["error"] = str(e)

    # Check AI provider
    try:
        if AITranslator.is_available():
            result["ai_provider"]["available"] = True
            # Get provider info
            job_store = get_job_store()
            ai_settings = job_store.get_ai_settings()
            if ai_settings:
                result["ai_provider"]["provider"] = ai_settings.get("provider")
                result["ai_provider"]["model"] = ai_settings.get("model")
    except Exception as e:
        result["ai_provider"]["error"] = str(e)

    # Overall availability
    result["available"] = (
        result["translategemma"]["available"] or
        result["ai_provider"]["available"]
    )

    return result


@router.post("", response_model=TranslateResponse)
async def translate_text(request: TranslateRequest):
    """Translate text from one language to another.

    Supports two translation backends:
    - `translategemma`: Local TranslateGemma via Ollama (default)
    - `ai_provider`: Use configured AI provider (GPT-4, Claude, etc.)

    Example:
    ```json
    {
        "text": "Hello, how are you?",
        "source_lang": "en",
        "target_lang": "ja",
        "translator": "ai_provider"
    }
    ```
    """
    # Validate languages
    try:
        source_code = normalize_language_code(request.source_lang)
        target_code = normalize_language_code(request.target_lang)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        if request.translator == TranslatorType.AI_PROVIDER:
            # Use configured AI provider
            translator = AITranslator.from_settings()

            if not translator.provider:
                raise HTTPException(
                    status_code=503,
                    detail="No AI provider configured. Please configure AI settings first.",
                )

            result = await translator.translate(
                text=request.text,
                source_lang=source_code,
                target_lang=target_code,
            )
        else:
            # Use TranslateGemma
            from ..config import get_settings
            settings = get_settings()

            # Get available models first
            available_models = []
            try:
                import httpx
                with httpx.Client(timeout=5.0) as client:
                    response = client.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
                    if response.status_code == 200:
                        data = response.json()
                        available_models = [
                            m.get("name", "") for m in data.get("models", [])
                            if "translategemma" in m.get("name", "").lower()
                        ]
            except Exception:
                pass

            # Determine the model to use
            requested_model = request.model or "latest"
            if not requested_model.startswith("translategemma"):
                requested_model = f"translategemma:{requested_model}"

            # Check if the requested model is available, otherwise try to find an alternative
            model = requested_model
            if available_models and requested_model not in available_models:
                # Try to find the requested size variant
                size = requested_model.split(":")[-1] if ":" in requested_model else "latest"
                matching = [m for m in available_models if f":{size}" in m]
                if matching:
                    model = matching[0]
                elif "translategemma:latest" in available_models:
                    # Fall back to latest if specific size not found
                    model = "translategemma:latest"
                elif available_models:
                    # Use whatever is available
                    model = available_models[0]

            translator = TranslateGemmaTranslator(
                model=model,
                base_url=settings.ollama_base_url,
            )

            if not translator.is_available():
                raise HTTPException(
                    status_code=503,
                    detail=f"TranslateGemma is not available. Please install it with: ollama pull translategemma",
                )

            result = await translator.translate(
                text=request.text,
                source_lang=source_code,
                target_lang=target_code,
            )

        return TranslateResponse(
            source_text=result.source_text,
            translated_text=result.translated_text,
            source_lang=result.source_lang,
            target_lang=result.target_lang,
            source_lang_name=get_language_name(result.source_lang),
            target_lang_name=get_language_name(result.target_lang),
            model=result.model,
            tokens_used=result.tokens_used,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Translation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Translation failed: {str(e)}")


@router.post("/job", response_model=TranslateResponse)
async def translate_job(request: TranslateFromJobRequest):
    """Translate a completed transcription job.

    Retrieves the transcript from a completed job and translates it
    to the target language.
    """
    job_store = get_job_store()
    job = job_store.get_job(request.job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Job is not completed (status: {job['status']})",
        )

    # Get transcript text
    transcription = job.get("transcription_result")
    if not transcription:
        raise HTTPException(
            status_code=400,
            detail="Job has no transcription result",
        )

    text = transcription.get("text", "")
    if not text:
        raise HTTPException(
            status_code=400,
            detail="Transcription has no text content",
        )

    # Determine source language
    source_lang = request.source_lang
    if not source_lang:
        # Try to get from transcription result
        source_lang = transcription.get("language", "en")

    # Validate languages
    try:
        source_code = normalize_language_code(source_lang)
        target_code = normalize_language_code(request.target_lang)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Determine model
    model = request.model or "translategemma:latest"
    if not model.startswith("translategemma"):
        model = f"translategemma:{model}"

    # Create translator
    from ..config import get_settings
    settings = get_settings()

    translator = TranslateGemmaTranslator(
        model=model,
        base_url=settings.ollama_base_url,
    )

    if not translator.is_available():
        raise HTTPException(
            status_code=503,
            detail=f"TranslateGemma is not available. Please install it with: ollama pull {model}",
        )

    try:
        result = await translator.translate(
            text=text,
            source_lang=source_code,
            target_lang=target_code,
        )

        return TranslateResponse(
            source_text=result.source_text,
            translated_text=result.translated_text,
            source_lang=result.source_lang,
            target_lang=result.target_lang,
            source_lang_name=get_language_name(result.source_lang),
            target_lang_name=get_language_name(result.target_lang),
            model=result.model,
            tokens_used=result.tokens_used,
        )

    except Exception as e:
        logger.error(f"Translation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Translation failed: {str(e)}")
