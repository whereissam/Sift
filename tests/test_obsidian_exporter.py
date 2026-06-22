"""Tests for app/core/obsidian_exporter.py YAML-safe frontmatter."""

from __future__ import annotations

import yaml

from app.core.obsidian_exporter import ObsidianExporter


def _parse_frontmatter(fm: str) -> dict:
    """Extract and parse the YAML document between the --- fences."""
    parts = fm.split("---")
    # parts[0] == "" (before first ---), parts[1] == yaml body
    return yaml.safe_load(parts[1])


def test_frontmatter_escapes_newline_injection():
    """A source_url with embedded newlines must not inject extra YAML keys."""
    exporter = ObsidianExporter("/tmp")
    malicious = "https://x.com/a\ninjected: pwned\nadmin: true"

    fm = exporter.generate_frontmatter(title="Note", source_url=malicious)
    parsed = _parse_frontmatter(fm)

    assert "injected" not in parsed
    assert "admin" not in parsed
    # The whole value survives as a single scalar (newlines collapsed).
    assert parsed["source"] == "https://x.com/a injected: pwned admin: true"


def test_frontmatter_is_valid_yaml():
    """Tricky title/tags/language values must still produce parseable YAML."""
    exporter = ObsidianExporter("/tmp")
    fm = exporter.generate_frontmatter(
        title='My "Great": Title',
        source_url="https://example.com",
        language="en: us",
        tags=["ai", "security: x", "b]reak"],
        created_at="2026-06-22",
    )
    parsed = _parse_frontmatter(fm)

    assert parsed["title"] == 'My "Great": Title'
    assert parsed["language"] == "en: us"
    assert parsed["tags"] == ["ai", "security: x", "b]reak"]
    assert parsed["date"] == "2026-06-22"
