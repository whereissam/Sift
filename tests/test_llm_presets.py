"""Tests for app/core/llm_presets.py.

We swap out the real JobStore and config singletons with tiny stubs so we can
drive the preset resolution logic without touching SQLite or the real env.
"""

from __future__ import annotations

import json

import pytest

from app.core import llm_presets
from app.core.llm_presets import TaskType, get_provider_for_task, list_defaults


class _FakeStore:
    """Mimics the slice of JobStore that llm_presets touches."""

    def __init__(
        self,
        ai_settings: dict | None = None,
        task_presets: dict | None = None,
    ):
        self._ai_settings = ai_settings
        self._task_presets = task_presets or {}

    def get_ai_settings(self):
        return self._ai_settings

    def get_task_presets(self):
        # Tests pass already-decrypted presets — JobStore.get_task_presets
        # would have run them through _decrypt_secret.
        return self._task_presets


class _NoEnv:
    """Stand-in for app.config.Settings with no provider configured."""

    llm_provider = "none"
    openai_api_key = None
    openai_model = None
    openai_base_url = None
    anthropic_api_key = None
    anthropic_model = None
    groq_api_key = None
    groq_model = None
    deepseek_api_key = None
    deepseek_model = None
    gemini_api_key = None
    gemini_model = None
    ollama_model = "llama3.2"
    ollama_base_url = "http://localhost:11434"


@pytest.fixture(autouse=True)
def _patch_defaults(monkeypatch):
    """Default fixture: empty DB ai_settings, empty env."""
    monkeypatch.setattr(
        "app.core.job_store.get_job_store", lambda: _FakeStore(None)
    )
    monkeypatch.setattr("app.config.get_settings", lambda: _NoEnv())
    yield


def _set_store(monkeypatch, **kwargs):
    monkeypatch.setattr(
        "app.core.job_store.get_job_store", lambda: _FakeStore(**kwargs)
    )


def _set_env(monkeypatch, settings_obj):
    monkeypatch.setattr("app.config.get_settings", lambda: settings_obj)


# ---------- defaults registry ----------


def test_list_defaults_covers_all_tasks():
    defaults = list_defaults()
    assert {TaskType(k) for k in defaults} == set(TaskType)


# ---------- nothing configured ----------


def test_returns_none_when_nothing_is_configured():
    assert get_provider_for_task(TaskType.EXTRACT) is None


# ---------- DB ai_settings as fallback ----------


def test_default_preset_uses_db_api_key_when_providers_match(monkeypatch):
    _set_store(
        monkeypatch,
        ai_settings={"provider": "openai", "model": "ignored", "api_key": "sk-test"},
    )
    provider = get_provider_for_task(TaskType.EXTRACT)
    assert provider is not None
    # Default extract preset is openai/gpt-4o-mini; DB only supplies the key.
    assert provider.model_name == "gpt-4o-mini"
    assert provider.api_key == "sk-test"
    assert provider.name == "openai"


def test_falls_back_to_user_provider_when_default_provider_has_no_key(monkeypatch):
    """User has Ollama in DB but default preset is openai → use Ollama."""
    _set_store(
        monkeypatch,
        ai_settings={"provider": "ollama", "model": "llama3.2"},
    )
    provider = get_provider_for_task(TaskType.EXTRACT)
    assert provider is not None
    assert provider.name == "ollama"
    assert provider.model_name == "ollama/llama3.2"


# ---------- env fallback ----------


def test_env_settings_used_when_db_empty(monkeypatch):
    """A user with only `.env` configured (no DB row) gets a working provider."""

    class _OllamaEnv(_NoEnv):
        llm_provider = "ollama"
        ollama_model = "llama3.1"
        ollama_base_url = "http://elsewhere:11434"

    _set_env(monkeypatch, _OllamaEnv())
    provider = get_provider_for_task(TaskType.EXTRACT)
    assert provider is not None
    assert provider.name == "ollama"
    assert provider.model_name == "ollama/llama3.1"
    assert provider.base_url == "http://elsewhere:11434"


def test_env_openai_provides_api_key_for_default_preset(monkeypatch):
    class _OpenAIEnv(_NoEnv):
        llm_provider = "openai"
        openai_api_key = "sk-from-env"
        openai_model = "gpt-4o-mini"

    _set_env(monkeypatch, _OpenAIEnv())
    provider = get_provider_for_task(TaskType.EXTRACT)
    assert provider is not None
    assert provider.name == "openai"
    assert provider.api_key == "sk-from-env"


def test_db_wins_over_env(monkeypatch):
    class _OpenAIEnv(_NoEnv):
        llm_provider = "openai"
        openai_api_key = "sk-from-env"
        openai_model = "gpt-4o-mini"

    _set_env(monkeypatch, _OpenAIEnv())
    _set_store(
        monkeypatch,
        ai_settings={"provider": "openai", "model": "x", "api_key": "sk-from-db"},
    )
    provider = get_provider_for_task(TaskType.EXTRACT)
    assert provider is not None
    assert provider.api_key == "sk-from-db"


# ---------- per-task overrides ----------


def test_per_task_override_wins_over_default(monkeypatch):
    _set_store(
        monkeypatch,
        ai_settings={
            "provider": "openai",
            "model": "ignored",
            "api_key": "sk-test",
        },
        task_presets={
            "extract": {
                "provider": "groq",
                "model": "llama-3.1-8b-instant",
                "api_key": "gsk-test",
            }
        },
    )
    provider = get_provider_for_task("extract")
    assert provider is not None
    assert provider.name == "groq"
    assert provider.model_name == "groq/llama-3.1-8b-instant"
    assert provider.api_key == "gsk-test"


def test_ollama_override_does_not_require_api_key(monkeypatch):
    _set_store(
        monkeypatch,
        ai_settings=None,
        task_presets={"extract": {"provider": "ollama", "model": "llama3.2"}},
    )
    provider = get_provider_for_task(TaskType.EXTRACT)
    assert provider is not None
    assert provider.model_name == "ollama/llama3.2"


def test_malformed_task_preset_is_skipped_not_crashed(monkeypatch):
    """Defensive: a string preset (not a dict) shouldn't blow up resolution."""
    # Bypass the JobStore.get_task_presets sanitization — we want to test the
    # downstream code's robustness in case malformed entries leak through.
    class _BadStore(_FakeStore):
        def get_task_presets(self):
            # Real JobStore.get_task_presets filters these out, but if it
            # ever didn't, llm_presets should still recover gracefully.
            return {"extract": "this-is-not-a-dict"}  # type: ignore[dict-item]

    monkeypatch.setattr("app.core.job_store.get_job_store", lambda: _BadStore())
    # Should not raise; should fall through to defaults / fallback.
    result = get_provider_for_task(TaskType.EXTRACT)
    # No env, no usable preset, no DB ai_settings → None
    assert result is None


# ---------- arg shape ----------


def test_string_task_arg_accepted():
    list_defaults()
    get_provider_for_task("summarize")  # should not raise


def test_unknown_task_raises():
    with pytest.raises(ValueError):
        get_provider_for_task("nonsense-task")
