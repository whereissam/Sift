"""A caller-chosen base_url never receives the server's env LLM key.

Regression test for the security audit: with no api_key, LiteLLM falls back
to OPENAI_API_KEY (etc.) from the environment, so saving or testing a
"custom" provider with an attacker's base_url sent the operator's key there.
"""

from types import SimpleNamespace

import pytest

from app.delivery import clip_generator
from app.knowledge import summarizer


def _response():
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))], usage=None
    )


@pytest.fixture(params=[summarizer, clip_generator], ids=["summarizer", "clip_generator"])
def module(request, monkeypatch):
    calls = []

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)
        return _response()

    monkeypatch.setattr(request.param, "acompletion", fake_acompletion)
    request.param.calls = calls
    return request.param


async def test_keyless_custom_base_url_gets_placeholder(module):
    provider = module.LiteLLMProvider(model="openai/m", base_url="https://llm.example")
    await provider.generate("hi")
    assert module.calls[-1]["api_key"] == module.NO_API_KEY


async def test_explicit_key_is_used(module):
    provider = module.LiteLLMProvider(
        model="openai/m", base_url="https://llm.example", api_key="sk-user"
    )
    await provider.generate("hi")
    assert module.calls[-1]["api_key"] == "sk-user"


async def test_ollama_and_default_endpoints_are_unchanged(module):
    await module.LiteLLMProvider(model="ollama/llama3", base_url="http://localhost:11434").generate("hi")
    await module.LiteLLMProvider(model="gpt-4o-mini").generate("hi")
    assert all("api_key" not in call for call in module.calls)
