"""Tests for the knowledge accessors on JobStore (P18 Phase A).

Each test gets a fresh on-disk SQLite DB via tmp_path so we exercise the same
path the real app does (no in-memory shortcuts).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.job_store import JobStore
from app.core.knowledge_schema import (
    EXTRACTION_VERSION,
    SCHEMA_VERSION,
    Claim,
    ClaimType,
    compute_claim_id,
)


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(db_path=tmp_path / "test_jobs.db")


def _make_claim(
    *,
    episode_id: str = "ep-1",
    text: str = "ETH may outperform BTC over the next 6 months",
    speaker: str = "Host A",
    timestamp_start: float = 12.5,
    timestamp_end: float = 18.0,
    claim_type: ClaimType = ClaimType.PREDICTION,
    confidence: float = 0.8,
) -> dict:
    cid = compute_claim_id(
        text=text,
        episode_id=episode_id,
        speaker=speaker,
        timestamp_start=timestamp_start,
    )
    c = Claim(
        claim_id=cid,
        episode_id=episode_id,
        text=text,
        speaker=speaker,
        timestamp_start=timestamp_start,
        timestamp_end=timestamp_end,
        claim_type=claim_type,
        confidence=confidence,
        evidence_excerpt=text,
        source_url="https://example.com/ep",
        extraction_version=EXTRACTION_VERSION,
        schema_version=SCHEMA_VERSION,
    )
    return c.model_dump(mode="json")


class TestKnowledgeStatus:
    def test_default_is_none_string(self, store: JobStore):
        # Need a job row to read status from
        from app.core.job_store import JobType

        store.create_job("j1", JobType.TRANSCRIBE, source_url="https://x")
        assert store.get_knowledge_status("j1") == "none"

    def test_set_and_read_status(self, store: JobStore):
        from app.core.job_store import JobType

        store.create_job("j1", JobType.TRANSCRIBE, source_url="https://x")
        store.set_knowledge_status("j1", "extracting")
        assert store.get_knowledge_status("j1") == "extracting"
        store.set_knowledge_status("j1", "complete")
        assert store.get_knowledge_status("j1") == "complete"

    def test_status_for_unknown_job_is_none(self, store: JobStore):
        assert store.get_knowledge_status("does-not-exist") is None


class TestClaimUpsert:
    def test_insert_and_read_back(self, store: JobStore):
        claim = _make_claim()
        n = store.upsert_claims([claim])
        assert n == 1

        rows = store.get_claims_for_job("ep-1")
        assert len(rows) == 1
        row = rows[0]
        assert row["claim_id"] == claim["claim_id"]
        assert row["text"] == claim["text"]
        assert row["speaker"] == "Host A"
        assert row["claim_type"] == "prediction"
        assert row["confidence"] == pytest.approx(0.8)
        assert row["entity_ids"] == []
        assert row["topic_ids"] == []
        assert row["source_url"] == "https://example.com/ep"

    def test_upsert_is_idempotent(self, store: JobStore):
        claim = _make_claim()
        store.upsert_claims([claim])
        store.upsert_claims([claim])
        store.upsert_claims([claim])
        assert len(store.get_claims_for_job("ep-1")) == 1

    def test_upsert_updates_existing(self, store: JobStore):
        claim = _make_claim(confidence=0.5)
        store.upsert_claims([claim])
        # Same claim_id (same text/episode/speaker/timestamp), new confidence
        claim["confidence"] = 0.95
        store.upsert_claims([claim])
        rows = store.get_claims_for_job("ep-1")
        assert len(rows) == 1
        assert rows[0]["confidence"] == pytest.approx(0.95)

    def test_min_confidence_filter(self, store: JobStore):
        store.upsert_claims(
            [
                _make_claim(text="weak", timestamp_start=1.0, confidence=0.2),
                _make_claim(text="strong", timestamp_start=2.0, confidence=0.9),
            ]
        )
        all_rows = store.get_claims_for_job("ep-1")
        assert len(all_rows) == 2
        filtered = store.get_claims_for_job("ep-1", min_confidence=0.5)
        assert len(filtered) == 1
        assert filtered[0]["text"] == "strong"

    def test_ordered_by_timestamp_ascending(self, store: JobStore):
        store.upsert_claims(
            [
                _make_claim(text="late", timestamp_start=99.0),
                _make_claim(text="early", timestamp_start=1.0),
                _make_claim(text="mid", timestamp_start=50.0),
            ]
        )
        rows = store.get_claims_for_job("ep-1")
        assert [r["text"] for r in rows] == ["early", "mid", "late"]

    def test_delete_claims_for_job(self, store: JobStore):
        store.upsert_claims(
            [
                _make_claim(episode_id="ep-1", text="a", timestamp_start=1.0),
                _make_claim(episode_id="ep-1", text="b", timestamp_start=2.0),
                _make_claim(episode_id="ep-2", text="c", timestamp_start=3.0),
            ]
        )
        deleted = store.delete_claims_for_job("ep-1")
        assert deleted == 2
        assert store.get_claims_for_job("ep-1") == []
        # ep-2 untouched
        assert len(store.get_claims_for_job("ep-2")) == 1


class TestQueryClaims:
    def test_filter_by_type(self, store: JobStore):
        store.upsert_claims(
            [
                _make_claim(
                    text="forecast",
                    timestamp_start=1.0,
                    claim_type=ClaimType.PREDICTION,
                ),
                _make_claim(
                    text="opinion-y",
                    timestamp_start=2.0,
                    claim_type=ClaimType.OPINION,
                ),
            ]
        )
        rows = store.query_claims(claim_type="prediction")
        assert len(rows) == 1
        assert rows[0]["text"] == "forecast"

    def test_filter_by_speaker(self, store: JobStore):
        store.upsert_claims(
            [
                _make_claim(text="from-host", timestamp_start=1.0, speaker="Host A"),
                _make_claim(
                    text="from-guest", timestamp_start=2.0, speaker="Guest B"
                ),
            ]
        )
        rows = store.query_claims(speaker="Host A")
        assert {r["text"] for r in rows} == {"from-host"}

    def test_pagination(self, store: JobStore):
        store.upsert_claims(
            [
                _make_claim(text=f"c{i}", timestamp_start=float(i))
                for i in range(5)
            ]
        )
        page1 = store.query_claims(limit=2, offset=0)
        page2 = store.query_claims(limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2
        assert {r["text"] for r in page1}.isdisjoint({r["text"] for r in page2})


class TestExtractionFailures:
    def test_record_failure(self, store: JobStore):
        store.record_extraction_failure(
            episode_id="ep-1",
            chunk_index=3,
            error="JSON parse error",
            raw_output="{not json",
            extraction_version=1,
            model="gpt-4o-mini",
        )
        # Read directly via the store's connection helper
        with store._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM extraction_failures WHERE episode_id = ?",
                ("ep-1",),
            ).fetchall()
        assert len(rows) == 1
        assert rows[0]["chunk_index"] == 3
        assert "JSON parse error" in rows[0]["error"]


class TestReplaceClaimsForJob:
    """Atomicity smoke tests for the delete+insert single-transaction path."""

    def test_replaces_existing_claims(self, store: JobStore):
        store.upsert_claims(
            [
                _make_claim(text="old1", timestamp_start=1.0),
                _make_claim(text="old2", timestamp_start=2.0),
            ]
        )
        n = store.replace_claims_for_job(
            "ep-1",
            [_make_claim(text="new1", timestamp_start=10.0)],
        )
        assert n == 1
        rows = store.get_claims_for_job("ep-1")
        assert {r["text"] for r in rows} == {"new1"}

    def test_replace_with_empty_list_clears(self, store: JobStore):
        store.upsert_claims([_make_claim(text="will-be-cleared", timestamp_start=1.0)])
        n = store.replace_claims_for_job("ep-1", [])
        assert n == 0
        assert store.get_claims_for_job("ep-1") == []

    def test_does_not_touch_other_episodes(self, store: JobStore):
        store.upsert_claims(
            [
                _make_claim(episode_id="ep-1", text="a", timestamp_start=1.0),
                _make_claim(episode_id="ep-2", text="b", timestamp_start=2.0),
            ]
        )
        store.replace_claims_for_job(
            "ep-1", [_make_claim(episode_id="ep-1", text="c", timestamp_start=3.0)]
        )
        ep2 = store.get_claims_for_job("ep-2")
        assert {r["text"] for r in ep2} == {"b"}


class TestEntityStore:
    """Phase B: entity + mention CRUD and dual-ID lookup."""

    def _make_entity(self, *, entity_id: str = "ent_aaaaaaaa", slug: str = "person:alice", name: str = "Alice") -> dict:
        return {
            "entity_id": entity_id,
            "slug": slug,
            "name": name,
            "entity_type": "person",
            "aliases": [name],
            "confidence": 0.9,
        }

    def test_upsert_and_get_by_id(self, store: JobStore):
        store.upsert_entity(self._make_entity())
        row = store.get_entity_by_id("ent_aaaaaaaa")
        assert row is not None
        assert row["name"] == "Alice"
        assert row["aliases"] == ["Alice"]

    def test_get_by_slug(self, store: JobStore):
        store.upsert_entity(self._make_entity())
        row = store.get_entity_by_slug("person:alice")
        assert row is not None
        assert row["entity_id"] == "ent_aaaaaaaa"

    def test_upsert_merges_aliases(self, store: JobStore):
        e1 = self._make_entity()
        e1["aliases"] = ["Alice"]
        store.upsert_entity(e1)
        e2 = self._make_entity()
        e2["aliases"] = ["Alice", "Ali"]
        store.upsert_entity(e2)
        row = store.get_entity_by_id("ent_aaaaaaaa")
        assert set(row["aliases"]) == {"Alice", "Ali"}

    def test_slug_exists(self, store: JobStore):
        assert store.slug_exists("person:alice") is False
        store.upsert_entity(self._make_entity())
        assert store.slug_exists("person:alice") is True

    def test_list_and_filter(self, store: JobStore):
        store.upsert_entity(self._make_entity())
        store.upsert_entity(
            self._make_entity(
                entity_id="ent_bbbbbbbb", slug="company:openai", name="OpenAI"
            )
            | {"entity_type": "company"}
        )
        rows = store.list_entities(entity_type="company")
        assert len(rows) == 1
        assert rows[0]["slug"] == "company:openai"

    def test_find_entity_ids_by_type(self, store: JobStore):
        store.upsert_entity(self._make_entity())
        store.upsert_entity(
            self._make_entity(
                entity_id="ent_bbbbbbbb", slug="company:openai", name="OpenAI"
            )
            | {"entity_type": "company"}
        )
        ids = store.find_entity_ids_by_type("person")
        assert ids == ["ent_aaaaaaaa"]

    def test_mention_crud(self, store: JobStore):
        store.upsert_entity(self._make_entity())
        store.add_entity_mention(
            {
                "entity_id": "ent_aaaaaaaa",
                "episode_id": "ep-1",
                "claim_id": None,
                "chunk_id": "ep-1:chunk:0",
                "raw_text": "Alice",
                "start_char": 0,
                "end_char": 5,
                "timestamp": 1.0,
                "speaker": "Host",
            }
        )
        rows = store.get_mentions_for_entity("ent_aaaaaaaa")
        assert len(rows) == 1
        assert rows[0]["raw_text"] == "Alice"


class TestReplaceClaimsIncludesEntities:
    """Phase B: the transaction replaces claims AND entity mentions atomically."""

    def test_entities_upserted_alongside_claims(self, store: JobStore):
        entity = {
            "entity_id": "ent_aaaaaaaa",
            "slug": "person:alice",
            "name": "Alice",
            "entity_type": "person",
            "aliases": ["Alice"],
            "confidence": 0.9,
        }
        claim = _make_claim(text="Alice said hi", timestamp_start=1.0)
        claim["entity_ids"] = ["ent_aaaaaaaa"]
        mention = {
            "entity_id": "ent_aaaaaaaa",
            "episode_id": "ep-1",
            "claim_id": claim["claim_id"],
            "chunk_id": "ep-1:chunk:0",
            "raw_text": "Alice",
            "start_char": 0,
            "end_char": 5,
            "timestamp": 1.0,
            "speaker": None,
        }
        store.replace_claims_for_job("ep-1", [claim], entities=[entity], mentions=[mention])
        assert store.get_entity_by_id("ent_aaaaaaaa") is not None
        rows = store.get_claims_for_job("ep-1")
        assert rows[0]["entity_ids"] == ["ent_aaaaaaaa"]
        assert store.get_mentions_for_entity("ent_aaaaaaaa")

    def test_replacing_replaces_mentions_too(self, store: JobStore):
        """Second call must wipe prior episode mentions, not duplicate them."""
        entity = {
            "entity_id": "ent_aaaaaaaa",
            "slug": "person:alice",
            "name": "Alice",
            "entity_type": "person",
            "aliases": ["Alice"],
            "confidence": 0.9,
        }
        claim = _make_claim(text="Alice said hi", timestamp_start=1.0)
        mention = {
            "entity_id": "ent_aaaaaaaa",
            "episode_id": "ep-1",
            "claim_id": claim["claim_id"],
            "chunk_id": "ep-1:chunk:0",
            "raw_text": "Alice",
            "timestamp": 1.0,
        }
        store.replace_claims_for_job(
            "ep-1", [claim], entities=[entity], mentions=[mention]
        )
        store.replace_claims_for_job(
            "ep-1", [claim], entities=[entity], mentions=[mention]
        )
        # Still only one mention for this episode — second call replaced, not appended.
        rows = store.get_mentions_for_entity("ent_aaaaaaaa")
        assert len(rows) == 1


class TestTaskPresets:
    """get_task_presets / set_task_presets round-trip with api_key encryption."""

    def _seed_default_ai_settings(self, store: JobStore):
        # set_task_presets requires an existing default ai_settings row.
        now_iso = "2026-04-22T00:00:00"
        with store._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO ai_settings (provider, model, api_key, base_url,
                                         is_default, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?)
                """,
                ("openai", "gpt-4o-mini", None, None, now_iso, now_iso),
            )

    def test_empty_when_no_settings_row(self, store: JobStore):
        assert store.get_task_presets() == {}

    def test_round_trip_decrypts_api_key(self, store: JobStore):
        self._seed_default_ai_settings(store)
        store.set_task_presets(
            {
                "extract": {
                    "provider": "groq",
                    "model": "llama-3.1-8b-instant",
                    "api_key": "gsk-secret-value",
                }
            }
        )
        out = store.get_task_presets()
        assert "extract" in out
        # Decryption must recover the original plaintext
        assert out["extract"]["api_key"] == "gsk-secret-value"
        assert out["extract"]["provider"] == "groq"

    def test_raw_column_is_not_plaintext(self, store: JobStore):
        """The api_key in the raw JSON column must not equal the plaintext."""
        self._seed_default_ai_settings(store)
        store.set_task_presets(
            {"extract": {"provider": "openai", "model": "x", "api_key": "PLAIN"}}
        )
        with store._get_conn() as conn:
            row = conn.execute(
                "SELECT task_presets FROM ai_settings WHERE is_default = 1"
            ).fetchone()
        raw = row["task_presets"]
        # The plaintext must not appear in the stored JSON. (`enc:` or `b64:`
        # prefix is what the secret helpers emit.)
        assert "PLAIN" not in raw
        assert ("enc:" in raw) or ("b64:" in raw)

    def test_non_dict_preset_is_dropped(self, store: JobStore):
        self._seed_default_ai_settings(store)
        # Force a malformed entry directly into the column to test the
        # read-side filter.
        with store._get_conn() as conn:
            conn.execute(
                "UPDATE ai_settings SET task_presets = ? WHERE is_default = 1",
                ('{"extract": "not-a-dict", "summarize": {"provider": "ollama", "model": "llama3.2"}}',),
            )
        out = store.get_task_presets()
        assert "extract" not in out
        assert "summarize" in out

    def test_invalid_json_returns_empty(self, store: JobStore):
        self._seed_default_ai_settings(store)
        with store._get_conn() as conn:
            conn.execute(
                "UPDATE ai_settings SET task_presets = ? WHERE is_default = 1",
                ("{not valid json",),
            )
        assert store.get_task_presets() == {}
