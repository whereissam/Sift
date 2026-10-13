"""Tests for P23 subtitle reflow (app/ingest/transcribe/subtitles.py).

The interesting cases are the ones the constraint model exists for: sources
that *cannot* satisfy every subtitle rule. Those must produce legal cues plus
a reported violation, never an exception and never a silently broken cue.
"""

from __future__ import annotations

import pytest

from sift_core.transcribe.subtitles import (
    DEFAULT_STYLE,
    PRESETS,
    ScriptProfile,
    SubtitleStyle,
    cjk_equivalent_chars,
    display_width,
    format_srt,
    format_vtt,
    profile_for_text,
    reflow,
    reflow_to_srt,
    split_segment,
    validate,
)

EPS = 1e-6
BALANCED = SubtitleStyle.preset("balanced")


def seg(start, end, text, speaker=None):
    return {"start": start, "end": end, "text": text, "speaker": speaker}


# Every fixture here is run through the invariant test at the bottom.
FIXTURES: dict[str, tuple[list[dict], SubtitleStyle, bool]] = {
    "long_latin": (
        [seg(0, 12, "I went to the store because I needed some milk and eggs for the "
                    "recipe that my grandmother wrote down in her notebook years ago.")],
        BALANCED,
        False,
    ),
    "long_cjk": (
        [seg(0, 14, "今天我們測了 NVIDIA 的新模型，結果發現它在中文語音辨識上的表現比我們"
                    "預期的還要好很多，特別是在有背景噪音的情況下。")],
        BALANCED,
        False,
    ),
    "mixed_zh_en": (
        [seg(0, 10, "這個 endpoint 回傳的 JSON schema 我們改過了，"
                    "now every field is explicitly typed and validated on the way in.")],
        BALANCED,
        False,
    ),
    "youtube_fragments": (
        [seg(i * 0.4, i * 0.4 + 0.35, t) for i, t in enumerate(
            ["so if you", "look at the", "numbers here", "you can see", "the trend"])],
        SubtitleStyle.preset("youtube"),
        False,
    ),
    "impossible_reading_speed": (
        [seg(0, 2, "This is a very long sentence with a whole lot of text in it")],
        BALANCED,
        False,
    ),
    "impossible_min_duration": ([seg(10.0, 10.4, "Okay.")], BALANCED, False),
    "url_single_line": (
        [seg(0, 5, "see https://example.com/a/very/long/path/that/never/ends/ok now")],
        SubtitleStyle.preset("single_line"),
        False,
    ),
    "speakers": (
        [seg(0, 8, "Hello everyone and welcome back to the show where we talk about "
                   "a lot of things at some length.", "SPEAKER_00"),
         seg(8.2, 9.0, "Thanks for having me.", "SPEAKER_01")],
        BALANCED,
        True,
    ),
    "very_long_segment": ([seg(0, 300, "Short.")], BALANCED, False),
    "conformant_pair": (
        [seg(0, 1.2, "Hello there my friend."), seg(1.28, 2.5, "How are you doing today?")],
        BALANCED,
        False,
    ),
    "overlapping_diarized": (
        [seg(0, 2.0, "First speaker talking.", "A"), seg(1.5, 3.0, "Second one cuts in.", "B")],
        BALANCED,
        True,
    ),
}


# ---------------------------------------------------------------- measurement


def test_display_width_counts_cjk_as_two():
    assert display_width("你好") == 4
    assert display_width("hi") == 2


def test_cjk_line_capacity_is_characters_not_display_width():
    """Regression: measuring a 16-character CJK limit in east-asian width
    units would halve the real capacity to 8 characters."""
    sixteen = "一二三四五六七八九十一二三四五六"
    assert len(sixteen) == 16
    assert cjk_equivalent_chars(sixteen, BALANCED) == pytest.approx(16.0)
    result = reflow([seg(0, 4, sixteen)], BALANCED)
    assert len(result.cues) == 1
    assert result.cues[0].lines == (sixteen,)


def test_profile_comes_from_the_text():
    assert profile_for_text("hello world", BALANCED) is ScriptProfile.LATIN
    assert profile_for_text("今天天氣很好", BALANCED) is ScriptProfile.CJK
    assert profile_for_text("我們用 GraphQL", BALANCED) is ScriptProfile.CJK


# --------------------------------------------------------------------- splits


def test_long_latin_splits_into_two_line_cues():
    segments, style, _ = FIXTURES["long_latin"]
    result = reflow(segments, style)
    assert len(result.cues) > 1
    for cue in result.cues:
        assert len(cue.lines) <= style.max_lines


