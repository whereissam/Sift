"""Slice 1 tests: asset identity — canonicalization, find-or-create,
job linkage, and the legacy-database backfill migration."""

import sqlite3
import threading
from datetime import datetime

import pytest

import app.store as job_store_pkg
from sift_core.asset_identity import (
    canonical_source_for_job,
    canonicalize_url,
    fingerprint_file,
)
from app.store import JobType


# ---------------------------------------------------------------------------
# URL canonicalization
# ---------------------------------------------------------------------------

YOUTUBE_VARIANTS = [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtube.com/watch?v=dQw4w9WgXcQ&t=42",
    "https://youtu.be/dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ?si=SHARE_TRACKING",
    "https://www.youtube.com/shorts/dQw4w9WgXcQ",
    "https://www.youtube.com/embed/dQw4w9WgXcQ",
    "https://m.youtube.com/watch?v=dQw4w9WgXcQ&utm_source=share",
    "https://www.youtube.com/live/dQw4w9WgXcQ",
]


def test_youtube_variants_share_one_canonical_source():
    canonicals = {canonicalize_url(u).canonical_source for u in YOUTUBE_VARIANTS}
    assert canonicals == {"youtube:video:dQw4w9WgXcQ"}
    assert canonicalize_url(YOUTUBE_VARIANTS[0]).platform == "youtube"


def test_different_youtube_videos_stay_distinct():
    a = canonicalize_url("https://youtu.be/dQw4w9WgXcQ")
    b = canonicalize_url("https://youtu.be/aaaaaaaaaaa")
    assert a.canonical_source != b.canonical_source
    assert a.fingerprint != b.fingerprint


def test_generic_normalization_conservative():
    a = canonicalize_url(
        "HTTPS://Example.com:443/Podcast/Ep1/?b=2&a=1&utm_source=x&fbclid=y#frag"
    )
    # Fragment gone, tracking gone, params sorted, host lowered, port dropped,
    # trailing slash trimmed — but path case and unknown params preserved.
    assert a.canonical_source == "https://example.com/Podcast/Ep1?a=1&b=2"


def test_unknown_params_are_preserved():
    a = canonicalize_url("https://example.com/watch?episode=5")
    b = canonicalize_url("https://example.com/watch?episode=6")
    assert a.canonical_source != b.canonical_source


def test_generic_t_param_is_kept():
    # t= is only tracking on x.com/twitter.com; elsewhere it can select content.
    a = canonicalize_url("https://example.com/v?t=120")
    assert "t=120" in a.canonical_source


def test_x_share_tokens_dropped():
    a = canonicalize_url("https://x.com/user/status/123?s=20&t=AbCdEf")
    b = canonicalize_url("https://x.com/user/status/123")
    assert a.canonical_source == b.canonical_source


def test_canonical_source_for_job_pseudo_urls():
    assert canonical_source_for_job("resume://audio.m4a") is None
    assert canonical_source_for_job(None) is None
    upload = canonical_source_for_job("upload://file.mp3")
    assert upload.canonical_source == "upload:legacy:upload://file.mp3"
    hashed = canonical_source_for_job("upload://file.mp3", content_sha256="ab" * 32)
    assert hashed.canonical_source == f"upload:sha256:{'ab' * 32}"


def test_fingerprint_file_ignores_filename(tmp_path):
    f1 = tmp_path / "a.mp3"
    f2 = tmp_path / "b.mp3"
    f1.write_bytes(b"same bytes")
    f2.write_bytes(b"same bytes")
    assert fingerprint_file(f1).canonical_source == fingerprint_file(f2).canonical_source


# ---------------------------------------------------------------------------
# Store integration
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path, monkeypatch):
    s = job_store_pkg.JobStore(db_path=tmp_path / "jobs.db")
    monkeypatch.setattr(job_store_pkg, "_job_store", s)
    return s


def test_same_url_one_asset_two_jobs(store):
    j1 = store.create_job("j1", JobType.DOWNLOAD, source_url="https://youtu.be/dQw4w9WgXcQ")
    j2 = store.create_job(
        "j2", JobType.DOWNLOAD, source_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    )
    assert j1["asset_id"] is not None
    assert j1["asset_id"] == j2["asset_id"]
    assert j1["job_id"] != j2["job_id"]

    asset = store.get_asset(j1["asset_id"])
    assert asset["canonical_source"] == "youtube:video:dQw4w9WgXcQ"
    assert asset["platform"] == "youtube"
    assert len(store.get_asset_jobs(j1["asset_id"])) == 2


def test_upload_hash_asset_identity(store):
    j1 = store.create_job(
        "u1", JobType.TRANSCRIBE, source_url="upload://a.mp3", content_sha256="cd" * 32
    )
    j2 = store.create_job(
        "u2", JobType.TRANSCRIBE, source_url="upload://b.mp3", content_sha256="cd" * 32
    )
    assert j1["asset_id"] == j2["asset_id"]
    assert store.get_asset(j1["asset_id"])["source_type"] == "upload"


def test_explicit_asset_id_inherited(store):
    j1 = store.create_job("d1", JobType.DOWNLOAD, source_url="https://youtu.be/dQw4w9WgXcQ")
    j2 = store.create_job("t1", JobType.TRANSCRIBE, asset_id=j1["asset_id"])
    assert j2["asset_id"] == j1["asset_id"]


def test_resume_pseudo_source_has_no_asset(store):
    job = store.create_job("r1", JobType.TRANSCRIBE, source_url="resume://audio.m4a")
    assert job["asset_id"] is None


