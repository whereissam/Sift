"""Tests for the Sift MCP tool surface (app/mcp_server/server.py).

Tools are driven through ``FastMCP.call_tool`` against an injected fake client,
so we cover tool registration, response shaping, the per-episode compositions
(entities / topics / predictions built from claims), 202-pending handling, and
mode validation — without HTTP.
"""

from __future__ import annotations

import json

import pytest

from app.mcp_server import build_server
from app.mcp_server.config import MCPConfig


def _parse(result) -> dict:
    """call_tool returns list[TextContent]; pull the JSON payload."""
    assert result, "tool returned no content"
    return json.loads(result[0].text)


class FakeSift:
    """Configurable stand-in for SiftClient. Records calls; returns canned data."""

    def __init__(self, **overrides):
        self.overrides = overrides
        self.calls: list[tuple] = []

    async def transcribe(self, *, url=None, job_id=None, language=None, diarize=False):
        self.calls.append(("transcribe", url, diarize))
        return {"job_id": "ep1", "status": "processing", "progress": 0.1}

    async def get_transcription(self, job_id):
        return self.overrides.get(
            "transcription",
            {
                "status": "completed",
                "language": "en",
                "duration_seconds": 12.0,
                "text": "hello world",
                "formatted_output": "1\n00:00 hello",
                "output_format": "srt",
                "segments": [
                    {"start": 0.0, "end": 5.0, "text": "hello"},
                    {"start": 5.0, "end": 10.0, "text": "world"},
                ],
            },
        )

    async def summarize(self, job_id, summary_type):
        self.calls.append(("summarize", job_id, summary_type))
        return {"summary_type": summary_type, "content": f"summary:{summary_type}"}

    async def get_clips(self, job_id):
        return self.overrides.get("clips", {"clips": []})

    async def get_knowledge(self, job_id, *, min_confidence=0.5):
        return self.overrides.get("knowledge", (200, {"claim_count": 0, "claims": []}))

    async def get_entity(self, id_or_slug):
        if id_or_slug in self.overrides.get("missing_entities", ()):
            raise RuntimeError("404")
        return {"entity_id": id_or_slug, "name": id_or_slug.upper()}

    async def get_topic(self, topic_id):
        return {"topic_id": topic_id, "name": topic_id.upper()}

    async def get_prediction(self, claim_id):
        return {"claim_id": claim_id, "resolution": "pending"}

    async def export_job(self, job_id, body):
        self.calls.append(("export_job", job_id, body))
        return {"success": True, "written": body.get("write") is not False,
                "template": body.get("template"), "target": body.get("target")}


def _server(fake: FakeSift):
    return build_server(MCPConfig(api_url="http://x"), client=fake)


class TestRegistration:
    @pytest.mark.asyncio
    async def test_expected_tools_registered(self):
        m = _server(FakeSift())
        names = {t.name for t in await m.list_tools()}
        assert names == {
            "ingest_url", "get_transcript", "get_segment", "get_summary",
            "get_chapters", "get_clips", "get_highlights", "get_claims",
            "get_entities", "get_topics", "get_predictions", "export_to_vault",
        }

    @pytest.mark.asyncio
    async def test_deferred_tools_absent(self):
        m = _server(FakeSift())
        names = {t.name for t in await m.list_tools()}
        for absent in ("ask_episode", "search_library", "compare_episodes", "summarize_trend"):
            assert absent not in names


class TestTranscriptTools:
    @pytest.mark.asyncio
    async def test_ingest_url_returns_episode_id(self):
        fake = FakeSift()
        m = _server(fake)
        out = _parse(await m.call_tool("ingest_url", {"url": "https://x.com/ep"}))
        assert out["episode_id"] == "ep1"
        assert fake.calls[0][0] == "transcribe"

    @pytest.mark.asyncio
    async def test_get_transcript_text_default(self):
        m = _server(FakeSift())
        out = _parse(await m.call_tool("get_transcript", {"episode_id": "ep1"}))
        assert out["text"] == "hello world"
        assert "segments" not in out

    @pytest.mark.asyncio
    async def test_get_transcript_json_returns_segments(self):
        m = _server(FakeSift())
        out = _parse(
            await m.call_tool("get_transcript", {"episode_id": "ep1", "format": "json"})
        )
        assert len(out["segments"]) == 2

    @pytest.mark.asyncio
    async def test_get_segment_slices_by_time(self):
        m = _server(FakeSift())
        out = _parse(
            await m.call_tool("get_segment", {"episode_id": "ep1", "start": 0.0, "end": 4.0})
        )
        # Only the first segment overlaps [0, 4].
        assert out["text"] == "hello"
        assert len(out["segments"]) == 1


