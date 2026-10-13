"""Hardening follow-ups from the 2026-10 security audit."""

import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import auth, cloud_routes, ingestion_routes, job_management_routes
from app.api.schedule_routes import _to_naive_utc
from app.api.schemas import TranslateRequest
from app.config import Settings, get_settings
from app.pipeline import queue_manager, workflow
from sift_core.fetch.url_validator import _ip_block_reason


class TestApiKeySettings:
    @pytest.mark.parametrize("value", ["", "   "])
    def test_blank_api_key_means_unset(self, value):
        assert Settings(api_key=value).api_key is None

    def test_docs_follow_api_key_unless_configured(self):
        assert Settings(api_key=None).docs_enabled
        assert not Settings(api_key="k").docs_enabled
        assert Settings(api_key="k", api_docs=True).docs_enabled
        assert not Settings(api_key=None, api_docs=False).docs_enabled


class TestKeyComparison:
    @pytest.fixture(autouse=True)
    def _key(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "api_key", "s3cret")

    async def _verify(self, key):
        request = SimpleNamespace(state=SimpleNamespace())
        await auth.verify_api_key(request, key)

    async def test_non_ascii_key_is_a_401_not_a_500(self):
        with pytest.raises(HTTPException) as exc:
            await self._verify("sécret")
        assert exc.value.status_code == 401

    async def test_correct_key_passes(self):
        await self._verify("s3cret")

    async def test_master_guard_handles_non_ascii(self):
        with pytest.raises(HTTPException) as exc:
            await auth.verify_master_key("ключ")
        assert exc.value.status_code == 403


class TestSsrfValidatorGaps:
    @pytest.mark.parametrize(
        "ip",
        [
            "::7f00:1",  # IPv4-compatible ::127.0.0.1
            "64:ff9b::a9fe:a9fe",  # NAT64 -> 169.254.169.254
            "2002:7f00:1::",  # 6to4 -> 127.0.0.1
            "2001:0:4136:e378:8000:63bf:80ff:fffe",  # Teredo -> 127.0.0.1
            "198.18.0.1",  # benchmarking
            "192.0.0.8",  # IETF protocol assignments
            "fec0::1",  # site-local
        ],
    )
    def test_blocked(self, ip):
        assert _ip_block_reason(ip) is not None

    @pytest.mark.parametrize(
        "ip", ["8.8.8.8", "93.184.216.34", "2606:4700:4700::1111", "64:ff9b::808:808"]
    )
    def test_public_addresses_still_allowed(self, ip):
        assert _ip_block_reason(ip) is None


class TestQueuedJobsRun:
    async def test_start_sets_a_processor(self, monkeypatch):
        manager = queue_manager.DownloadQueueManager(max_concurrent=1)
        monkeypatch.setattr(queue_manager, "_queue_manager", manager)
        await queue_manager.start_queue_manager()
        try:
            assert manager._processor is queue_manager.run_queued_job
        finally:
            await manager.stop()

    async def test_processor_runs_the_stored_job(self, monkeypatch):
        ran = []

        class FakeProcessor:
            def __init__(self, store):
                pass

            async def retry_job(self, job_id):
                ran.append(job_id)

        monkeypatch.setattr(workflow, "WorkflowProcessor", FakeProcessor)
        monkeypatch.setattr(queue_manager, "get_job_store", lambda: None)
        await queue_manager.run_queued_job("job-1")
        assert ran == ["job-1"]

    async def test_recovery_leaves_future_scheduled_jobs_alone(self, monkeypatch):
        later = (datetime.utcnow() + timedelta(hours=1)).isoformat()
        jobs = [
            {"job_id": "now", "status": "pending", "scheduled_at": None},
            {"job_id": "later", "status": "pending", "scheduled_at": later},
        ]
        ran = []

        class FakeProcessor:
            def __init__(self, store):
                pass

            async def retry_job(self, job_id):
                ran.append(job_id)

        store = SimpleNamespace(get_unfinished_jobs=lambda: jobs)
        monkeypatch.setattr(workflow, "get_job_store", lambda: store)
        monkeypatch.setattr(workflow, "WorkflowProcessor", FakeProcessor)
        await workflow.recover_unfinished_jobs()
        assert ran == ["now"]