def test_break_scoring_beats_the_comma_trap():
    """A strict priority ladder takes the comma and wrecks the balance:
    'I went,' / 'to the store because I needed some milk.'"""
    result = reflow([seg(0, 6, "I went to the store because I needed some milk.")], BALANCED)
    assert len(result.cues) == 1
    lines = result.cues[0].lines
    assert lines[0] != "I went,"
    assert not lines[0].endswith(",")
    assert lines[0] == "I went to the store"
    assert lines[1] == "because I needed some milk."


def test_never_splits_a_latin_word():
    words = ["extraordinarily", "complicated", "vocabulary", "throughout"] * 3
    result = reflow([seg(0, 20, " ".join(words))], BALANCED)
    emitted = " ".join(" ".join(c.lines) for c in result.cues).split()
    assert emitted == words


def test_over_long_token_takes_the_hard_cut_exception():
    """'never split a Latin word' and 'never exceed capacity' cannot both hold
    for a single token wider than one line -- the token loses."""
    segments, style, _ = FIXTURES["url_single_line"]
    result = reflow(segments, style)
    for cue in result.cues:
        for line in cue.render_lines():
            assert display_width(line) <= style.latin_max_display_width


def test_mixed_script_switches_profile_within_one_segment():
    segments, style, _ = FIXTURES["mixed_zh_en"]
    result = reflow(segments, style)
    profiles = {profile_for_text(line, style)
                for cue in result.cues for line in cue.lines}
    assert ScriptProfile.CJK in profiles
    assert ScriptProfile.LATIN in profiles


def test_split_segment_is_usable_on_its_own():
    cues = split_segment(seg(0, 8, "One sentence here. Another sentence follows it now."), BALANCED)
    assert cues
    assert all(c.source_segment_indices == (0,) for c in cues)


# --------------------------------------------------------------------- merges


def test_youtube_fragments_are_merged():
    segments, style, _ = FIXTURES["youtube_fragments"]
    result = reflow(segments, style)
    assert len(result.cues) < len(segments)
    assert "so if you look at the numbers here" in result.cues[0].text


def test_merged_cue_keeps_every_source():
    segments, style, _ = FIXTURES["youtube_fragments"]
    result = reflow(segments, style)
    assert len(result.cues[0].source_segment_indices) > 1
    assert result.cues[0].source_start == 0.0


def test_conformant_neighbours_are_not_merged():
    """Merging is triggered by undershoot, not by legality -- otherwise
    reflow is not idempotent."""
    segments, style, _ = FIXTURES["conformant_pair"]
    result = reflow(segments, style)
    assert len(result.cues) == 2


def test_no_merge_across_speaker_change():
    result = reflow([seg(0, 0.4, "Yes.", "A"), seg(0.5, 0.9, "No.", "B")], BALANCED, True)
    assert len(result.cues) == 2
    assert result.cues[0].speaker == "A"
    assert result.cues[1].speaker == "B"


def test_no_merge_across_a_long_silence():
    result = reflow([seg(0, 0.3, "Right."), seg(3.3, 3.6, "Okay.")], BALANCED)
    assert len(result.cues) == 2


# --------------------------------------------------------------------- timing


def test_extension_never_overlaps_the_next_cue():
    # 1.8 s apart, so the fragment is not merged into its neighbour.
    result = reflow([seg(0, 0.2, "Hi."), seg(2.0, 4.0, "Then a longer one here.")], BALANCED)
    assert len(result.cues) == 2
    assert result.cues[0].end <= result.cues[1].start + EPS


def test_extension_never_outruns_the_audio():
    """max_lead_out defaults to 0.0 -- strict envelope."""
    result = reflow([seg(10.0, 10.4, "Okay.")], BALANCED)
    assert result.cues[0].end <= 10.4 + EPS


def test_lead_out_relaxes_the_envelope_when_enabled():
    style = SubtitleStyle(max_lead_out=1.0)
    result = reflow([seg(10.0, 10.4, "Okay.")], style)
    assert result.cues[0].duration == pytest.approx(style.min_duration)
    assert not [v for v in result.violations if v.kind == "min_duration"]


def test_max_duration_is_hard():
    segments, style, _ = FIXTURES["very_long_segment"]
    result = reflow(segments, style)
    for cue in result.cues:
        assert cue.duration <= style.max_duration + EPS


def test_reading_speed_never_shortens_a_cue_into_a_dead_gap():
    """Reading speed is a maximum, not a target duration."""
    segments, style, _ = FIXTURES["long_latin"]
    result = reflow(segments, style)
    for a, b in zip(result.cues, result.cues[1:]):
        assert b.start - a.end < 0.5


# ------------------------------------------------------- impossible sources


def test_dense_source_reports_reading_speed_and_does_not_raise():
    """60 characters in 2.0 s reads at 30 cps and splitting cannot change
    that -- the cue must still be legal, with the violation reported."""
    segments, style, _ = FIXTURES["impossible_reading_speed"]
    result = reflow(segments, style)
    assert result.cues
    kinds = {v.kind for v in result.violations}
    assert "reading_speed" in kinds
    assert result.violations[0].actual > style.latin_cps