class TestSummaryTools:
    @pytest.mark.asyncio
    async def test_get_summary_passes_mode(self):
        fake = FakeSift()
        m = _server(fake)
        out = _parse(await m.call_tool("get_summary", {"episode_id": "ep1", "mode": "full"}))
        assert out["content"] == "summary:full"

    @pytest.mark.asyncio
    async def test_get_summary_rejects_unknown_mode(self):
        m = _server(FakeSift())
        with pytest.raises(Exception):
            await m.call_tool("get_summary", {"episode_id": "ep1", "mode": "bogus"})

    @pytest.mark.asyncio
    async def test_get_chapters_uses_chapters_mode(self):
        fake = FakeSift()
        m = _server(fake)
        out = _parse(await m.call_tool("get_chapters", {"episode_id": "ep1"}))
        assert out["content"] == "summary:chapters"

    @pytest.mark.asyncio
    async def test_get_highlights_from_clips_ranked(self):
        fake = FakeSift(
            clips={
                "clips": [
                    {"start_time": 0, "end_time": 5, "transcript_text": "lo", "viral_score": 0.3},
                    {"start_time": 5, "end_time": 9, "transcript_text": "hi", "viral_score": 0.9},
                ]
            }
        )
        m = _server(fake)
        out = _parse(await m.call_tool("get_highlights", {"episode_id": "ep1"}))
        assert [h["quote"] for h in out["highlights"]] == ["hi", "lo"]  # sorted by score

    @pytest.mark.asyncio
    async def test_get_highlights_empty_has_message(self):
        m = _server(FakeSift(clips={"clips": []}))
        out = _parse(await m.call_tool("get_highlights", {"episode_id": "ep1"}))
        assert out["highlights"] == []
        assert "message" in out


class TestKnowledgeTools:
    @pytest.mark.asyncio
    async def test_get_claims_returns_claims(self):
        claims = [{"claim_id": "c1", "text": "x", "claim_type": "fact",
                   "entity_ids": [], "topic_ids": []}]
        m = _server(FakeSift(knowledge=(200, {"claim_count": 1, "claims": claims})))
        out = _parse(await m.call_tool("get_claims", {"episode_id": "ep1"}))
        assert out["claim_count"] == 1

    @pytest.mark.asyncio
    async def test_get_claims_pending_202(self):
        m = _server(FakeSift(knowledge=(202, {"run_state": "running"})))
        out = _parse(await m.call_tool("get_claims", {"episode_id": "ep1"}))
        assert out["status"] == "pending"
        assert out["run_state"] == "running"

    @pytest.mark.asyncio
    async def test_get_entities_composes_and_dedups(self):
        claims = [
            {"claim_id": "c1", "claim_type": "fact", "entity_ids": ["e1", "e2"], "topic_ids": []},
            {"claim_id": "c2", "claim_type": "fact", "entity_ids": ["e2"], "topic_ids": []},
        ]
        m = _server(FakeSift(knowledge=(200, {"claims": claims})))
        out = _parse(await m.call_tool("get_entities", {"episode_id": "ep1"}))
        # e1, e2 fetched once each (e2 deduped).
        assert [e["entity_id"] for e in out["entities"]] == ["e1", "e2"]

    @pytest.mark.asyncio
    async def test_get_entities_skips_missing(self):
        claims = [{"claim_id": "c1", "claim_type": "fact", "entity_ids": ["e1", "gone"], "topic_ids": []}]
        m = _server(FakeSift(knowledge=(200, {"claims": claims}), missing_entities=("gone",)))
        out = _parse(await m.call_tool("get_entities", {"episode_id": "ep1"}))
        assert [e["entity_id"] for e in out["entities"]] == ["e1"]

    @pytest.mark.asyncio
    async def test_get_topics_composes(self):
        claims = [{"claim_id": "c1", "claim_type": "fact", "entity_ids": [], "topic_ids": ["t1"]}]
        m = _server(FakeSift(knowledge=(200, {"claims": claims})))
        out = _parse(await m.call_tool("get_topics", {"episode_id": "ep1"}))
        assert out["topics"][0]["topic_id"] == "t1"

    @pytest.mark.asyncio
    async def test_get_predictions_filters_prediction_claims(self):
        claims = [
            {"claim_id": "c1", "claim_type": "fact", "entity_ids": [], "topic_ids": []},
            {"claim_id": "c2", "claim_type": "prediction", "entity_ids": [], "topic_ids": []},
        ]
        m = _server(FakeSift(knowledge=(200, {"claims": claims})))
        out = _parse(await m.call_tool("get_predictions", {"episode_id": "ep1"}))
        assert [p["claim_id"] for p in out["predictions"]] == ["c2"]

    @pytest.mark.asyncio
    async def test_get_topics_pending_202(self):
        m = _server(FakeSift(knowledge=(202, {"run_state": "pending"})))
        out = _parse(await m.call_tool("get_topics", {"episode_id": "ep1"}))
        assert out["status"] == "pending"


class TestExportTool:
    @pytest.mark.asyncio
    async def test_export_to_vault_registered(self):
        m = _server(FakeSift())
        names = {t.name for t in await m.list_tools()}
        assert "export_to_vault" in names

    @pytest.mark.asyncio
    async def test_export_writes_by_default(self):
        fake = FakeSift()
        m = _server(fake)
        out = _parse(await m.call_tool(
            "export_to_vault", {"episode_id": "ep1", "target": "logseq"}
        ))
        assert out["success"] is True
        # write=True passed through (preview defaults to false).
        _, job_id, body = fake.calls[-1]
        assert job_id == "ep1" and body["write"] is True and body["target"] == "logseq"

    @pytest.mark.asyncio
    async def test_export_preview_sets_write_false(self):
        fake = FakeSift()
        m = _server(fake)
        await m.call_tool("export_to_vault", {"episode_id": "ep1", "preview": True})
        _, _, body = fake.calls[-1]
        assert body["write"] is False