def test_get_asset_for_episode_bridge(store):
    job = store.create_job("e1", JobType.TRANSCRIBE, source_url="https://youtu.be/dQw4w9WgXcQ")
    assert store.get_asset_for_episode("e1") == job["asset_id"]
    assert store.get_asset_for_episode("missing") is None


def test_find_or_create_concurrent_single_row(store):
    source = canonicalize_url("https://youtu.be/dQw4w9WgXcQ")
    results = []

    def worker():
        results.append(store.find_or_create_asset(source))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(set(results)) == 1
    with store._get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
    assert count == 1


# ---------------------------------------------------------------------------
# Backfill of a pre-migration database
# ---------------------------------------------------------------------------

_LEGACY_JOBS_DDL = """
CREATE TABLE jobs (
    job_id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL,
    source_url TEXT,
    platform TEXT,
    raw_file_path TEXT,
    converted_file_path TEXT,
    output_format TEXT,
    quality TEXT,
    model_size TEXT,
    language TEXT,
    transcription_format TEXT,
    content_info TEXT,
    transcription_result TEXT,
    file_size_mb REAL,
    error TEXT,
    progress REAL DEFAULT 0.0,
    last_checkpoint TEXT,
    priority INTEGER DEFAULT 5,
    batch_id TEXT,
    scheduled_at TEXT,
    webhook_url TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
)
"""


def _make_legacy_db(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.execute(_LEGACY_JOBS_DDL)
    now = datetime.utcnow().isoformat()
    rows = [
        ("old-1", "download", "completed", "https://youtu.be/dQw4w9WgXcQ"),
        ("old-2", "transcribe", "completed", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        ("old-3", "download", "completed", "https://example.com/ep.mp3"),
        ("old-4", "transcribe", "completed", "upload://old-file.mp3"),
        ("old-5", "transcribe", "failed", "resume://broken.m4a"),
        ("old-6", "transcribe", "completed", None),
    ]
    for job_id, job_type, status, url in rows:
        conn.execute(
            "INSERT INTO jobs (job_id, job_type, status, source_url, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, job_type, status, url, now, now),
        )
    conn.commit()
    conn.close()


def test_backfill_links_legacy_jobs(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.db"
    _make_legacy_db(db_path)

    store = job_store_pkg.JobStore(db_path=db_path)
    monkeypatch.setattr(job_store_pkg, "_job_store", store)

    # Pre-migration backup was taken.
    backups = list((tmp_path / "backups").glob("pre_migration_*.db"))
    assert len(backups) == 1

    # Same video → one shared asset; other URL and upload get their own.
    j1, j2 = store.get_job("old-1"), store.get_job("old-2")
    assert j1["asset_id"] is not None
    assert j1["asset_id"] == j2["asset_id"]
    assert store.get_job("old-3")["asset_id"] not in (None, j1["asset_id"])
    upload_asset = store.get_asset(store.get_job("old-4")["asset_id"])
    assert upload_asset["canonical_source"].startswith("upload:legacy:")

    # Pseudo/absent sources stay unlinked.
    assert store.get_job("old-5")["asset_id"] is None
    assert store.get_job("old-6")["asset_id"] is None

    # No job data lost.
    with store._get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 6
        asset_count = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
    assert asset_count == 3


def test_backfill_is_idempotent(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.db"
    _make_legacy_db(db_path)

    store1 = job_store_pkg.JobStore(db_path=db_path)
    first_asset = store1.get_job("old-1")["asset_id"]

    # Reopen: migration re-runs, backfill marker short-circuits, links stable.
    store2 = job_store_pkg.JobStore(db_path=db_path)
    assert store2.get_job("old-1")["asset_id"] == first_asset
    with store2._get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 3

    # Second open must not create a second backup (assets table exists now).
    backups = list((tmp_path / "backups").glob("pre_migration_*.db"))
    assert len(backups) == 1


# ---------------------------------------------------------------------------
# Endpoint-level: same URL twice → same asset in API responses
# ---------------------------------------------------------------------------

def test_download_endpoint_shares_asset_for_same_url(store, tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api import auth as auth_module
    from app.api import download_routes
    from app.api.ratelimit import limiter
    from sift_core.base import Platform as CorePlatform

    class _NoAuth:
        api_key = None

    monkeypatch.setattr(auth_module, "get_settings", lambda: _NoAuth())

    media = tmp_path / "out.m4a"
    media.write_bytes(b"fake")

    class FakeResult:
        success = True
        file_path = media
        metadata = None
        error = None

    class FakeDownloader:
        async def download(self, url, output_format, quality):
            return FakeResult()

    monkeypatch.setattr(
        download_routes.DownloaderFactory,
        "detect_platform",
        staticmethod(lambda url: CorePlatform.YOUTUBE),
    )
    monkeypatch.setattr(
        download_routes.DownloaderFactory,
        "get_downloader",
        staticmethod(lambda url: FakeDownloader()),
    )

    api = FastAPI()
    api.state.limiter = limiter
    api.include_router(download_routes.router, prefix="/api")
    client = TestClient(api)

    r1 = client.post("/api/download", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
    r2 = client.post(
        "/api/download", json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=9"}
    )
    assert r1.status_code == r2.status_code == 200

    s1 = client.get(f"/api/download/{r1.json()['job_id']}").json()
    s2 = client.get(f"/api/download/{r2.json()['job_id']}").json()
    assert s1["asset_id"] is not None
    assert s1["asset_id"] == s2["asset_id"]
    assert s1["job_id"] != s2["job_id"]
