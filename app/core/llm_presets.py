"""Task-based LLM preset registry.

Maps task types (extract, summarize, synthesize, chat) to a configured
LiteLLMProvider. Defaults are defined in code; users can override per task
via the `ai_settings.task_presets` JSON column.

Resolution order, per task:
  1. Per-task override stored in `ai_settings.task_presets[task]`
  2. Default preset baked into `_DEFAULT_PRESETS`, *if* the user has a working
     credential for that provider (DB or env)
  3. The user's main configured provider (from DB `ai_settings`, falling back
     to env vars via `app.config.get_settings()`)

This means a user who only set `LLM_PROVIDER=ollama` in `.env` gets Ollama for
extract/summarize/synthesize/chat — they don't have to hand-write
`task_presets` to escape the OpenAI default.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

from .summarizer import LiteLLMProvider

logger = logging.getLogger(__name__)


class TaskType(str, Enum):
    """LLM task categories with different cost / quality requirements."""

    EXTRACT = "extract"          # cheap, structured, deterministic
    SUMMARIZE = "summarize"      # cheap-medium
    SYNTHESIZE = "synthesize"    # better model allowed (cross-source)
    CHAT = "chat"                # user-selected (RAG / ask_episode)


# Default provider+model per task. Overridable via ai_settings.task_presets.
# Format mirrors ai_settings: {provider, model, [api_key], [base_url]}
_DEFAULT_PRESETS: dict[TaskType, dict] = {
    TaskType.EXTRACT: {"provider": "openai", "model": "gpt-4o-mini"},
    TaskType.SUMMARIZE: {"provider": "openai", "model": "gpt-4o-mini"},
    TaskType.SYNTHESIZE: {"provider": "openai", "model": "gpt-4o"},
    TaskType.CHAT: {"provider": "openai", "model": "gpt-4o-mini"},
}


def _build_litellm_model(provider: str, model: str) -> str:
    """Build the litellm model string from provider+model name.

    Mirrors TranscriptSummarizer._build_litellm_model so all services format
    identically. Kept here to avoid coupling presets to the summarizer module
    just for one helper.
    """
    if provider == "ollama":
        return f"ollama/{model}"
    if provider == "groq":
        return f"groq/{model}"
    if provider == "deepseek":
        return f"deepseek/{model}"
    if provider == "gemini":
        return f"gemini/{model}"
    if provider == "custom":
        return f"openai/{model}"
    return model  # openai, anthropic — no prefix


def _env_to_ai_settings() -> Optional[dict]:
    """Build an ai_settings-shaped dict from env vars.

    Mirrors the long if/elif chain in TranscriptSummarizer.from_settings so
    behaviour is consistent across services. Returns None when no env-only
    provider is configured.
    """
    try:
        from ..config import get_settings

        s = get_settings()
    except Exception:
        return None

    if s.llm_provider == "ollama":
        return {
            "provider": "ollama",
            "model": s.ollama_model,
            "base_url": s.ollama_base_url,
        }
    if s.llm_provider == "openai" and s.openai_api_key:
        return {
            "provider": "openai",
            "model": s.openai_model,
            "api_key": s.openai_api_key,
            "base_url": s.openai_base_url,
        }
    if s.llm_provider == "openai_compatible" and s.openai_api_key:
        return {
            "provider": "custom",
            "model": s.openai_model,
            "api_key": s.openai_api_key,
            "base_url": s.openai_base_url,
        }
    if s.llm_provider == "anthropic" and s.anthropic_api_key:
        return {
            "provider": "anthropic",
            "model": s.anthropic_model,
            "api_key": s.anthropic_api_key,
        }
    if s.llm_provider == "groq" and s.groq_api_key:
        return {
            "provider": "groq",
            "model": s.groq_model,
            "api_key": s.groq_api_key,
        }
    if s.llm_provider == "deepseek" and s.deepseek_api_key:
        return {
            "provider": "deepseek",
            "model": s.deepseek_model,
            "api_key": s.deepseek_api_key,
        }
    if s.llm_provider == "gemini" and s.gemini_api_key:
        return {
            "provider": "gemini",
            "model": s.gemini_model,
            "api_key": s.gemini_api_key,
        }
    return None


def _load_task_presets() -> dict[TaskType, dict]:
    """Load per-task overrides from `ai_settings.task_presets`.

    The actual JSON parsing + api_key decryption lives in
    `JobStore.get_task_presets()` so the encryption boundary stays inside the
    storage layer.
    """
    try:
        from .job_store import get_job_store

        raw = get_job_store().get_task_presets()
    except Exception as e:
        logger.debug("could not load task presets: %s", e)
        return {}

    out: dict[TaskType, dict] = {}
    for task_str, preset in raw.items():
        if not isinstance(preset, dict):
            # Defensive: a non-dict slipped past the storage-layer sanitization.
            logger.warning("task preset %s is not a dict; skipping", task_str)
            continue
        try:
            out[TaskType(task_str)] = preset
        except ValueError:
            logger.warning("unknown task preset key: %s", task_str)
    return out


def _fallback_to_global_ai_settings() -> Optional[dict]:
    """User's main configured provider — DB row first, then env vars.

    The env fallback matches what TranscriptSummarizer.from_settings and
    SentimentAnalyzer.from_settings already do, so behaviour stays consistent
    across services. Without this, a `.env`-only setup that powers
    summarization would 503 on extraction.
    """
    try:
        from .job_store import get_job_store

        db = get_job_store().get_ai_settings()
        if db:
            return db
    except Exception:
        pass
    return _env_to_ai_settings()


def _preset_is_usable(preset: dict) -> bool:
    """A preset is usable if it has credentials for its provider."""
    provider = preset.get("provider")
    if not provider:
        return False
    if provider in {"ollama", "custom"}:
        return True  # local / OpenAI-compatible — no key required
    return bool(preset.get("api_key"))


def get_provider_for_task(task: TaskType | str) -> Optional[LiteLLMProvider]:
    """Resolve a configured LiteLLMProvider for the given task.

    Returns None when nothing is configured anywhere (DB ai_settings empty,
    env vars empty, default preset's provider has no key).
    """
    if isinstance(task, str):
        task = TaskType(task)

    overrides = _load_task_presets()
    global_settings = _fallback_to_global_ai_settings() or {}

    # 1. Per-task override always wins
    preset: Optional[dict] = overrides.get(task)

    # 2. Default preset, hydrated with global creds when the providers match.
    if preset is None:
        default = dict(_DEFAULT_PRESETS[task])
        if global_settings.get("provider") == default["provider"]:
            default["api_key"] = global_settings.get("api_key")
            default["base_url"] = global_settings.get("base_url")
        if _preset_is_usable(default):
            preset = default

    # 3. Fall back to the user's main provider if the default isn't usable.
    if preset is None and global_settings:
        candidate = {
            "provider": global_settings.get("provider"),
            "model": global_settings.get("model"),
            "api_key": global_settings.get("api_key"),
            "base_url": global_settings.get("base_url"),
        }
        if _preset_is_usable(candidate):
            preset = candidate

    if preset is None:
        logger.info(
            "no usable provider configured for task=%s "
            "(default preset has no api_key and no fallback ai_settings/env)",
            task.value,
        )
        return None

    provider_name = preset["provider"]
    model = preset["model"]
    api_key = preset.get("api_key")
    base_url = preset.get("base_url")

    if not _preset_is_usable(preset):
        logger.info(
            "preset for task=%s provider=%s missing api_key", task.value, provider_name
        )
        return None

    return LiteLLMProvider(
        model=_build_litellm_model(provider_name, model),
        api_key=api_key,
        base_url=base_url,
        provider=provider_name,
    )


def get_default_preset(task: TaskType | str) -> dict:
    """Return the built-in default preset for a task (for introspection / UI)."""
    if isinstance(task, str):
        task = TaskType(task)
    return dict(_DEFAULT_PRESETS[task])


def list_defaults() -> dict[str, dict]:
    """Return all built-in defaults (used by API endpoint exposing the registry)."""
    return {task.value: dict(preset) for task, preset in _DEFAULT_PRESETS.items()}
