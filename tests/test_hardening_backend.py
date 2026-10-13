"""Hardening follow-ups: write rate limit and interactive LLM spend."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.api import summarize_routes
from app.api.ratelimit import WriteRateLimitMiddleware
from app.knowledge import knowledge_budget
from app.knowledge.knowledge_budget import record_llm_spend


@pytest.fixture
def limited_client():
    limiter = Limiter(key_func=get_remote_address, default_limits=["2/minute"])
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(WriteRateLimitMiddleware)

    @app.get("/read")
    async def read():
        return {}

    @app.post("/write")
    async def write():
        return {}

    @app.post("/own-limit")
    @limiter.limit("5/minute")
    async def own_limit(request: Request):
        return {}

    return TestClient(app)


class TestWriteRateLimit:
    def test_writes_get_the_default_limit(self, limited_client):
        codes = [limited_client.post("/write").status_code for _ in range(3)]
        assert codes == [200, 200, 429]

    def test_reads_are_not_limited(self, limited_client):
        assert {limited_client.get("/read").status_code for _ in range(10)} == {200}

    def test_route_limits_override_the_default(self, limited_client):
        codes = [limited_client.post("/own-limit").status_code for _ in range(6)]
        assert codes == [200] * 5 + [429]

    def test_installed_on_the_app(self):
        from app.main import app

        assert any(m.cls is WriteRateLimitMiddleware for m in app.user_middleware)


@pytest.fixture
def tracker(monkeypatch):
    t = knowledge_budget.KnowledgeBudgetTracker()
    monkeypatch.setattr(knowledge_budget, "_tracker", t)
    return t


class TestSpendRecording:
    def test_cloud_model_spend_is_recorded(self, tracker):
        record_llm_spend(SimpleNamespace(model="gpt-4o", tokens_used=2000))
        assert tracker.spent_today() == pytest.approx(0.015)

    @pytest.mark.parametrize("model", ["ollama/llama3.2", "translategemma:4b", "ollama/qwen2.5"])
    def test_local_models_are_free(self, tracker, model):
        record_llm_spend(SimpleNamespace(model=model, tokens_used=50_000))
        assert tracker.spent_today() == 0

    def test_missing_fields_are_ignored(self, tracker):
        record_llm_spend(SimpleNamespace(model=None, tokens_used=100))
        record_llm_spend(object())
        assert tracker.spent_today() == 0

    def test_summarize_route_records_spend(self, tracker, monkeypatch):
        from app.knowledge import summarizer as summarizer_mod

        class FakeSummarizer:
            provider = SimpleNamespace(is_available=lambda: True, name="openai")

            async def summarize(self, text, summary_type):
                return SimpleNamespace(
                    summary_type=summary_type, content="s", model="gpt-4o",
                    provider="openai", tokens_used=1000,
                )

        monkeypatch.setattr(
            summarizer_mod.TranscriptSummarizer, "from_settings", classmethod(lambda cls: FakeSummarizer())
        )
        app = FastAPI()
        app.include_router(summarize_routes.router, prefix="/api")
        r = TestClient(app).post(
            "/api/summarize", json={"text": "hello world", "summary_type": "bullet_points"}
        )
        assert r.status_code == 200, r.text
        assert tracker.spent_today() == pytest.approx(0.0075)