class TestScheduleTimezone:
    def test_aware_time_is_converted_not_truncated(self):
        tz = timezone(timedelta(hours=8))
        assert _to_naive_utc(datetime(2026, 1, 1, 10, 0, tzinfo=tz)) == datetime(2026, 1, 1, 2, 0)

    def test_naive_time_is_taken_as_utc(self):
        assert _to_naive_utc(datetime(2026, 1, 1, 10, 0)) == datetime(2026, 1, 1, 10, 0)


class TestRetryRoute:
    @pytest.fixture
    def client(self, monkeypatch):
        jobs = {
            "failed": {"job_id": "failed", "status": "failed"},
            "running": {"job_id": "running", "status": "downloading"},
            "pending": {"job_id": "pending", "status": "pending"},
        }
        store = SimpleNamespace(get_job=jobs.get)
        monkeypatch.setattr("app.store.get_job_store", lambda: store)
        retried = []

        class FakeProcessor:
            def __init__(self, store):
                pass

            async def retry_job(self, job_id):
                retried.append(job_id)

        monkeypatch.setattr(workflow, "WorkflowProcessor", FakeProcessor)
        app = FastAPI()
        app.include_router(job_management_routes.router, prefix="/api")
        client = TestClient(app)
        client.retried = retried
        return client

    @pytest.mark.parametrize("job_id", ["running", "pending"])
    def test_active_jobs_are_not_run_twice(self, client, job_id):
        assert client.post(f"/api/jobs/{job_id}/retry").status_code == 409
        assert client.retried == []

    def test_failed_job_is_retried(self, client):
        assert client.post("/api/jobs/failed/retry").status_code == 200
        assert client.retried == ["failed"]


def test_translate_text_is_capped():
    with pytest.raises(ValidationError):
        TranslateRequest(text="x" * 100_001, target_lang="es")


class TestIdempotencyPrincipal:
    def test_principal_keys_get_their_own_namespace(self):
        request = SimpleNamespace(state=SimpleNamespace(principal={"principal_id": "p1"}))
        assert ingestion_routes._idempotency_principal(request) == "p1"

    @pytest.mark.parametrize("state", [SimpleNamespace(principal=None), SimpleNamespace()])
    def test_master_and_open_access_share_default(self, state):
        request = SimpleNamespace(state=state)
        assert ingestion_routes._idempotency_principal(request) == "default"


class TestOAuthState:
    def test_state_is_single_use_and_bound(self):
        state = cloud_routes._issue_oauth_state("gdrive", "http://localhost/cb")
        assert not cloud_routes._consume_oauth_state(state, "dropbox", "http://localhost/cb")
        state = cloud_routes._issue_oauth_state("gdrive", "http://localhost/cb")
        assert not cloud_routes._consume_oauth_state(state, "gdrive", "http://evil/cb")
        state = cloud_routes._issue_oauth_state("gdrive", "http://localhost/cb")
        assert cloud_routes._consume_oauth_state(state, "gdrive", "http://localhost/cb")
        assert not cloud_routes._consume_oauth_state(state, "gdrive", "http://localhost/cb")

    def test_missing_or_unknown_state_is_refused(self):
        assert not cloud_routes._consume_oauth_state(None, "gdrive", "http://localhost/cb")
        assert not cloud_routes._consume_oauth_state("forged", "gdrive", "http://localhost/cb")

    def test_expired_state_is_refused(self, monkeypatch):
        state = cloud_routes._issue_oauth_state("gdrive", "http://localhost/cb")
        future = time.monotonic() + cloud_routes._OAUTH_STATE_TTL_SECONDS + 1
        monkeypatch.setattr(cloud_routes.time, "monotonic", lambda: future)
        assert not cloud_routes._consume_oauth_state(state, "gdrive", "http://localhost/cb")
