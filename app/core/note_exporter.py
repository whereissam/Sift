"""P21: note templater + vault writer for Obsidian / Logseq / plain markdown.

Turns an episode (transcript + P18 claims/entities/topics) or a P20 synthesis
into a templated markdown note — with YAML frontmatter, clickable timestamp
links, claim cards, highlight blocks, a collapsible transcript, and
``[[wikilinks]]`` for canonical entities. The rendering is deterministic (no
LLM): the knowledge is already extracted; this just presents it.

Targets differ only in idiom — Obsidian uses ``[[wikilinks]]`` + callouts,
Logseq uses outline bullets, ``markdown`` is portable plain text. The vault
writer reuses the security posture of the original ObsidianExporter (vault
validation, path-traversal containment, filename sanitization, dedup).

Notion is intentionally out of scope here (needs an external SDK + integration
token + database) — deferred, like email in P20.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


class NoteTarget(str, Enum):
    OBSIDIAN = "obsidian"
    LOGSEQ = "logseq"
    MARKDOWN = "markdown"


class NoteTemplate(str, Enum):
    EPISODE = "episode"        # full episode → one note
    HIGHLIGHTS = "highlights"  # just the key claims / quotes
    TOPIC = "topic"            # cross-episode synthesis on a topic
    DIGEST = "digest"          # a digest run → one note


# Surfaced by GET /api/export-templates.
EXPORT_TEMPLATES = [
    {"id": "episode", "name": "Episode note", "description": "Full episode: frontmatter, chapters, claim cards, collapsible transcript."},
    {"id": "highlights", "name": "Highlights only", "description": "Top claims and pull-quotes with timestamps."},
    {"id": "topic", "name": "Topic note", "description": "Cross-episode synthesis on a topic (themes, consensus, disagreements)."},
    {"id": "digest", "name": "Daily digest", "description": "A generated digest run rendered as a note."},
]
EXPORT_TARGETS = [t.value for t in NoteTarget]


# ===== input data =====


@dataclass
class EpisodeNoteData:
    """Everything the episode/highlights templates need, pre-gathered."""

    job_id: str
    title: str
    source_url: Optional[str] = None
    platform: Optional[str] = None
    language: Optional[str] = None
    duration_seconds: Optional[float] = None
    created_at: Optional[str] = None
    speakers: list[str] = field(default_factory=list)
    claims: list[dict] = field(default_factory=list)
    entities: list[dict] = field(default_factory=list)
    topics: list[dict] = field(default_factory=list)
    chapters: list[dict] = field(default_factory=list)  # {title, timestamp}
    segments: list[dict] = field(default_factory=list)   # {start, end, text, speaker}


# ===== YAML frontmatter (security-preserving) =====


def _yaml_scalar(value: object) -> str:
    """Serialize a value as a single-line, YAML-safe scalar (anti-injection)."""
    if isinstance(value, str):
        value = re.sub(r"\s*\n\s*", " ", value)
    dumped = yaml.safe_dump(
        value, default_flow_style=True, allow_unicode=True, width=float("inf")
    ).strip()
    if dumped.endswith("\n..."):
        dumped = dumped[:-4].strip()
    return dumped


def _frontmatter(fields: dict) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if value in (None, "", [], {}):
            continue
        lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


# ===== formatting helpers =====


def _fmt_timestamp(seconds: float) -> str:
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


_YOUTUBE_RE = re.compile(r"(?:youtube\.com|youtu\.be)", re.IGNORECASE)


def _timestamp_link(seconds: float, source_url: Optional[str]) -> str:
    """Clickable ``[mm:ss](url?t=Ns)`` for YouTube; plain ``mm:ss`` otherwise."""
    label = _fmt_timestamp(seconds)
    if source_url and _YOUTUBE_RE.search(source_url):
        sep = "&" if "?" in source_url else "?"
        return f"[{label}]({source_url}{sep}t={int(seconds or 0)}s)"
    return f"`{label}`"


def _entity_link(name: str, target: NoteTarget) -> str:
    """Obsidian/Logseq link an entity by name; plain markdown leaves it bold."""
    name = name.strip()
    if not name:
        return ""
    if target in (NoteTarget.OBSIDIAN, NoteTarget.LOGSEQ):
        return f"[[{name}]]"
    return f"**{name}**"


def _bullet(target: NoteTarget) -> str:
    # Logseq is outline-first — every block is a bullet.
    return "- " if target == NoteTarget.LOGSEQ else "- "


def sanitize_filename(title: str, max_length: int = 100) -> str:
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title or "")
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length].strip()
    return sanitized or "Untitled"


# ===== templates =====


def _claim_card(claim: dict, source_url: Optional[str], target: NoteTarget) -> list[str]:
    """One claim → a card with type, confidence, timestamp link, and evidence."""
    ctype = claim.get("claim_type", "claim")
    conf = claim.get("confidence")
    conf_str = f" · {round(conf * 100)}%" if isinstance(conf, (int, float)) else ""
    ts = _timestamp_link(claim.get("timestamp_start", 0.0), source_url)
    speaker = claim.get("speaker")
    who = f" — {speaker}" if speaker else ""
    text = (claim.get("text") or "").strip()
    lines = [f"- **[{ctype}{conf_str}]** {text} ({ts}{who})"]
    evidence = (claim.get("evidence_excerpt") or "").strip()
    if evidence and target == NoteTarget.OBSIDIAN:
        lines.append(f"  > {evidence}")
    elif evidence:
        lines.append(f"  - _{evidence}_")
    return lines


def _entity_line(entities: list[dict], target: NoteTarget) -> str:
    links = [_entity_link(e.get("name", ""), target) for e in entities if e.get("name")]
    links = [x for x in links if x]
    return ", ".join(links)


def render_episode_note(data: EpisodeNoteData, *, target: NoteTarget) -> str:
    topic_names = [t.get("name") for t in data.topics if t.get("name")]
    entity_names = [e.get("name") for e in data.entities if e.get("name")]
    fm = _frontmatter(
        {
            "title": data.title,
            "source": data.source_url,
            "platform": data.platform,
            "date": data.created_at or datetime.utcnow().isoformat(),
            "language": data.language,
            "speakers": data.speakers,
            "topics": topic_names,
            "tags": ["sift/episode", *[f"topic/{_slug(t)}" for t in topic_names]],
            "entities": entity_names,
        }
    )

    out: list[str] = [fm, f"# {data.title}", ""]

    if data.entities:
        out += [f"**Entities:** {_entity_line(data.entities, target)}", ""]

    if data.chapters:
        out.append("## Chapters")
        for ch in data.chapters:
            ts = _timestamp_link(ch.get("timestamp", 0.0), data.source_url)
            out.append(f"- {ts} {ch.get('title', '').strip()}")
        out.append("")

    if data.claims:
        out.append("## Claims")
        for c in data.claims:
            out += _claim_card(c, data.source_url, target)
        out.append("")

    if data.segments:
        out.append("## Transcript")
        if target == NoteTarget.OBSIDIAN:
            # Obsidian renders HTML <details> for a collapsible block.
            out.append("> [!note]- Full transcript")
            for seg in data.segments:
                ts = _fmt_timestamp(seg.get("start", 0.0))
                spk = f"**{seg['speaker']}:** " if seg.get("speaker") else ""
                out.append(f"> `{ts}` {spk}{(seg.get('text') or '').strip()}")
        else:
            for seg in data.segments:
                ts = _timestamp_link(seg.get("start", 0.0), data.source_url)
                spk = f"**{seg['speaker']}:** " if seg.get("speaker") else ""
                out.append(f"- {ts} {spk}{(seg.get('text') or '').strip()}")
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def render_highlights_note(data: EpisodeNoteData, *, target: NoteTarget) -> str:
    """Highest-signal claims only (confidence-ordered), no transcript."""
    fm = _frontmatter(
        {
            "title": f"{data.title} — Highlights",
            "source": data.source_url,
            "date": data.created_at or datetime.utcnow().isoformat(),
            "tags": ["sift/highlights"],
        }
    )
    ranked = sorted(
        data.claims, key=lambda c: c.get("confidence") or 0.0, reverse=True
    )
    out = [fm, f"# {data.title} — Highlights", ""]
    if not ranked:
        out.append("_No extracted claims for this episode yet._")
        return "\n".join(out).rstrip() + "\n"
    for c in ranked:
        out += _claim_card(c, data.source_url, target)
    return "\n".join(out).rstrip() + "\n"


def render_synthesis_note(
    *, title: str, markdown_body: str, source: Optional[str] = None, kind: str = "topic"
) -> str:
    """Wrap a P20 synthesis markdown (topic or digest) with frontmatter."""
    fm = _frontmatter(
        {
            "title": title,
            "source": source,
            "date": datetime.utcnow().isoformat(),
            "tags": [f"sift/{kind}"],
        }
    )
    return fm + markdown_body.rstrip() + "\n"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-") or "untitled"


# ===== vault writer (filesystem targets) =====


@dataclass
class VaultWriteResult:
    success: bool
    file_path: Optional[str] = None
    vault_path: Optional[str] = None
    note_name: Optional[str] = None
    error: Optional[str] = None


def write_note_to_vault(
    vault_path: str,
    filename_title: str,
    content: str,
    *,
    subfolder: Optional[str] = None,
) -> VaultWriteResult:
    """Write a note into a vault folder, safely.

    Validates the vault is an existing writable dir, contains the optional
    subfolder within the vault (rejecting ``..`` / absolute escapes), sanitizes
    the filename, and dedups by appending a timestamp. Mirrors the original
    ObsidianExporter's containment checks so Logseq/Obsidian share one writer.
    """
    vault = Path(vault_path)
    if not vault.exists():
        return VaultWriteResult(success=False, error=f"Vault path does not exist: {vault}")
    if not vault.is_dir():
        return VaultWriteResult(success=False, error=f"Vault path is not a directory: {vault}")

    target_dir = vault
    if subfolder:
        safe = Path(subfolder)
        if safe.is_absolute() or ".." in safe.parts:
            return VaultWriteResult(
                success=False, error=f"Invalid subfolder: path traversal in '{subfolder}'"
            )
        target_dir = (vault / safe).resolve()
        if not str(target_dir).startswith(str(vault.resolve())):
            return VaultWriteResult(success=False, error="Subfolder resolves outside vault")
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:  # noqa: BLE001
            return VaultWriteResult(success=False, error=f"Cannot create subfolder: {e}")

    name = sanitize_filename(filename_title)
    file_path = target_dir / f"{name}.md"
    if file_path.exists():
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        file_path = target_dir / f"{name}_{stamp}.md"

    try:
        file_path.write_text(content, encoding="utf-8")
    except PermissionError:
        return VaultWriteResult(success=False, error=f"Permission denied: {file_path}")
    except Exception as e:  # noqa: BLE001
        return VaultWriteResult(success=False, error=f"Failed to write note: {e}")

    logger.info("Exported note to vault: %s", file_path)
    return VaultWriteResult(
        success=True,
        file_path=str(file_path),
        vault_path=str(vault),
        note_name=file_path.name,
    )
