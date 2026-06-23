"""FastMCP server wiring Sift primitives as MCP tools (P19).

``build_server`` returns a configured ``FastMCP`` instance. Tools close over a
single ``SiftClient`` so the whole surface shares one HTTP connection pool and a
test can inject an in-process (ASGI) client.

Scope: tools backed by P18 + existing routes, plus ``export_to_vault`` (P21).
Tools that need unbuilt phases — ``ask_episode`` / ``ask_at_timestamp`` (P11 RAG),
``search_library`` (P10), ``compare_episodes`` / ``find_contradictions`` /
``summarize_trend`` (P13 + P20) — are intentionally absent until their substrate
ships.
"""

from __future__ import annotations

from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from .client import SiftClient
from .config import MCPConfig, load_config

# Summary modes accepted by POST /api/summarize/job/{id}.
_SUMMARY_MODES = {"bullet_points", "chapters", "key_topics", "action_items", "full"}

SERVER_INSTRUCTIONS = (
    "Sift exposes audio/video knowledge primitives. Ingest a URL with "
    "`ingest_url` to get an `episode_id` (a job id), then read its transcript, "
    "summary, clips, and the structured knowledge layer (claims, entities, "
    "topics, predictions) by that id. Knowledge extraction is asynchronous: a "
    "knowledge tool may report `status='pending'` — retry shortly. Q&A, "
    "library-wide semantic search, cross-episode synthesis, and vault export "
    "are not yet available."
)


def _pending(status: int, body: dict) -> Optional[dict]:
    """Return a uniform pending-notice dict for a 202 knowledge response."""
    if status == 202:
        return {
            "status": "pending",
            "run_state": body.get("run_state") or body.get("knowledge_status"),
            "message": "Knowledge extraction is still running; retry shortly.",
        }
    return None


def _ordered_unique(items) -> list:
    seen: dict[Any, None] = {}
    for it in items:
        if it not in seen:
            seen[it] = None
    return list(seen.keys())


