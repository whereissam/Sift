"""KOL scorecard step 3: scores and the weekly digest (docs/kol-scorecard.md).

Pure functions over `JobStore.list_scorecard_calls()` — only verified calls
whose speaker is assigned to a KOL ever reach this module, so everything it
renders has been checked by a human.

Scoring
- score: Wilson lower bound (95%) of the hit rate, so 2/2 doesn't outrank
  40/60; the leaderboard shows only KOLs with `min_resolved` resolved calls
- bold hit: a correct call whose target was >= 25% away from the price when
  it was made (needs a price target with a baseline)
- too-vague rate: unresolvable / (resolved + unresolvable)
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional

BOLD_THRESHOLD = 0.25
MIN_RESOLVED = 5


@dataclass
class KolScore:
    entity_id: str
    name: str
    handle: Optional[str]
    resolved: int
    hits: int
    hit_rate: Optional[float]
    score: float
    bold_hits: int
    too_vague: int
    too_vague_rate: Optional[float]
    open_calls: int

    @property
    def label(self) -> str:
        return f"@{self.handle}" if self.handle else self.name

    def to_dict(self) -> dict:
        return {**asdict(self), "label": self.label}


def wilson_lower_bound(hits: int, n: int, z: float = 1.96) -> float:
    if n == 0:
        return 0.0
    p = hits / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / (1 + z * z / n)


def boldness(target: Optional[dict]) -> Optional[float]:
    """How far the target was from the price when the call was made, in the
    called direction (0.5 = a 50% move). None without a baseline."""
    if not target or not target.get("baseline"):
        return None
    base, value = target["baseline"], target["value"]
    move = (value - base) / base if target["comparator"] == ">=" else (base - value) / base
    return max(move, 0.0)


def _when(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _label(call: dict) -> str:
    return f"@{call['kol_x_handle']}" if call.get("kol_x_handle") else call["kol_name"]


def build_leaderboard(calls: list[dict], *, min_resolved: int = MIN_RESOLVED) -> list[KolScore]:
    by_kol: dict[str, list[dict]] = defaultdict(list)
    for call in calls:
        by_kol[call["kol_entity_id"]].append(call)

    scores = []
    for entity_id, kol_calls in by_kol.items():
        resolved = [c for c in kol_calls if c["resolution"] in ("true", "false")]
        hits = [c for c in resolved if c["resolution"] == "true"]
        vague = sum(1 for c in kol_calls if c["resolution"] == "unresolvable")
        if len(resolved) < min_resolved:
            continue
        first = kol_calls[0]
        scores.append(KolScore(
            entity_id=entity_id,
            name=first["kol_name"],
            handle=first.get("kol_x_handle"),
            resolved=len(resolved),
            hits=len(hits),
            hit_rate=len(hits) / len(resolved) if resolved else None,
            score=round(wilson_lower_bound(len(hits), len(resolved)), 3),
            bold_hits=sum(1 for c in hits if (boldness(c["target"]) or 0) >= BOLD_THRESHOLD),
            too_vague=vague,
            too_vague_rate=vague / (len(resolved) + vague) if (resolved or vague) else None,
            open_calls=sum(1 for c in kol_calls if c["resolution"] == "pending"),
        ))
    return sorted(scores, key=lambda s: (-s.score, -s.resolved, s.name.lower()))


# ---------- digest ----------


def _link(call: dict) -> str:
    seconds = call.get("timestamp_start")
    url = call.get("source_url")
    stamp = ""
    if seconds is not None:
        total = int(seconds)
        h, m, s = total // 3600, total % 3600 // 60, total % 60
        stamp = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
    if not url:
        return f"[{stamp}]" if stamp else ""
    if seconds is not None and ("youtube.com" in url or "youtu.be" in url):
        url = f"{url}{'&' if '?' in url else '?'}t={int(seconds)}s"
    return f"[▶ {stamp or 'source'}]({url})"


def _day(value: Optional[str]) -> str:
    return value[:10] if value else "?"


def _usd(value: float) -> str:
    return f"${value:,.2f}" if value < 100 else f"${value:,.0f}"


def _target_text(target: Optional[dict]) -> str:
    if not target:
        return ""
    text = f"{target['asset']} {'≥' if target['comparator'] == '>=' else '≤'} {_usd(target['value'])}"
    bold = boldness(target)
    if bold is not None:
        text += f" ({'+' if target['comparator'] == '>=' else '−'}{bold:.0%} from {_usd(target['baseline'])})"
    return text


def _direction(target: Optional[dict]) -> Optional[str]:
    if not target or not target.get("baseline"):
        return None
    if target["comparator"] == ">=" and target["value"] > target["baseline"]:
        return "bullish"
    if target["comparator"] == "<=" and target["value"] < target["baseline"]:
        return "bearish"
    return None


def build_digest(
    calls: list[dict],
    contradictions: list[dict],
    *,
    start: datetime,
    end: datetime,
    title: str = "Crypto Calls Weekly",
    min_resolved: int = MIN_RESOLVED,
    corrections_url: Optional[str] = None,
) -> tuple[str, dict]:
    """Markdown for calls in [start, end), plus the numbers behind it."""

    def in_window(value: Optional[str]) -> bool:
        when = _when(value)
        return bool(when and start <= when < end)

    came_due = [c for c in calls if c["resolution"] != "pending" and in_window(c["resolved_at"])]
    new_calls = [c for c in calls if in_window(c["made_at"])]
    bold_new = sorted(
        (c for c in new_calls if c["resolution"] == "pending"),
        key=lambda c: (boldness(c["target"]) is None, -(boldness(c["target"]) or 0)),
    )[:5]
    leaderboard = build_leaderboard(calls, min_resolved=min_resolved)

    by_id = {c["claim_id"]: c for c in calls}
    flips = []
    for row in contradictions:
        a, b = by_id.get(row["claim_id_a"]), by_id.get(row["claim_id_b"])
        if not a or not b or a["kol_entity_id"] != b["kol_entity_id"]:
            continue
        earlier, later = sorted((a, b), key=lambda c: c["made_at"] or "")
        if in_window(later["made_at"]):
            flips.append((earlier, later))

    consensus = []
    by_asset: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for c in new_calls:
        side = _direction(c["target"])
        if side:
            by_asset[c["target"]["asset"]][side].add(_label(c))
    for asset, sides in sorted(by_asset.items()):
        total = len(sides["bullish"] | sides["bearish"])
        if total < 3:
            continue
        major = max(("bullish", "bearish"), key=lambda s: len(sides[s]))
        minor = "bearish" if major == "bullish" else "bullish"
        if len(sides[major]) / total < 2 / 3:
            continue
        line = f"- {len(sides[major])} of {total} KOLs {major} on {asset}"
        if sides[minor]:
            line += f"; contrarian: {', '.join(f'**{k}**' for k in sorted(sides[minor]))}"
        consensus.append(line)

    last_day = datetime.fromtimestamp(end.timestamp() - 1, tz=timezone.utc)
    episodes = {c["episode_id"] for c in calls if in_window(c["made_at"]) or in_window(c["resolved_at"])}
    kols = {c["kol_entity_id"] for c in new_calls + came_due}
    out = [
        f"# {title} — {start.date().isoformat()} to {last_day.date().isoformat()}",
        f"{len(kols)} KOLs · {len(episodes)} episodes · {len(new_calls)} new calls · "
        f"{len(came_due)} came due",
        "",
    ]

    if came_due:
        out.append("## ✅❌ Calls that came due")
        for c in sorted(came_due, key=lambda c: c["resolved_at"]):
            mark = {"true": "✅", "false": "❌"}.get(c["resolution"], "➖")
            out.append(f"- {mark} **{_label(c)}**: “{c['text']}” · said {_day(c['made_at'])} {_link(c)}")
            if c["resolution"] == "unresolvable":
                out.append("  Too vague to check.")
            elif c.get("resolution_note"):
                out.append(f"  {c['resolution_note']}")
        out.append("")

    if bold_new:
        out.append("## 🆕 Boldest new calls")
        for c in bold_new:
            details = [d for d in (_target_text(c["target"]),
                                   f"due {_day(c['due_at'])}" if c.get("due_at") else "") if d]
            suffix = f" · {' · '.join(details)}" if details else ""
            out.append(f"- **{_label(c)}**: “{c['text']}”{suffix} {_link(c)}")
        out.append("")

    if flips:
        out.append("## 🔁 Changed their mind")
        for earlier, later in flips:
            out.append(
                f"- **{_label(later)}** said “{earlier['text']}” ({_day(earlier['made_at'])} "
                f"{_link(earlier)}) → “{later['text']}” ({_day(later['made_at'])} {_link(later)})"
            )
        out.append("")

    if consensus:
        out.append("## 🤝 Consensus vs. contrarian")
        out.extend(consensus)
        out.append("")

    out.append(f"## 🏆 Leaderboard (min. {min_resolved} resolved)")
    if leaderboard:
        out.append("| # | KOL | Resolved | Hit rate | Score | Bold hits | Too vague |")
        out.append("|---|-----|---------:|---------:|------:|----------:|----------:|")
        for i, s in enumerate(leaderboard, 1):
            vague = f"{s.too_vague_rate:.0%}" if s.too_vague_rate is not None else "–"
            out.append(f"| {i} | {s.label} | {s.resolved} | {s.hit_rate:.0%} | {s.score:.2f} | "
                       f"{s.bold_hits} | {vague} |")
    else:
        out.append(f"_No KOL has {min_resolved} resolved calls yet._")
    out.append("")

    correction = f"[Request a correction]({corrections_url})" if corrections_url else "Tell us"
    out += [
        "---",
        "AI-assisted, human-reviewed. Every quote links to the exact moment it was said.",
        f"Spotted a mistake? {correction} and we'll fix it.",
        "",
    ]

    stats = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "kols": len(kols),
        "episodes": len(episodes),
        "new_calls": len(new_calls),
        "came_due": len(came_due),
        "resolved_true": sum(1 for c in came_due if c["resolution"] == "true"),
        "resolved_false": sum(1 for c in came_due if c["resolution"] == "false"),
        "flip_flops": len(flips),
        "leaderboard_size": len(leaderboard),
    }
    return "\n".join(out), stats
