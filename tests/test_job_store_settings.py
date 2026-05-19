"""Tests for the settings mixin on JobStore.

Task presets are covered separately by ``test_llm_presets.py``; these
tests focus on AI and Obsidian settings, especially the
encryption-at-rest round-trip for API keys.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.core.job_store import JobStore


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(db_path=tmp_path / "jobs.db")


class TestAISettings:
    def test_get_unconfigured_returns_none(self, store: JobStore):
        assert store.get_ai_settings() is None

    def test_save_then_get_round_trips(self, store: JobStore):
        store.save_ai_settings(
            provider="openai",
            model="gpt-4o-mini",
            api_key="sk-secret",
            base_url=None,
        )
        s = store.get_ai_settings()
        assert s["provider"] == "openai"
        assert s["model"] == "gpt-4o-mini"
        # Decrypted on the way out
        assert s["api_key"] == "sk-secret"

    def test_save_updates_existing_row(self, store: JobStore):
        store.save_ai_settings(provider="openai", model="gpt-4o-mini", api_key="k1")
        store.save_ai_settings(provider="anthropic", model="claude-opus-4-7", api_key="k2")
        s = store.get_ai_settings()
        assert s["provider"] == "anthropic"
        assert s["api_key"] == "k2"
        # Only one default row exists — assert via raw SQL.
        with sqlite3.connect(str(store.db_path)) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM ai_settings WHERE is_default = 1"
            ).fetchone()[0]
        assert count == 1

    def test_api_key_not_plaintext_at_rest(self, store: JobStore):
        # Critical: dumping the SQLite file must not yield usable creds.
        store.save_ai_settings(
            provider="openai",
            model="gpt-4o-mini",
            api_key="sk-very-secret-key",
        )
        with sqlite3.connect(str(store.db_path)) as conn:
            raw = conn.execute("SELECT api_key FROM ai_settings").fetchone()[0]
        # Stored value must be prefixed (enc: or b64:) — never the raw key.
        assert raw != "sk-very-secret-key"
        assert raw.startswith(("enc:", "b64:"))

    def test_empty_api_key_stored_as_null(self, store: JobStore):
        store.save_ai_settings(provider="ollama", model="llama3.2", api_key=None)
        with sqlite3.connect(str(store.db_path)) as conn:
            raw = conn.execute("SELECT api_key FROM ai_settings").fetchone()[0]
        assert raw is None


class TestObsidianSettings:
    def test_get_unconfigured_returns_none(self, store: JobStore):
        assert store.get_obsidian_settings() is None

    def test_save_then_get_with_tags_list(self, store: JobStore):
        store.save_obsidian_settings(
            vault_path="/tmp/vault",
            subfolder="Sift",
            template=None,
            default_tags=["sift", "podcast", "knowledge"],
        )
        s = store.get_obsidian_settings()
        assert s["vault_path"] == "/tmp/vault"
        assert s["subfolder"] == "Sift"
        # Tags round-trip as a list (stored as CSV internally)
        assert s["default_tags"] == ["sift", "podcast", "knowledge"]

    def test_default_tags_when_none_provided(self, store: JobStore):
        store.save_obsidian_settings(vault_path="/tmp/v")
        s = store.get_obsidian_settings()
        assert s["default_tags"] == ["sift", "transcript"]

    def test_save_updates_existing_row(self, store: JobStore):
        store.save_obsidian_settings(vault_path="/path/a")
        store.save_obsidian_settings(vault_path="/path/b", subfolder="Notes")
        s = store.get_obsidian_settings()
        assert s["vault_path"] == "/path/b"
        assert s["subfolder"] == "Notes"
