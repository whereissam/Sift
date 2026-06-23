"""Schemas for P20 cross-episode digest synthesis.

The digest's value over a single-episode summary is *cross-source* structure:
what several episodes agreed on, where they disagreed, which narratives repeat,
and which forward-looking claims are worth tracking. These models are the wire
format the synthesizer produces and the store persists (as ``synthesis_json``).

Versioned independently of the P18 knowledge schema — a digest is a derived,
regenerable artifact, so a format change just bumps ``DIGEST_SCHEMA_VERSION`` and
old runs stay readable as historical rows.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

DIGEST_SCHEMA_VERSION = 1


class DigestTheme(BaseModel):
    """A topic that surfaced across the window, with how many sources touched it."""

    model_config = ConfigDict(extra="ignore")

    title: str
    summary: str = ""
    episode_ids: list[str] = Field(default_factory=list)
    source_count: int = 0


class ConsensusPoint(BaseModel):
    """A claim multiple sources broadly agreed on."""

    model_config = ConfigDict(extra="ignore")

    statement: str
    sources: list[str] = Field(
        default_factory=list, description="Episode ids / labels that support it."
    )


class DisagreementPosition(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: str = ""
    stance: str = ""


class Disagreement(BaseModel):
    """A topic where sources took opposing positions."""

    model_config = ConfigDict(extra="ignore")

    topic: str
    positions: list[DisagreementPosition] = Field(default_factory=list)


class NotablePrediction(BaseModel):
    """A forward-looking claim worth tracking, attributed to its source."""

    model_config = ConfigDict(extra="ignore")

    text: str
    source: str = ""
    horizon: Optional[str] = None


class NarrativeWatch(BaseModel):
    """A repeated framing and who is amplifying it (narrative-tracking)."""

    model_config = ConfigDict(extra="ignore")

    narrative: str
    amplifiers: list[str] = Field(default_factory=list)


class DigestSynthesis(BaseModel):
    """The structured cross-episode synthesis for one digest run."""

    model_config = ConfigDict(extra="ignore")

    headline: str = ""
    themes: list[DigestTheme] = Field(default_factory=list)
    consensus: list[ConsensusPoint] = Field(default_factory=list)
    disagreements: list[Disagreement] = Field(default_factory=list)
    predictions: list[NotablePrediction] = Field(default_factory=list)
    narratives: list[NarrativeWatch] = Field(default_factory=list)
    schema_version: int = DIGEST_SCHEMA_VERSION


class DigestRunResult(BaseModel):
    """Outcome of one synthesis call (not persisted directly — the runner maps
    it onto a ``digest_runs`` row)."""

    success: bool
    synthesis: Optional[DigestSynthesis] = None
    episode_count: int = 0
    claim_count: int = 0
    tokens_used: int = 0
    model: Optional[str] = None
    provider: Optional[str] = None
    error: Optional[str] = None


def render_digest_markdown(
    synthesis: DigestSynthesis, *, title: str, window_label: str
) -> str:
    """Render a synthesis into a human-readable markdown digest.

    Deterministic (no LLM) so the same synthesis always renders identically —
    used for the email/Telegram/Obsidian channels and the API preview.
    """
    lines: list[str] = [f"# {title}", "", f"*{window_label}*", ""]

    if synthesis.headline:
        lines += [f"**{synthesis.headline}**", ""]

    if synthesis.themes:
        lines.append("## Themes")
        for t in synthesis.themes:
            src = f" _({t.source_count} sources)_" if t.source_count else ""
            lines.append(f"- **{t.title}**{src} — {t.summary}".rstrip(" —"))
        lines.append("")

    if synthesis.consensus:
        lines.append("## Consensus")
        for c in synthesis.consensus:
            src = f" _({', '.join(c.sources)})_" if c.sources else ""
            lines.append(f"- {c.statement}{src}")
        lines.append("")

    if synthesis.disagreements:
        lines.append("## Disagreements")
        for d in synthesis.disagreements:
            lines.append(f"- **{d.topic}**")
            for p in d.positions:
                who = f"{p.source}: " if p.source else ""
                lines.append(f"  - {who}{p.stance}")
        lines.append("")

    if synthesis.predictions:
        lines.append("## Predictions to track")
        for p in synthesis.predictions:
            horizon = f" _(by {p.horizon})_" if p.horizon else ""
            src = f" — {p.source}" if p.source else ""
            lines.append(f"- {p.text}{horizon}{src}")
        lines.append("")

    if synthesis.narratives:
        lines.append("## Narratives")
        for n in synthesis.narratives:
            who = f" — amplified by {', '.join(n.amplifiers)}" if n.amplifiers else ""
            lines.append(f"- {n.narrative}{who}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
