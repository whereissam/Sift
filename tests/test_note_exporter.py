"""Tests for the P21 note templater + vault writer."""

from __future__ import annotations

from pathlib import Path


from app.core.note_exporter import (
    EpisodeNoteData,
    NoteTarget,
    _fmt_timestamp,
    _timestamp_link,
    render_episode_note,
    render_highlights_note,
    sanitize_filename,
    write_note_to_vault,
)


def _data(**over) -> EpisodeNoteData:
    base = dict(
        job_id="j1",
        title="The Future of L2s",
        source_url="https://youtube.com/watch?v=abc",
        platform="youtube",
        language="en",
        claims=[
            {"text": "L2s win", "claim_type": "prediction", "confidence": 0.9,
             "timestamp_start": 762, "speaker": "Guest", "evidence_excerpt": "rollups",
             "entity_ids": ["e1"], "topic_ids": ["t1"]},
            {"text": "Gas is high", "claim_type": "fact", "confidence": 0.4,
             "timestamp_start": 10, "entity_ids": [], "topic_ids": []},
        ],
        entities=[{"name": "Vitalik Buterin", "entity_type": "person"}],
        topics=[{"name": "Layer 2"}],
        segments=[{"start": 762, "end": 770, "text": "rollups", "speaker": "Guest"}],
    )
    base.update(over)
    return EpisodeNoteData(**base)


class TestHelpers:
    def test_fmt_timestamp(self):
        assert _fmt_timestamp(62) == "01:02"
        assert _fmt_timestamp(3725) == "1:02:05"

    def test_timestamp_link_youtube(self):
        link = _timestamp_link(762, "https://youtube.com/watch?v=abc")
        assert link == "[12:42](https://youtube.com/watch?v=abc&t=762s)"

    def test_timestamp_link_non_youtube_is_plain(self):
        assert _timestamp_link(62, "https://example.com/ep") == "`01:02`"

    def test_timestamp_link_no_url(self):
        assert _timestamp_link(62, None) == "`01:02`"

    def test_sanitize_filename(self):
        assert sanitize_filename('a/b:c*?"<>|d') == "abcd"
        assert sanitize_filename("") == "Untitled"


class TestEpisodeNote:
    def test_obsidian_has_wikilinks_and_callout(self):
        md = render_episode_note(_data(), target=NoteTarget.OBSIDIAN)
        assert "[[Vitalik Buterin]]" in md          # entity wikilink
        assert "> [!note]- Full transcript" in md     # collapsible callout
        assert "[12:42](https://youtube.com/watch?v=abc&t=762s)" in md  # clickable ts
        assert "**[prediction · 90%]**" in md         # claim card w/ confidence

    def test_logseq_uses_plain_bullets_no_callout(self):
        md = render_episode_note(_data(), target=NoteTarget.LOGSEQ)
        assert "[[Vitalik Buterin]]" in md            # Logseq also links
        assert "[!note]" not in md                     # no Obsidian callout
        assert "## Transcript" in md

    def test_markdown_target_no_wikilinks(self):
        md = render_episode_note(_data(), target=NoteTarget.MARKDOWN)
        assert "[[" not in md
        assert "**Vitalik Buterin**" in md

    def test_frontmatter_is_yaml_safe(self):
        # A newline-injecting title must not break out of the frontmatter block.
        md = render_episode_note(_data(title="evil\ntitle: hacked"), target=NoteTarget.MARKDOWN)
        head = md.split("---", 2)[1]
        assert "hacked" not in head.replace("evil title: hacked", "")  # collapsed to one scalar

    def test_frontmatter_lists_topics_and_tags(self):
        md = render_episode_note(_data(), target=NoteTarget.OBSIDIAN)
        assert "topics: [Layer 2]" in md
        assert "topic/layer-2" in md


class TestHighlightsNote:
    def test_ranks_by_confidence(self):
        md = render_highlights_note(_data(), target=NoteTarget.MARKDOWN)
        # 0.9 claim appears before the 0.4 claim.
        assert md.index("L2s win") < md.index("Gas is high")
        assert "## Transcript" not in md  # highlights omit the transcript

    def test_empty_claims_message(self):
        md = render_highlights_note(_data(claims=[]), target=NoteTarget.MARKDOWN)
        assert "No extracted claims" in md


class TestVaultWriter:
    def test_writes_note(self, tmp_path: Path):
        r = write_note_to_vault(str(tmp_path), "My Note", "# hello\n")
        assert r.success is True
        assert Path(r.file_path).read_text() == "# hello\n"
        assert r.note_name == "My Note.md"

    def test_subfolder_created(self, tmp_path: Path):
        r = write_note_to_vault(str(tmp_path), "N", "x", subfolder="Sift/Episodes")
        assert r.success is True
        assert (tmp_path / "Sift" / "Episodes" / "N.md").exists()

    def test_path_traversal_rejected(self, tmp_path: Path):
        r = write_note_to_vault(str(tmp_path), "N", "x", subfolder="../escape")
        assert r.success is False
        assert "traversal" in r.error.lower()

    def test_missing_vault_errors(self, tmp_path: Path):
        r = write_note_to_vault(str(tmp_path / "nope"), "N", "x")
        assert r.success is False
        assert "does not exist" in r.error

    def test_dedup_appends_timestamp(self, tmp_path: Path):
        write_note_to_vault(str(tmp_path), "Dup", "a")
        r2 = write_note_to_vault(str(tmp_path), "Dup", "b")
        assert r2.success is True
        assert r2.note_name != "Dup.md"  # timestamp-suffixed
        assert (tmp_path / "Dup.md").read_text() == "a"  # original untouched