def test_short_source_reports_min_duration_and_does_not_raise():
    result = reflow([seg(10.0, 10.4, "Okay.")], BALANCED)
    assert result.cues[0].duration == pytest.approx(0.4)
    assert [v.kind for v in result.violations] == ["min_duration"]


def test_summary_names_the_unmet_targets():
    segments, style, _ = FIXTURES["impossible_reading_speed"]
    assert "reading_speed" in reflow(segments, style).summary()
    assert "all subtitle targets met" in reflow(
        [seg(0, 4, "A short line.")], BALANCED).summary()


# -------------------------------------------------------------- speaker prefix


def test_speaker_prefix_is_charged_to_the_first_line():
    segments, style, _ = FIXTURES["speakers"]
    result = reflow(segments, style, speaker_prefix=True)
    first = result.cues[0]
    assert first.render_lines()[0].startswith("[SPEAKER_00] ")
    assert display_width(first.render_lines()[0]) <= style.latin_max_display_width


def test_prefix_is_not_part_of_the_source_text():
    """The preservation invariant compares source text, and the prefix is
    presentation -- so it must live outside `lines`."""
    result = reflow([seg(0, 4, "Hello there.", "SPEAKER_00")], BALANCED, True)
    assert "SPEAKER_00" not in result.cues[0].text
    assert "SPEAKER_00" in result.cues[0].render()


def test_no_prefix_when_not_requested():
    result = reflow([seg(0, 4, "Hello there.", "SPEAKER_00")], BALANCED, False)
    assert result.cues[0].render() == "Hello there."


# ------------------------------------------------------------------ degenerate


@pytest.mark.parametrize("segments", [
    [],
    [seg(0, 1, "")],
    [seg(0, 1, "   ")],
    [seg(5, 1, "End before start.")],
    [seg(0, 0, "Zero duration.")],
])
def test_degenerate_input_does_not_raise(segments):
    result = reflow(segments, BALANCED)
    validate(result.cues, BALANCED)


def test_unknown_preset_is_rejected():
    with pytest.raises(ValueError):
        SubtitleStyle.preset("nope")


# ------------------------------------------------------------------ writers


def test_srt_shape():
    out = reflow_to_srt([seg(0, 2.5, "Hello there.")], BALANCED)
    assert out.startswith("1\n00:00:00,000 --> 00:00:02,500\nHello there.")


def test_vtt_shape():
    out = format_vtt(reflow([seg(0, 2.5, "Hello there.")], BALANCED).cues)
    assert out.startswith("WEBVTT\n\n00:00:00.000 --> 00:00:02.500\n")


def test_writer_prepends_nothing():
    """Appending the prefix at write time would break a width invariant that
    was already validated."""
    result = reflow([seg(0, 6, "A line of dialogue here.", "S")], BALANCED, True)
    assert format_srt(result.cues).count("[S] ") == len(result.cues)


# ---------------------------------------------------------------- invariants


def _normalized(text: str) -> str:
    return "".join(text.split())


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_hard_invariants_hold_for_every_fixture(name):
    segments, style, speakers = FIXTURES[name]
    result = reflow(segments, style, speakers)

    # validate() asserts the hard constraints itself.
    validate(result.cues, style)

    prev_end = float("-inf")
    for cue in result.cues:
        assert cue.start >= prev_end - EPS
        assert cue.end >= cue.start - EPS
        assert cue.start >= cue.source_start - EPS
        assert cue.end <= max(cue.start, cue.source_end + style.max_lead_out) + EPS
        assert len(cue.lines) <= style.max_lines
        prev_end = cue.end

    # No text lost, none duplicated (prefix excluded -- it is presentation).
    assert _normalized(" ".join(c.text for c in result.cues)) == _normalized(
        " ".join(s["text"] for s in segments)
    )


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_reflow_is_idempotent(name):
    segments, style, speakers = FIXTURES[name]
    once = reflow(segments, style, speakers)
    round_trip = [
        {"start": c.start, "end": c.end, "text": c.text, "speaker": c.speaker}
        for c in once.cues
    ]
    twice = reflow(round_trip, style, speakers)
    assert [c.render() for c in twice.cues] == [c.render() for c in once.cues]
    assert [(c.start, c.end) for c in twice.cues] == [(c.start, c.end) for c in once.cues]


@pytest.mark.parametrize("preset", sorted(PRESETS))
def test_every_preset_produces_legal_output(preset):
    style = SubtitleStyle.preset(preset)
    for segments, _, speakers in FIXTURES.values():
        validate(reflow(segments, style, speakers).cues, style)


