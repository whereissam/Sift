"""The live canary list stays in step with the platform registry.

Offline: this runs in the normal suite, so adding a platform without a canary
(or checking in a canary its own adapter rejects) fails CI immediately rather
than going unnoticed by the daily live run.
"""

from sift_core import Platform
from sift_core.platforms import DOWNLOADERS

from tests.live.canaries import CANARIES


def test_every_platform_has_exactly_one_canary():
    platforms = [c.platform for c in CANARIES]
    assert sorted(platforms, key=lambda p: p.value) == sorted(Platform, key=lambda p: p.value)


def test_canary_urls_are_accepted_by_their_adapter():
    adapters = {cls.PLATFORM: cls for cls in DOWNLOADERS}
    for canary in CANARIES:
        if canary.url:
            assert adapters[canary.platform].can_handle_url(canary.url), canary


def test_youtube_skips_on_ci_without_cookies_but_runs_locally():
    canary = next(c for c in CANARIES if c.platform is Platform.YOUTUBE)
    assert canary.skip_reason({}) is None
    assert "bot-checks CI" in canary.skip_reason({"CI": "true"})
    assert canary.skip_reason({"CI": "true", "YOUTUBE_COOKIES_FILE": "/tmp/c.txt"}) is None


def test_auth_gated_canary_skips_everywhere_without_credentials():
    canary = next(c for c in CANARIES if c.platform is Platform.INSTAGRAM)
    assert "needs one of" in canary.skip_reason({})
    assert canary.skip_reason({"INSTAGRAM_COOKIES_FILE": "/tmp/c.txt"}) is None


def test_env_var_overrides_the_checked_in_url(monkeypatch):
    canary = next(c for c in CANARIES if c.platform is Platform.SPOTIFY)
    assert canary.resolved_url is None
    monkeypatch.setenv("SIFT_CANARY_SPOTIFY", "https://open.spotify.com/episode/abc")
    assert canary.resolved_url == "https://open.spotify.com/episode/abc"
