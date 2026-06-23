"""Tests for the P21 export API (app/api/export_routes.py)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.export_routes import router as export_router
from app.config import get_settings
from app.core import job_store as job_store_module
from app.core.job_store import JobStore
from app.core.job_store._enums import JobType


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> JobStore:
    s = JobStore(db_path=tmp_path / "export.db")
    monkeypatch.setattr(job_store_module, "_job_store", s)
    # Allow writing into tmp_path by making it the (scope-validated) download dir.
    monkeypatch.setattr(get_settings(), "download_dir", str(tmp_path))
    return s


@pytest.fixture
def client(store: JobStore) -> TestClient:
    app = FastAPI()
    app.include_router(export_router)
    return TestClient(app)


def _episode(store: JobStore, job_id="j1"):
    store.create_job(job_id, JobType.TRANSCRIBE, source_url="https://youtube.com/watch?v=x")
    store.update_job(
        job_id,
        content_info={"title": "My Episode"},
        transcription_result={
            "language": "en",
            "segments": [{"start": 5.0, "end": 9.0, "text": "hello", "speaker": "A"}],
        },
    )
    store.replace_claims_for_job(
        job_id,
        [{
            "claim_id": "c1", "episode_id": job_id, "text": "big claim",
            "timestamp_start": 5.0, "timestamp_end": 9.0, "claim_type": "fact",
            "confidence": 0.9, "evidence_excerpt": "hello", "entity_ids": [],
            "topic_ids": [], "extraction_version": 1, "schema_version": 1,
        }],
    )


class TestTemplatesList:
    def test_lists_templates_and_targets(self, client):
        r = client.get("/export-templates")
        assert r.status_code == 200
        body = r.json()
        assert {t["id"] for t in body["templates"]} >= {"episode", "highlights"}
        assert "obsidian" in body["targets"] and "logseq" in body["targets"]


class TestExport:
    def test_preview_returns_content_without_writing(self, client, store):
        _episode(store)
        r = client.post("/jobs/j1/export", json={"write": False, "template": "episode"})
        assert r.status_code == 200
        body = r.json()
        assert body["written"] is False
        assert "# My Episode" in body["content"]
        assert body["file_path"] is None

    def test_write_to_vault(self, client, store, tmp_path):
        _episode(store)
        vault = tmp_path / "vault"
        vault.mkdir()
        r = client.post(
            "/jobs/j1/export",
            json={"write": True, "target": "obsidian", "vault_path": str(vault), "subfolder": "Sift"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["written"] is True
        written = Path(body["file_path"])
        assert written.exists()
        assert "[[" in written.read_text() or "**" in written.read_text()

    def test_highlights_template(self, client, store):
        _episode(store)
        r = client.post("/jobs/j1/export", json={"write": False, "template": "highlights"})
        assert r.status_code == 200
        assert "Highlights" in r.json()["content"]

    def test_unknown_job_404(self, client):
        r = client.post("/jobs/ghost/export", json={"write": False})
        assert r.status_code == 404

    def test_no_transcription_400(self, client, store):
        store.create_job("j2", JobType.TRANSCRIBE)
        r = client.post("/jobs/j2/export", json={"write": False})
        assert r.status_code == 400

    def test_topic_template_rejected_on_job(self, client, store):
        _episode(store)
        r = client.post("/jobs/j1/export", json={"write": False, "template": "topic"})
        assert r.status_code == 400

    def test_write_without_vault_or_config_400(self, client, store):
        _episode(store)
        # write=True, no vault_path, no configured Obsidian vault
        r = client.post("/jobs/j1/export", json={"write": True})
        assert r.status_code == 400
        assert "vault" in r.json()["detail"].lower()

    def test_vault_scope_rejected_outside_allowed_roots(self, client, store):
        _episode(store)
        r = client.post("/jobs/j1/export", json={"write": True, "vault_path": "/etc"})
        assert r.status_code == 400
