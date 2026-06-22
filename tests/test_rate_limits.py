"""Expensive endpoints enforce a per-route rate limit."""

import pytest
from fastapi.testclient import TestClient

from app.api.ratelimit import limiter
from app.main import app


@pytest.fixture
def client():
    # Reset the shared limiter before and after so this test neither inherits
    # nor leaks rate-limit state across the suite.
    limiter.reset()
    yield TestClient(app)
    limiter.reset()


def test_download_endpoint_rate_limited(client):
    """The 11th call within the window is rejected with 429 (limit is 10/min)."""
    statuses = [
        client.post(
            "/api/download",
            json={"url": "https://example.invalid/not-a-real-platform"},
        ).status_code
        for _ in range(12)
    ]
    # Earlier calls fail platform detection (400) but still count toward the
    # limit; once the limit is exceeded we must see a 429.
    assert 429 in statuses, statuses
    # And the limit should kick in around the 11th request, not immediately.
    assert statuses[:10].count(429) == 0, statuses