def build_server(
    config: Optional[MCPConfig] = None,
    *,
    client: Optional[SiftClient] = None,
) -> FastMCP:
    config = config or load_config()
    sift = client or SiftClient(config)

    mcp = FastMCP("sift", instructions=SERVER_INSTRUCTIONS)

    # ===== ingest / transcript =====

    @mcp.tool()
    async def ingest_url(
        url: str, diarize: bool = False, language: str | None = None
    ) -> dict:
        """Submit a URL to download and transcribe. Returns the episode/job id
        and initial status; poll the knowledge/transcript tools by that id."""
        job = await sift.transcribe(url=url, diarize=diarize, language=language)
        return {
            "episode_id": job.get("job_id"),
            "status": job.get("status"),
            "progress": job.get("progress"),
        }

    @mcp.tool()
    async def get_transcript(episode_id: str, format: str = "text") -> dict:
        """Fetch an episode transcript. `format`: 'text' (plain), 'json'
        (timestamped segments), or 'formatted' (the SRT/VTT/dialogue rendering
        chosen at ingest time)."""
        job = await sift.get_transcription(episode_id)
        base = {
            "episode_id": episode_id,
            "status": job.get("status"),
            "language": job.get("language"),
            "duration_seconds": job.get("duration_seconds"),
        }
        if format == "json":
            base["segments"] = job.get("segments") or []
        elif format == "formatted":
            base["formatted_output"] = job.get("formatted_output")
            base["output_format"] = job.get("output_format")
        else:
            base["text"] = job.get("text")
        return base

    @mcp.tool()
    async def get_segment(episode_id: str, start: float, end: float) -> dict:
        """Pull the transcript for a specific time range [start, end] (seconds).
        Composed client-side from the episode's timestamped segments."""
        job = await sift.get_transcription(episode_id)
        segments = job.get("segments") or []
        hits = [
            s
            for s in segments
            if s.get("end") is not None
            and s.get("start") is not None
            and s["end"] >= start
            and s["start"] <= end
        ]
        return {
            "episode_id": episode_id,
            "start": start,
            "end": end,
            "segments": hits,
            "text": " ".join(s.get("text", "").strip() for s in hits).strip(),
        }

    # ===== summary / clips / highlights =====

    @mcp.tool()
    async def get_summary(episode_id: str, mode: str = "bullet_points") -> dict:
        """Summarize an episode. `mode`: bullet_points | chapters | key_topics |
        action_items | full. Generated on demand via the configured LLM."""
        if mode not in _SUMMARY_MODES:
            raise ValueError(
                f"Unknown mode '{mode}'. Choose one of: {sorted(_SUMMARY_MODES)}"
            )
        return await sift.summarize(episode_id, mode)

    @mcp.tool()
    async def get_chapters(episode_id: str) -> dict:
        """Auto-generated chapter markers for an episode (summary in 'chapters'
        mode)."""
        return await sift.summarize(episode_id, "chapters")

    @mcp.tool()
    async def get_clips(episode_id: str) -> dict:
        """List previously generated social/viral clips for an episode (hook,
        caption, hashtags, timestamps, viral score)."""
        return await sift.get_clips(episode_id)

    @mcp.tool()
    async def get_highlights(episode_id: str) -> dict:
        """Pull-quote-grade highlights with timestamps. Derived from the
        episode's generated clips (ranked by viral score)."""
        data = await sift.get_clips(episode_id)
        clips = data.get("clips") or []
        highlights = [
            {
                "start_time": c.get("start_time"),
                "end_time": c.get("end_time"),
                "quote": c.get("transcript_text") or c.get("hook"),
                "hook": c.get("hook"),
                "score": c.get("viral_score"),
            }
            for c in clips
        ]
        highlights.sort(key=lambda h: h.get("score") or 0.0, reverse=True)
        result: dict[str, Any] = {"episode_id": episode_id, "highlights": highlights}
        if not highlights:
            result["message"] = (
                "No highlights yet — generate clips for this episode first "
                "(POST /api/jobs/{id}/clips)."
            )
        return result

    # ===== knowledge layer (P18) =====

    @mcp.tool()
    async def get_claims(episode_id: str, min_confidence: float = 0.5) -> dict:
        """Structured, citable claims for an episode (fact / opinion /
        prediction / question / recommendation) with timestamps, speaker,
        confidence, and evidence."""
        status, body = await sift.get_knowledge(
            episode_id, min_confidence=min_confidence
        )
        pending = _pending(status, body)
        if pending:
            return pending
        return {
            "episode_id": episode_id,
            "claim_count": body.get("claim_count", len(body.get("claims") or [])),
            "claims": body.get("claims") or [],
        }

    @mcp.tool()
    async def get_entities(episode_id: str, min_confidence: float = 0.5) -> dict:
        """Canonical entities mentioned in an episode (people, companies,
        tickers, projects, products, places), resolved across the library."""
        status, body = await sift.get_knowledge(
            episode_id, min_confidence=min_confidence
        )
        pending = _pending(status, body)
        if pending:
            return pending
        entity_ids = _ordered_unique(
            eid for c in (body.get("claims") or []) for eid in (c.get("entity_ids") or [])
        )
        entities = []
        for eid in entity_ids:
            try:
                entities.append(await sift.get_entity(eid))
            except Exception:  # noqa: BLE001 - skip an entity that 404s, don't fail the call
                continue
        return {"episode_id": episode_id, "entities": entities}

    @mcp.tool()
    async def get_topics(episode_id: str, min_confidence: float = 0.5) -> dict:
        """Topic clusters this episode contributes to (the topic graph)."""
        status, body = await sift.get_knowledge(
            episode_id, min_confidence=min_confidence
        )
        pending = _pending(status, body)
        if pending:
            return pending
        topic_ids = _ordered_unique(
            tid for c in (body.get("claims") or []) for tid in (c.get("topic_ids") or [])
        )
        topics = []
        for tid in topic_ids:
            try:
                topics.append(await sift.get_topic(tid))
            except Exception:  # noqa: BLE001
                continue
        return {"episode_id": episode_id, "topics": topics}

    @mcp.tool()
    async def get_predictions(episode_id: str, min_confidence: float = 0.5) -> dict:
        """Falsifiable forward-looking claims for an episode, with lifecycle
        metadata (target horizon, conditions, falsifier, resolution)."""
        status, body = await sift.get_knowledge(
            episode_id, min_confidence=min_confidence
        )
        pending = _pending(status, body)
        if pending:
            return pending
        claim_ids = [
            c.get("claim_id")
            for c in (body.get("claims") or [])
            if c.get("claim_type") == "prediction" and c.get("claim_id")
        ]
        predictions = []
        for cid in claim_ids:
            try:
                predictions.append(await sift.get_prediction(cid))
            except Exception:  # noqa: BLE001 - a prediction row may not exist yet
                continue
        return {"episode_id": episode_id, "predictions": predictions}

    # ===== export (P21) =====

    @mcp.tool()
    async def export_to_vault(
        episode_id: str,
        target: str = "obsidian",
        template: str = "episode",
        vault_path: str | None = None,
        preview: bool = False,
    ) -> dict:
        """Export an episode as a templated markdown note. `target`: obsidian |
        logseq | markdown. `template`: episode | highlights. Writes into the
        configured (or given) vault; set `preview=true` to return the rendered
        note content instead of writing it."""
        body = {
            "target": target,
            "template": template,
            "write": not preview,
        }
        if vault_path:
            body["vault_path"] = vault_path
        return await sift.export_job(episode_id, body)

    return mcp
