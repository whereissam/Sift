"""One batch request cannot freeze the API.

Regression tests for the security audit: batch routes took any number of
URLs, wrote a job row per URL on the event loop, and the queue's duplicate
check scanned the whole queue on every enqueue (O(N^2) with no yield).
"""

import asyncio
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import batch_routes
from app.pipeline.queue_manager import DownloadQueueManager


class _FakeBatchManager:
    def __init__(self):
        self.calls = []

    def create_batch(self, urls, **kwargs):
        try:
            asyncio.get_running_loop()
            on_loop = True
        except RuntimeError:
            on_loop = False
        self.calls.append(on_loop)
        return "b1", [f"j{i}" for i, _ in enumerate(urls)]

    def get_batch_status(self, batch_id):
        return {"name": "n", "status": "pending", "created_at": datetime.utcnow().isoformat()}

    async def enqueue_batch_jobs(self, batch_id):
        return 0


@pytest.fixture
def manager(monkeypatch):
    fake = _FakeBatchManager()
    monkeypatch.setattr(batch_routes, "get_batch_manager", lambda: fake)
    return fake


@pytest.fixture
def client(manager):
    app = FastAPI()
    app.include_router(batch_routes.router, prefix="/api")
    return TestClient(app)


def _urls(n):
    return [f"https://www.youtube.com/watch?v={i:011d}" for i in range(n)]


def test_json_batch_over_limit_is_rejected(client, manager):
    r = client.post("/api/batch/download", json={"urls": _urls(501)})
    assert r.status_code == 422
    assert manager.calls == []


def test_uploaded_batch_over_limit_is_rejected(client, manager):
    body = "\n".join(_urls(batch_routes.MAX_BATCH_URLS + 1)).encode()
    r = client.post("/api/batch/upload", files={"file": ("urls.txt", body)})
    assert r.status_code == 413
    assert manager.calls == []


def test_batch_rows_are_written_off_the_event_loop(client, manager):
    r = client.post("/api/batch/download", json={"urls": _urls(3)})
    assert r.status_code == 200
    assert r.json()["total_jobs"] == 3
    assert manager.calls == [False]  # ran in a worker thread, not on the loop


class TestQueueDedupe:
    async def test_duplicates_are_skipped(self):
        queue = DownloadQueueManager(max_concurrent=1)
        await queue.enqueue("a")
        await queue.enqueue("a")
        await queue.enqueue("b")
        assert len(queue._queue) == 2

    async def test_job_can_be_requeued_after_dequeue_or_remove(self):
        queue = DownloadQueueManager(max_concurrent=1)
        await queue.enqueue("a", priority=9)
        await queue.enqueue("b")
        assert await queue._get_next_job() == "a"
        await queue.enqueue("a")
        assert await queue.remove("b")
        await queue.enqueue("b")
        assert sorted(jid for _, _, jid in queue._queue) == ["a", "b"]
        assert queue._queued_ids == {"a", "b"}
