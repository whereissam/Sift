"""API routes for AI provider settings."""

import time
import logging
from fastapi import APIRouter, Depends, HTTPException

from .auth import verify_api_key
from .schemas import (
    AIProvider,
    AISettingsRequest,
    AISettingsResponse,
    AIProviderInfo,
    AIProvidersResponse,
    AITestRequest,
    AITestResponse,
)
from ..core.job_store import get_job_store
from ..core.summarizer import LiteLLMProvider, TranscriptSummarizer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["AI Settings"], dependencies=[Depends(verify_api_key)])

# Provider configurations with default models
PROVIDER_CONFIGS = {
    AIProvider.OLLAMA: AIProviderInfo(
        name="ollama",
        display_name="Ollama",
        models=["llama3.2", "llama3.1", "mistral", "gemma2", "phi3", "qwen2.5"],
        requires_api_key=False,
        default_base_url="http://localhost:11434",
    ),
    AIProvider.OPENAI: AIProviderInfo(
        name="openai",
        display_name="OpenAI",
        models=["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"],
        requires_api_key=True,
        default_base_url=None,
    ),
    AIProvider.ANTHROPIC: AIProviderInfo(
        name="anthropic",
        display_name="Anthropic",
        models=[
            "claude-3-haiku-20240307",
            "claude-3-sonnet-20240229",
            "claude-3-opus-20240229",
            "claude-3-5-sonnet-20241022",
        ],
        requires_api_key=True,
        default_base_url=None,
    ),
    AIProvider.GROQ: AIProviderInfo(
        name="groq",
        display_name="Groq",
        models=[
            "llama-3.1-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
            "gemma2-9b-it",
        ],
        requires_api_key=True,
        default_base_url=None,
    ),
    AIProvider.DEEPSEEK: AIProviderInfo(
        name="deepseek",
        display_name="DeepSeek",
        models=["deepseek-chat", "deepseek-coder"],
        requires_api_key=True,
        default_base_url=None,
    ),
    AIProvider.GEMINI: AIProviderInfo(
        name="gemini",
        display_name="Google Gemini",
        models=[
            "gemini-1.5-flash",
            "gemini-1.5-pro",
            "gemini-2.0-flash-exp",
        ],
        requires_api_key=True,
        default_base_url=None,
    ),
    AIProvider.CUSTOM: AIProviderInfo(
        name="custom",
        display_name="Custom (OpenAI-compatible)",
        models=[],  # User provides custom model name
        requires_api_key=False,  # May or may not require API key
        default_base_url=None,
    ),
}


@router.get("/settings", response_model=AISettingsResponse)
async def get_ai_settings():
    """Get current AI provider settings."""
    job_store = get_job_store()
    settings = job_store.get_ai_settings()

    if not settings:
        # Return default settings
        return AISettingsResponse(
            provider=AIProvider.OLLAMA,
            model="llama3.2",
            base_url="http://localhost:11434",
            has_api_key=False,
        )

    return AISettingsResponse(
        provider=AIProvider(settings["provider"]),
        model=settings["model"],
        base_url=settings.get("base_url"),
        has_api_key=bool(settings.get("api_key")),
    )


@router.post("/settings", response_model=AISettingsResponse)
async def save_ai_settings(request: AISettingsRequest):
    """Save AI provider settings."""
    job_store = get_job_store()

    # Validate provider-specific requirements
    provider_config = PROVIDER_CONFIGS.get(request.provider)
    if provider_config and provider_config.requires_api_key and not request.api_key:
        raise HTTPException(
            status_code=400,
            detail=f"{request.provider.value} requires an API key",
        )

    # Set default base_url for Ollama if not provided
    base_url = request.base_url
    if request.provider == AIProvider.OLLAMA and not base_url:
        base_url = "http://localhost:11434"

    job_store.save_ai_settings(
        provider=request.provider.value,
        model=request.model,
        api_key=request.api_key,
        base_url=base_url,
    )

    logger.info(f"Saved AI settings: provider={request.provider.value}, model={request.model}")

    return AISettingsResponse(
        provider=request.provider,
        model=request.model,
        base_url=base_url,
        has_api_key=bool(request.api_key),
    )


@router.get("/providers", response_model=AIProvidersResponse)
async def get_providers():
    """Get list of available AI providers with their configurations."""
    return AIProvidersResponse(providers=list(PROVIDER_CONFIGS.values()))


@router.post("/test", response_model=AITestResponse)
async def test_connection(request: AITestRequest):
    """Test connection to an AI provider."""
    try:
        # Build the LiteLLM model string
        model = TranscriptSummarizer._build_litellm_model(
            request.provider.value,
            request.model,
        )

        # Set default base_url for Ollama
        base_url = request.base_url
        if request.provider == AIProvider.OLLAMA and not base_url:
            base_url = "http://localhost:11434"

        provider = LiteLLMProvider(
            model=model,
            api_key=request.api_key,
            base_url=base_url,
            provider=request.provider.value,
        )

        # Check availability first
        if not provider.is_available():
            return AITestResponse(
                success=False,
                error=f"Provider {request.provider.value} is not available. "
                      "Check that the service is running and API key is valid.",
            )

        # Test with a simple prompt
        start_time = time.time()
        response, tokens = await provider.generate(
            prompt="Say 'Hello!' in exactly one word.",
            system_prompt="You are a helpful assistant. Respond concisely.",
        )
        elapsed_ms = (time.time() - start_time) * 1000

        return AITestResponse(
            success=True,
            response_time_ms=round(elapsed_ms, 2),
            response_preview=response[:100] if response else None,
        )

    except Exception as e:
        logger.error(f"AI connection test failed: {e}")
        error_msg = str(e)

        # Provide more helpful error messages
        if "401" in error_msg or "Unauthorized" in error_msg:
            error_msg = "Invalid API key"
        elif "404" in error_msg:
            error_msg = "Model not found. Check the model name."
        elif "Connection" in error_msg or "refused" in error_msg.lower():
            error_msg = "Could not connect to the provider. Check the URL and ensure the service is running."

        return AITestResponse(
            success=False,
            error=error_msg,
        )