def test_default_style_is_balanced():
    assert DEFAULT_STYLE.name == "balanced"
    assert DEFAULT_STYLE.latin_cps == 17.0
    assert PRESETS["broadcast"].latin_cps == 20.0


def test_over_long_cue_is_divided_not_left_as_dead_air():
    """Clamping to max_duration alone would drop the caption while the words
    are still being spoken."""
    text = ("I went to the store because I needed some milk and eggs for the "
            "recipe that my grandmother wrote down.")
    result = reflow([seg(0, 12, text)], BALANCED)
    assert len(result.cues) >= 3
    for cue in result.cues:
        assert cue.duration <= BALANCED.max_duration + EPS
    # Continuous coverage: no gap larger than the minimum separation.
    for a, b in zip(result.cues, result.cues[1:]):
        assert b.start - a.end <= BALANCED.min_gap + EPS


# ------------------------------------------------------------------- wiring


def test_transcriber_srt_is_reflowed(monkeypatch):
    from app.config import get_settings
    from sift_core.transcribe.transcriber import AudioTranscriber, TranscriptionSegment

    monkeypatch.setattr(get_settings(), "subtitle_reflow", True)
    segments = [TranscriptionSegment(0, 12, "I went to the store because I needed "
                                            "some milk and eggs for the recipe.")]
    out = AudioTranscriber.format_as_srt(segments)
    assert out.count("-->") > 1
    for line in out.splitlines():
        if "-->" not in line and not line.strip().isdigit():
            assert display_width(line) <= BALANCED.latin_max_display_width


def test_subtitle_reflow_false_restores_the_raw_path(monkeypatch):
    from app.config import get_settings
    from sift_core.transcribe.transcriber import AudioTranscriber, TranscriptionSegment

    monkeypatch.setattr(get_settings(), "subtitle_reflow", False)
    long_text = "I went to the store because I needed some milk and eggs today."
    segments = [TranscriptionSegment(0, 12, long_text)]
    assert AudioTranscriber.format_as_srt(segments) == (
        f"1\n00:00:00,000 --> 00:00:12,000\n{long_text}\n"
    )
    assert long_text in AudioTranscriber.format_as_vtt(segments)


def test_transcriber_speaker_srt_is_reflowed(monkeypatch):
    from app.config import get_settings
    from sift_core.transcribe.transcriber import AudioTranscriber, TranscriptionSegment

    monkeypatch.setattr(get_settings(), "subtitle_reflow", True)
    out = AudioTranscriber.format_as_srt_with_speakers(
        [TranscriptionSegment(0, 6, "Hello everyone and welcome back to the show.", "S0")]
    )
    assert "[S0] " in out
    out_unknown = AudioTranscriber.format_as_srt_with_speakers(
        [TranscriptionSegment(0, 4, "No speaker here.")]
    )
    assert "[SPEAKER_UNKNOWN] " in out_unknown


def test_fetched_captions_are_merged_by_the_route_formatter(monkeypatch):
    """The fetched-caption path is the one that most needs reflow, and it used
    to run a second, drifting copy of the SRT writer."""
    from app.api import transcript_fetch_routes as routes
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "subtitle_reflow", True)
    fragments = [
        {"start": i * 0.4, "end": i * 0.4 + 0.35, "text": t}
        for i, t in enumerate(["so if you", "look at the", "numbers here"])
    ]
    out = routes._format_srt(fragments)
    assert out.count("-->") < len(fragments)
    assert "so if you look at the numbers here" in out


def test_route_formatter_respects_the_reflow_flag(monkeypatch):
    from app.api import transcript_fetch_routes as routes
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "subtitle_reflow", False)
    fragments = [{"start": 0.0, "end": 0.35, "text": "so if you"},
                 {"start": 0.4, "end": 0.75, "text": "look at the"}]
    out = routes._format_srt(fragments)
    assert out.count("-->") == 2
    assert routes._format_vtt(fragments).startswith("WEBVTT")


def test_route_formatter_honours_a_per_request_preset(monkeypatch):
    from app.api import transcript_fetch_routes as routes
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "subtitle_reflow", True)
    long_line = [{"start": 0.0, "end": 6.0,
                  "text": "This line is comfortably wider than a single_line cue allows."}]
    out = routes._format_srt(long_line, "single_line")
    for line in out.splitlines():
        if "-->" not in line and not line.strip().isdigit() and line.strip():
            assert display_width(line) <= PRESETS["single_line"].latin_max_display_width


def test_style_from_settings_reads_the_flag():
    from sift_core.transcribe.subtitles import style_from_settings

    class Off:
        subtitle_reflow = False

    class On:
        subtitle_reflow = True
        subtitle_style_preset = "broadcast"

    assert style_from_settings(Off()) is None
    assert style_from_settings(On()).name == "broadcast"
