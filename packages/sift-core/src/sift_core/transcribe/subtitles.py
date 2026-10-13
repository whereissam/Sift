"""Subtitle-grade line breaking and cue timing (P23).

Raw ASR segments are not subtitles. Whisper emits 10-30 s segments that
overflow any player; fetched YouTube auto-captions emit 2-3 word cues that
flicker. This module is the single place that turns either into cues a human
can read, and the single writer for SRT/VTT.

The constraint model is tiered, because text is immutable and cues may not
leave their source time envelope, and under those two locks some ASR output
cannot satisfy every subtitle rule:

    Hard (invariant, never violated)
        text preserved, timestamps monotonic, no overlap, max_lines,
        line capacity, no mid-word Latin split (except over-long tokens),
        max_duration, speaker boundaries, cue inside its source envelope

    Soft (target, best effort then reported)
        reading speed, minimum duration, minimum gap

Splitting cannot lower reading speed -- 60 characters in 2.0 s reads at 30 cps
no matter where you cut it -- so reading speed is measured and reported as a
`SubtitleViolation`, never "enforced". Same for a 0.4 s "Okay." that can never
reach an 833 ms minimum inside its own envelope. `reflow` therefore neither
raises nor silently cheats.

Structural segmentation and timing are deliberately separate: `_split_text`
decides where breaks go, `_allocate_times` decides when cues start and end.
Phase 2 (word-level timestamps) replaces only `_allocate_times`.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Literal, Optional, Sequence

logger = logging.getLogger(__name__)

EPS = 1e-6


class ScriptProfile(str, Enum):
    """Which measuring and breaking rules apply to a piece of text."""

    LATIN = "latin"
    CJK = "cjk"


# --------------------------------------------------------------------------
# Character classes
# --------------------------------------------------------------------------

_CJK_RANGES = (
    (0x3000, 0x303F),  # CJK punctuation
    (0x3040, 0x30FF),  # kana
    (0x3400, 0x4DBF),  # CJK ext A
    (0x4E00, 0x9FFF),  # CJK unified
    (0xF900, 0xFAFF),  # compatibility ideographs
    (0xFF00, 0xFFEF),  # fullwidth forms
    (0xAC00, 0xD7AF),  # hangul syllables
)

SENTENCE_END = frozenset(".!?…。！？")
CLAUSE_PUNCT = frozenset(",;:、，；：—-")
CLOSING = frozenset(")]}」』》’”）")
OPENING = frozenset("([{「『《‘“（")

# Never start a line with these (they belong to the preceding text).
_NO_LINE_START = SENTENCE_END | CLAUSE_PUNCT | CLOSING
# Never end a line with these (they belong to the following text).
_NO_LINE_END = OPENING

# Breaking after these Latin words orphans them from what they modify.
AVOID_BREAK_AFTER = frozenset(
    {"a", "an", "the", "to", "of", "in", "on", "for", "at", "by", "is", "are", "was", "were"}
)
# These start a new syntactic unit -- a good place to break.
PREFER_BREAK_BEFORE = frozenset(
    {"but", "because", "although", "and", "so", "which", "that", "when", "while", "if", "or"}
)
# Chinese trailing particles: breaking before them strands the particle.
CJK_TRAILING_PARTICLES = frozenset("的了嗎吗呢吧啊麼么呢")
# Measure words: never break between a number and its measure word.
CJK_MEASURE_WORDS = frozenset(
    "個个件只隻張张次年月日天秒分"
    "鐘钟項项種种位台部本頁页元塊"
)

_WORD_CHAR = re.compile(r"[0-9A-Za-zÀ-ɏ'’]")


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


# --------------------------------------------------------------------------
# Measurement
# --------------------------------------------------------------------------


def display_width(text: str) -> int:
    """East-asian display width: W/F count 2, combining marks 0, else 1."""
    total = 0
    for ch in text:
        if unicodedata.combining(ch):
            continue
        total += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return total


def cjk_ratio(text: str) -> float:
    """Fraction of non-space characters that are CJK."""
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0.0
    return sum(1 for c in chars if _is_cjk(c)) / len(chars)


def cjk_equivalent_chars(text: str, style: "SubtitleStyle") -> float:
    """Netflix-style character count for a CJK line.

    A CJK character costs one unit. ASCII costs `cjk_ascii_char_cost` -- the
    single calibration constant in this module. It is deliberately *not*
    east-asian display width: `display_width("你好") == 4`, so measuring a
    16-character CJK limit in width units would halve the real capacity.
    """
    total = 0.0
    for ch in text:
        if unicodedata.combining(ch):
            continue
        if _is_cjk(ch):
            total += 1.0
        else:
            total += style.cjk_ascii_char_cost
    return total


# --------------------------------------------------------------------------
# Style
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SubtitleStyle:
    """Layout and timing targets.

    Defaults are inspired primarily by Netflix timed-text constraints
    (min 5/6 s, max 7 s, 2 lines, 16 CJK chars/line, 9 CJK cps). The Latin
    reading speed is *not* one single Netflix value, so the preset that uses
    their 20 cps is named `broadcast` and the more comfortable 17 cps default
    is named `balanced` rather than borrowing the brand for a number it does
    not specify.
    """

    name: str = "balanced"

    # Layout (hard)
    latin_max_display_width: int = 42
    cjk_max_chars: float = 16.0
    max_lines: int = 2

    # Timing (max_duration hard; the rest soft)
    min_duration: float = 5.0 / 6.0
    max_duration: float = 7.0
    min_gap: float = 0.08
    latin_cps: float = 17.0
    cjk_cps: float = 9.0

    # How far a cue may run past the end of its source audio. 0.0 keeps the
    # envelope strict, which is what makes the invariant clean and testable.
    # Raising it is the single knob that clears most min_duration violations.
    max_lead_out: float = 0.0

    # Merge policy. Merging is triggered by undershoot, never by legality --
    # that is what makes reflow idempotent.
    merge_max_gap: float = 1.5
    merge_min_fill: float = 0.5

    # Measurement calibration
    cjk_ascii_char_cost: float = 0.5
    cjk_ratio_threshold: float = 0.2

    @classmethod
    def preset(cls, name: str) -> "SubtitleStyle":
        try:
            return PRESETS[name]
        except KeyError:
            raise ValueError(
                f"Unknown subtitle preset {name!r}. Available: {sorted(PRESETS)}"
            ) from None


PRESETS: dict[str, SubtitleStyle] = {
    # Netflix-derived
    "broadcast": SubtitleStyle(name="broadcast", latin_cps=20.0),
    # Default: same layout, slower Latin pacing
    "balanced": SubtitleStyle(name="balanced"),
    # Auto-caption repair: merge fragments aggressively
    "youtube": SubtitleStyle(name="youtube", latin_cps=20.0, merge_min_fill=0.8),
    # Burned-in / clip captions
    "single_line": SubtitleStyle(
        name="single_line",
        latin_max_display_width=32,
        cjk_max_chars=12.0,
        max_lines=1,
        latin_cps=20.0,
    ),
}

DEFAULT_STYLE = PRESETS["balanced"]


def style_from_settings(settings: Any) -> Optional[SubtitleStyle]:
    """Resolve the configured style, or None when reflow is switched off.

    Takes the settings object rather than importing `app.config`, so this
    module stays free of application dependencies and trivially testable.
    """
    if not getattr(settings, "subtitle_reflow", True):
        return None
    return SubtitleStyle.preset(getattr(settings, "subtitle_style_preset", "balanced"))


def _capacity(profile: ScriptProfile, style: SubtitleStyle) -> float:
    if profile is ScriptProfile.LATIN:
        return float(style.latin_max_display_width)
    return float(style.cjk_max_chars)


def _measure(text: str, profile: ScriptProfile, style: SubtitleStyle) -> float:
    if profile is ScriptProfile.LATIN:
        return float(display_width(text))
    return cjk_equivalent_chars(text, style)


def profile_for_text(text: str, style: SubtitleStyle) -> ScriptProfile:
    """Pick rules from the text itself, never from the job's declared language.

    A Chinese episode quoting English API terminology has to be able to switch
    profile mid-segment.
    """
    return (
        ScriptProfile.CJK
        if cjk_ratio(text) >= style.cjk_ratio_threshold
        else ScriptProfile.LATIN
    )


def _cps_limit(text: str, style: SubtitleStyle) -> float:
    profile = profile_for_text(text, style)
    return style.cjk_cps if profile is ScriptProfile.CJK else style.latin_cps


# --------------------------------------------------------------------------
# Cues, violations, results
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SubtitleCue:
    """One displayed cue.

    `lines` never contains the speaker prefix: the prefix is presentation, not
    source text, so keeping it out lets the text-preservation invariant be a
    plain equality. It is still charged against the first line's capacity
    during segmentation -- the writer prepends nothing.

    After a merge a cue has more than one source, so there is no single
    "parent": `source_start` / `source_end` span every contributing segment.
    """

    start: float
    end: float
    lines: tuple[str, ...]
    speaker: Optional[str] = None
    prefix: str = ""
    source_segment_indices: tuple[int, ...] = ()
    source_start: float = 0.0
    source_end: float = 0.0

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    @property
    def duration(self) -> float:
        return self.end - self.start

    def render_lines(self) -> tuple[str, ...]:
        """Display lines, with the speaker prefix applied to the first."""
        if not self.prefix or not self.lines:
            return self.lines
        return (self.prefix + self.lines[0],) + self.lines[1:]

    def render(self) -> str:
        return "\n".join(self.render_lines())


ViolationKind = Literal["reading_speed", "min_duration", "min_gap"]


@dataclass(frozen=True)
class SubtitleViolation:
    """A soft target that could not be met for this source. Not an error."""

    cue_index: int
    kind: ViolationKind
    actual: float
    limit: float


@dataclass(frozen=True)
class ReflowResult:
    cues: list[SubtitleCue]
    violations: list[SubtitleViolation]

    def summary(self) -> str:
        if not self.violations:
            return f"{len(self.cues)} cues, all subtitle targets met"
        counts: dict[str, int] = {}
        for v in self.violations:
            counts[v.kind] = counts.get(v.kind, 0) + 1
        detail = ", ".join(f"{n} {kind}" for kind, n in sorted(counts.items()))
        return f"{len(self.cues)} cues, unmet targets: {detail}"


# --------------------------------------------------------------------------
# Source normalization
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Source:
    index: int
    start: float
    end: float
    text: str
    speaker: Optional[str]


def _get(seg: Any, key: str, default: Any = None) -> Any:
    if isinstance(seg, dict):
        return seg.get(key, default)
    return getattr(seg, key, default)


def _normalize_text(text: str) -> str:
    """Collapse whitespace, dropping the space at CJK/CJK boundaries.

    Dropping it matters for idempotency: re-flowing already-flowed cues joins
    lines back together, and a Chinese line break must not leave a space
    behind that was never in the source.
    """
    parts = str(text or "").split()
    if not parts:
        return ""
    out = parts[0]
    for part in parts[1:]:
        if out and _is_cjk(out[-1]) and _is_cjk(part[0]):
            out += part
        else:
            out += " " + part
    return out


def _join(left: str, right: str) -> str:
    if not left:
        return right
    if not right:
        return left
    if _is_cjk(left[-1]) and _is_cjk(right[0]):
        return left + right
    return left + " " + right


def _normalize(segments: Sequence[Any]) -> list[_Source]:
    """Accept dicts or objects with start/end/text/speaker; drop empties."""
    out: list[_Source] = []
    for i, seg in enumerate(segments):
        text = _normalize_text(_get(seg, "text", ""))
        if not text:
            continue
        try:
            start = float(_get(seg, "start", 0.0) or 0.0)
            end = float(_get(seg, "end", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if end < start:
            end = start
        speaker = _get(seg, "speaker")
        out.append(_Source(index=i, start=start, end=end, text=text, speaker=speaker))
    out.sort(key=lambda s: (s.start, s.end))
    return out


# --------------------------------------------------------------------------
# Break points
# --------------------------------------------------------------------------


def _break_candidates(text: str, profile: ScriptProfile) -> list[int]:
    """Indices i where `text[:i]` / `text[i:]` is a legal break."""
    candidates: list[int] = []
    n = len(text)
    for i in range(1, n):
        prev, cur = text[i - 1], text[i]
        if cur.isspace():
            continue
        if cur in _NO_LINE_START or prev in _NO_LINE_END:
            continue
        if prev.isspace():
            candidates.append(i)
            continue
        # A CJK character boundary is always breakable; a Latin word is not.
        if _is_cjk(prev) or _is_cjk(cur):
            if _WORD_CHAR.match(prev) and _WORD_CHAR.match(cur):
                continue  # inside an English word embedded in CJK text
            candidates.append(i)
            continue
        if profile is ScriptProfile.CJK and not (
            _WORD_CHAR.match(prev) and _WORD_CHAR.match(cur)
        ):
            candidates.append(i)
    return candidates


def _score_break(
    text: str,
    i: int,
    profile: ScriptProfile,
    style: SubtitleStyle,
    budget: float,
    tail_capacity: float,
) -> float:
    """Additive score -- a strict priority ladder picks terrible breaks.

    "I went to the store because I needed some milk." must not become
    "I went," / "to the store because I needed some milk." just because a
    comma outranks whitespace.
    """
    head = text[:i].rstrip()
    tail = text[i:].lstrip()
    if not head or not tail:
        return float("-inf")

    score = 0.0

    last = head[-1]
    if last in SENTENCE_END:
        score += 6.0
    elif last in CLAUSE_PUNCT:
        score += 3.0
    elif last in CLOSING:
        score += 2.0

    head_units = _measure(head, profile, style)
    fill = head_units / budget if budget > 0 else 1.0
    score -= 4.0 * abs(fill - 0.8)

    tail_units = _measure(tail, profile, style)
    if tail_units <= tail_capacity:
        # This is the last break of the cue -- balance the two lines.
        total = head_units + tail_units
        if total > 0:
            score += 3.0 * (1.0 - abs(head_units - tail_units) / total)
        if tail_units < 0.25 * tail_capacity:
            score -= 3.0

    if head_units < 0.2 * budget:
        score -= 3.0

    head_words = head.split()
    tail_words = tail.split()
    if head_words:
        last_word = head_words[-1].strip("".join(SENTENCE_END | CLAUSE_PUNCT)).lower()
        if last_word in AVOID_BREAK_AFTER:
            score -= 4.0
    if tail_words and tail_words[0].lower() in PREFER_BREAK_BEFORE:
        score += 2.0

    if tail and tail[0] in CJK_TRAILING_PARTICLES:
        score -= 4.0
    if tail and head and tail[0] in CJK_MEASURE_WORDS and head[-1].isdigit():
        score -= 3.0
    if tail and head and tail[0] in CJK_MEASURE_WORDS and _is_cjk(head[-1]):
        score -= 1.0

    return score


def _hard_cut(text: str, profile: ScriptProfile, style: SubtitleStyle, budget: float) -> int:
    """Largest prefix length that fits. The over-long-token escape hatch.

    Without this a `single_line` preset plus an 80-character URL has no legal
    output at all: "never split a Latin word" and "never exceed capacity"
    cannot both hold for a single token wider than one line.
    """
    total = 0.0
    for i, ch in enumerate(text):
        total += _measure(ch, profile, style)
        if total > budget:
            return max(1, i)
    return len(text)


def _take_line(
    text: str, style: SubtitleStyle, prefix: str = "", scored: bool = True
) -> tuple[str, str]:
    """Split off one line. Returns (line, remainder).

    `scored` picks the *best* break; without it the *fullest* legal break is
    taken. Chunk extent uses max-fill so it depends only on the text, while
    line layout uses scoring -- see `_split_text` for why that split matters.

    Two-pass profile resolution: seed capacity from the whole remaining text
    to generate candidates, then re-measure the chosen head under its *own*
    profile and retry with the tighter budget if it overflows. Terminates
    because the budget only ever shrinks.
    """
    text = text.strip()
    if not text:
        return "", ""

    profile = profile_for_text(text, style)
    budget = _capacity(profile, style) - _measure(prefix, profile, style)
    budget = max(budget, 1.0)

    for _ in range(3):
        if _measure(text, profile, style) <= budget:
            return text, ""

        candidates = [
            i
            for i in _break_candidates(text, profile)
            if _measure(text[:i].rstrip(), profile, style) <= budget
        ]
        if candidates:
            tail_capacity = _capacity(profile, style)
            best = (
                max(
                    candidates,
                    key=lambda i: _score_break(
                        text, i, profile, style, budget, tail_capacity
                    ),
                )
                if scored
                else max(candidates)
            )
            head, tail = text[:best].rstrip(), text[best:].lstrip()
        else:
            cut = _hard_cut(text, profile, style, budget)
            head, tail = text[:cut].rstrip(), text[cut:].lstrip()
            if not head:  # pathological: one character wider than the budget
                head, tail = text[:1], text[1:].lstrip()

        own = profile_for_text(head, style)
        own_budget = max(_capacity(own, style) - _measure(prefix, own, style), 1.0)
        if _measure(head, own, style) <= own_budget:
            return head, tail
        # The head measures differently under its own profile -- tighten.
        profile, budget = own, own_budget

    return head, tail


def _take_lines(
    text: str, style: SubtitleStyle, prefix: str, scored: bool
) -> tuple[list[str], str]:
    lines: list[str] = []
    remaining = text
    for line_no in range(style.max_lines):
        # Every cue carries the speaker prefix, so every cue's first line
        # pays for it.
        line_prefix = prefix if line_no == 0 else ""
        line, remaining = _take_line(remaining, style, line_prefix, scored)
        if not line:
            break
        lines.append(line)
        if not remaining:
            break
    return lines, remaining


def _lay_out(chunk: str, style: SubtitleStyle, prefix: str) -> tuple[str, ...]:
    """Break one cue's worth of text into lines. A pure function of the chunk.

    Scoring can prefer a break that leaves the second line overflowing; when
    it does, fall back to max-fill, which fits by construction.
    """
    lines, rest = _take_lines(chunk, style, prefix, scored=True)
    if rest:
        lines, rest = _take_lines(chunk, style, prefix, scored=False)
    if rest:  # pragma: no cover - max-fill consumed less than it should
        lines = lines or [chunk]
    return tuple(lines)


def _split_text(text: str, style: SubtitleStyle, prefix: str = "") -> list[tuple[str, ...]]:
    """Structural segmentation only: no timing decisions here.

    Two phases, and the separation is load-bearing for idempotency. Chunk
    extent (how much text one cue holds) is decided by max-fill, so it depends
    only on the text. Line layout inside a chunk is then decided by scoring,
    which uses a balance term that looks at the tail -- run that against a
    stream instead of a settled chunk and re-flowing an already-flowed cue
    picks a different break than the first pass did.
    """
    chunks: list[tuple[str, ...]] = []
    remaining = text.strip()
    guard = 0
    while remaining:
        guard += 1
        if guard > 10000:  # pragma: no cover - structural safety net
            chunks.append((remaining,))
            break
        lines, rest = _take_lines(remaining, style, prefix, scored=False)
        if not lines:
            break
        chunk = ""
        for line in lines:
            chunk = _join(chunk, line)
        chunks.append(_lay_out(chunk, style, prefix))
        remaining = rest
    return chunks or [(text,)]


# --------------------------------------------------------------------------
# Timing
# --------------------------------------------------------------------------


def _allocate_times(
    source: _Source,
    chunks: list[tuple[str, ...]],
    style: SubtitleStyle,
    prefix: str = "",
) -> list[SubtitleCue]:
    """Distribute the source span across chunks, proportional to width.

    Proportional interpolation is accurate to roughly +/-150 ms and is the
    only option while `TranscriptionSegment` carries no word timings. This is
    the Phase 2 swap point: word-boundary snapping replaces this function and
    nothing else.
    """
    weights = [max(display_width("".join(c)), 1) for c in chunks]
    total = float(sum(weights))
    span = max(source.end - source.start, 0.0)

    cues: list[SubtitleCue] = []
    cursor = source.start
    for i, (chunk, weight) in enumerate(zip(chunks, weights)):
        share = span * (weight / total) if total else 0.0
        start = cursor
        end = source.end if i == len(chunks) - 1 else min(cursor + share, source.end)
        cursor = end
        cues.append(
            SubtitleCue(
                start=start,
                end=max(end, start),
                lines=chunk,
                speaker=source.speaker,
                prefix=prefix,
                source_segment_indices=(source.index,),
                source_start=source.start,
                source_end=source.end,
            )
        )
    return cues


def _fill_ratio(cue: SubtitleCue, style: SubtitleStyle) -> float:
    profile = profile_for_text(cue.text, style)
    capacity = _capacity(profile, style) * len(cue.lines)
    if capacity <= 0:
        return 1.0
    return _measure(" ".join(cue.lines), profile, style) / capacity


def _needs_merge(cue: SubtitleCue, style: SubtitleStyle) -> bool:
    """Undershoot, not legality.

    Two already-conformant cues 80 ms apart must be left alone even though
    merging them would also be legal -- otherwise reflow is not idempotent.
    """
    if cue.duration + EPS < style.min_duration:
        return True
    return len(cue.lines) == 1 and _fill_ratio(cue, style) < style.merge_min_fill


def _relayout(
    cues: Sequence[SubtitleCue], style: SubtitleStyle
) -> Optional[SubtitleCue]:
    """Combine cues into one, or None if the result breaks a hard constraint."""
    text = ""
    for c in cues:
        text = _join(text, " ".join(c.lines))
    first = cues[0]
    chunks = _split_text(text, style, first.prefix)
    if len(chunks) != 1:
        return None
    start = min(c.start for c in cues)
    end = max(c.end for c in cues)
    if end - start > style.max_duration + EPS:
        return None
    indices: tuple[int, ...] = ()
    for c in cues:
        indices += c.source_segment_indices
    return SubtitleCue(
        start=start,
        end=end,
        lines=chunks[0],
        speaker=first.speaker,
        prefix=first.prefix,
        source_segment_indices=tuple(dict.fromkeys(indices)),
        source_start=min(c.source_start for c in cues),
        source_end=max(c.source_end for c in cues),
    )


def _merge_fragments(cues: list[SubtitleCue], style: SubtitleStyle) -> list[SubtitleCue]:
    """Coalesce fragmentary cues with a neighbour. Never across a speaker
    change, never across a long silence, never into an illegal result."""
    out: list[SubtitleCue] = []
    i = 0
    while i < len(cues):
        current = cues[i]
        while i + 1 < len(cues) and _needs_merge(current, style):
            nxt = cues[i + 1]
            if current.speaker != nxt.speaker:
                break
            if nxt.start - current.end > style.merge_max_gap:
                break
            merged = _relayout([current, nxt], style)
            if merged is None:
                break
            current = merged
            i += 1
        out.append(current)
        i += 1
    return out


def _refine_timing(
    cues: list[SubtitleCue], style: SubtitleStyle
) -> list[SubtitleCue]:
    """One operation, two purposes.

    Minimum duration and reading speed are both improved by giving a cue more
    time when time is available, so there is no separate
    `enforce_min_duration` -- just an extension into whatever slack exists,
    bounded by the neighbour and by the end of the audio.

    Reading speed is a *maximum*, never a target: a cue that already runs
    longer than its text needs is fine and must not be shortened to match, or
    continuous speech grows dead gaps between its own cues.
    """
    out: list[SubtitleCue] = []
    for idx, cue in enumerate(cues):
        chars = len(cue.text.replace("\n", " "))
        target = max(style.min_duration, chars / _cps_limit(cue.text, style))

        limit = cue.source_end + style.max_lead_out
        if idx + 1 < len(cues):
            limit = min(limit, cues[idx + 1].start - style.min_gap)

        end = cue.end
        if end < cue.start + target:
            # Too short: extend into the available slack.
            end = max(min(cue.start + target, limit), end)
        if end > limit:
            # Too close to the neighbour: pull back, but never below the
            # point where the cue would be starved -- report the gap instead.
            floor = min(cue.end, cue.start + style.min_duration)
            end = max(limit, floor)
        end = max(end, cue.start)
        out.append(replace(cue, end=end))
    return out


def _enforce_monotonic(cues: list[SubtitleCue]) -> list[SubtitleCue]:
    """Hard invariant: sorted, non-overlapping. Overlapping diarized sources
    are the realistic way this gets violated."""
    out: list[SubtitleCue] = []
    prev_end = float("-inf")
    for cue in cues:
        start = max(cue.start, prev_end)
        end = max(cue.end, start)
        prev_end = end
        out.append(replace(cue, start=start, end=end))
    return out


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def validate(cues: Sequence[SubtitleCue], style: SubtitleStyle) -> list[SubtitleViolation]:
    """Assert the hard invariants; collect the soft ones as violations."""
    violations: list[SubtitleViolation] = []
    prev: Optional[SubtitleCue] = None

    for i, cue in enumerate(cues):
        assert cue.end >= cue.start - EPS, f"cue {i}: end before start"
        assert len(cue.lines) <= style.max_lines, f"cue {i}: {len(cue.lines)} lines"
        assert cue.start >= cue.source_start - EPS, f"cue {i}: starts before source"
        envelope = max(cue.start, cue.source_end + style.max_lead_out)
        assert cue.end <= envelope + EPS, f"cue {i}: runs past source envelope"
        assert cue.duration <= style.max_duration + EPS, f"cue {i}: exceeds max_duration"
        if prev is not None:
            assert cue.start >= prev.end - EPS, f"cue {i}: overlaps previous"

        for line in cue.render_lines():
            profile = profile_for_text(line, style)
            capacity = _capacity(profile, style)
            assert _measure(line, profile, style) <= capacity + EPS, (
                f"cue {i}: line exceeds {profile.value} capacity: {line!r}"
            )

        if cue.duration + EPS < style.min_duration:
            violations.append(
                SubtitleViolation(i, "min_duration", cue.duration, style.min_duration)
            )
        chars = len(cue.text.replace("\n", " "))
        cps = chars / cue.duration if cue.duration > EPS else float("inf")
        limit = _cps_limit(cue.text, style)
        if cps > limit + EPS:
            violations.append(SubtitleViolation(i, "reading_speed", cps, limit))
        if prev is not None:
            gap = cue.start - prev.end
            if gap + EPS < style.min_gap:
                violations.append(SubtitleViolation(i, "min_gap", gap, style.min_gap))
        prev = cue

    return violations


# --------------------------------------------------------------------------
# Public entry points
# --------------------------------------------------------------------------


def split_segment(
    segment: Any, style: SubtitleStyle = DEFAULT_STYLE, index: int = 0
) -> list[SubtitleCue]:
    """Segment one source into spatially legal cues with interpolated times."""
    normalized = _normalize([segment])
    if not normalized:
        return []
    source = replace(normalized[0], index=index)
    prefix = f"[{source.speaker}] " if source.speaker else ""
    chunks = _split_text(source.text, style, prefix)
    cues = _allocate_times(source, chunks, style, prefix)
    return [c for cue in cues for c in _divide_over_long(cue, style, prefix)]


def _divide_over_long(
    cue: SubtitleCue, style: SubtitleStyle, prefix: str = ""
) -> list[SubtitleCue]:
    """`max_duration` is hard, and clamping alone would leave dead air.

    A cue whose text already fits one screen but whose span exceeds
    `max_duration` is divided again -- near the middle, at a legal break --
    with its time split proportionally, so the caption keeps up with the
    words instead of vanishing mid-sentence. Only text that cannot be divided
    at all (a single token) falls back to clamping.
    """
    if cue.duration <= style.max_duration + EPS:
        return [cue]

    text = ""
    for line in cue.lines:
        text = _join(text, line)

    profile = profile_for_text(text, style)
    candidates = _break_candidates(text, profile)
    if not candidates:
        return [replace(cue, end=cue.start + style.max_duration)]

    half = _measure(text, profile, style) / 2.0
    best = min(
        candidates,
        key=lambda i: abs(_measure(text[:i].rstrip(), profile, style) - half),
    )
    head, tail = text[:best].rstrip(), text[best:].lstrip()
    if not head or not tail:
        return [replace(cue, end=cue.start + style.max_duration)]

    head_units = max(_measure(head, profile, style), EPS)
    tail_units = max(_measure(tail, profile, style), EPS)
    boundary = cue.start + cue.duration * (head_units / (head_units + tail_units))

    first = replace(cue, end=boundary, lines=_lay_out(head, style, prefix))
    second = replace(cue, start=boundary, lines=_lay_out(tail, style, prefix))
    return _divide_over_long(first, style, prefix) + _divide_over_long(
        second, style, prefix
    )


def reflow(
    segments: Sequence[Any],
    style: SubtitleStyle = DEFAULT_STYLE,
    speaker_prefix: bool = False,
) -> ReflowResult:
    """Turn ASR segments into readable cues.

    Accepts dicts or objects exposing start/end/text/speaker, so the fetched
    caption path and the Whisper path share one implementation.
    """
    sources = _normalize(segments)
    cues: list[SubtitleCue] = []
    for source in sources:
        prefix = f"[{source.speaker}] " if (speaker_prefix and source.speaker) else ""
        chunks = _split_text(source.text, style, prefix)
        allocated = _allocate_times(source, chunks, style, prefix)
        for cue in allocated:
            cues.extend(_divide_over_long(cue, style, prefix))

    cues = _merge_fragments(cues, style)
    cues = _enforce_monotonic(cues)
    cues = _refine_timing(cues, style)
    cues = _enforce_monotonic(cues)
    violations = validate(cues, style)
    return ReflowResult(cues=cues, violations=violations)


# --------------------------------------------------------------------------
# The canonical writers
# --------------------------------------------------------------------------


def format_timestamp_srt(seconds: float) -> str:
    """HH:MM:SS,mmm"""
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis == 1000:
        millis, secs = 0, secs + 1
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def format_timestamp_vtt(seconds: float) -> str:
    """HH:MM:SS.mmm"""
    return format_timestamp_srt(seconds).replace(",", ".")


def format_srt(cues: Sequence[SubtitleCue]) -> str:
    lines: list[str] = []
    for i, cue in enumerate(cues, 1):
        lines.append(str(i))
        lines.append(
            f"{format_timestamp_srt(cue.start)} --> {format_timestamp_srt(cue.end)}"
        )
        lines.append(cue.render())
        lines.append("")
    return "\n".join(lines)


def format_vtt(cues: Sequence[SubtitleCue]) -> str:
    lines = ["WEBVTT", ""]
    for cue in cues:
        lines.append(
            f"{format_timestamp_vtt(cue.start)} --> {format_timestamp_vtt(cue.end)}"
        )
        lines.append(cue.render())
        lines.append("")
    return "\n".join(lines)


def reflow_to_srt(
    segments: Sequence[Any],
    style: SubtitleStyle = DEFAULT_STYLE,
    speaker_prefix: bool = False,
) -> str:
    result = reflow(segments, style, speaker_prefix)
    _log_violations(result)
    return format_srt(result.cues)


def reflow_to_vtt(
    segments: Sequence[Any],
    style: SubtitleStyle = DEFAULT_STYLE,
    speaker_prefix: bool = False,
) -> str:
    result = reflow(segments, style, speaker_prefix)
    _log_violations(result)
    return format_vtt(result.cues)


def _log_violations(result: ReflowResult) -> None:
    """Soft violations are information, never a reason to fail a transcription."""
    if result.violations:
        logger.info("Subtitle reflow: %s", result.summary())
