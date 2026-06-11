"""
Stress analysis from Zepp health data.

Native mode:  real Amazfit stress scores (0–100) from the events API.
Proxy mode:   derived from heart rate variability when native unavailable.

Stress thresholds (per Zepp app):
  0–39  Relaxed  |  40–59  Normal  |  60–79  Medium  |  80+  High
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class DailySummary:
    date: str
    avg: float
    peak: float
    peak_hour: int
    calm_hour: int
    source: str                          # "native" or "proxy"
    hourly: dict[int, float] = field(default_factory=dict)


def _label(score: float) -> str:
    if score <= 39:  return "Relaxed"
    if score <= 59:  return "Normal"
    if score <= 79:  return "Medium"
    return "High"


# ── Native stress ─────────────────────────────────────────────────────────────

def parse_stress_events(events: list[dict]) -> list[tuple[str, int, int]]:
    """Parse all_day_stress events → list of (date_str, hour, value)."""
    points = []
    for event in events:
        if "data" not in event:
            continue
        try:
            for r in json.loads(event["data"]):
                v, t = int(r.get("value", 0)), int(r.get("time", 0))
                if 0 < v <= 100 and t > 0:
                    dt = datetime.fromtimestamp(t / 1000)
                    points.append((dt.strftime("%Y-%m-%d"), dt.hour, v))
        except Exception:
            pass
    return sorted(points)


def summarize_stress(points: list[tuple[str, int, int]]) -> list[DailySummary]:
    by_date: dict[str, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))
    for date, hour, val in points:
        by_date[date][hour].append(val)
    return _build_summaries(by_date, source="native")


# ── HR variability proxy ──────────────────────────────────────────────────────

def summarize_hr_proxy(readings: list[dict]) -> list[DailySummary]:
    by_date: dict[str, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))
    for r in readings:
        by_date[r["date"]][r["hour"]].append(r["hr"])

    # Convert HR windows → proxy stress scores
    stress_by_date: dict[str, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))
    for date, hours in by_date.items():
        all_hrs = sorted(h for hrs in hours.values() for h in hrs)
        resting  = statistics.mean(all_hrs[:max(1, len(all_hrs)//10)])
        for hour, hrs in hours.items():
            if len(hrs) < 2:
                continue
            diffs  = [abs(hrs[i+1]-hrs[i]) for i in range(len(hrs)-1)]
            sdsd   = statistics.stdev(diffs) if len(diffs) > 1 else diffs[0]
            elev   = max(0.0, statistics.mean(hrs) - resting)
            score  = int(max(0, min(100, (8-sdsd)/8*60*0.6 + elev*2*0.4)))
            stress_by_date[date][hour].append(score)

    return _build_summaries(stress_by_date, source="proxy")


# ── Shared ───────────────────────────────────────────────────────────────────

def _build_summaries(by_date: dict, source: str) -> list[DailySummary]:
    summaries = []
    for date, hours in sorted(by_date.items()):
        hourly = {h: round(statistics.mean(vs), 1) for h, vs in hours.items() if vs}
        if not hourly:
            continue
        all_vals = [v for vs in hours.values() for v in vs]
        peak_h   = max(hourly, key=hourly.get)
        calm_h   = min(hourly, key=hourly.get)
        summaries.append(DailySummary(
            date=date,
            avg=round(statistics.mean(all_vals), 1),
            peak=round(max(all_vals), 1),
            peak_hour=peak_h,
            calm_hour=calm_h,
            source=source,
            hourly=hourly,
        ))
    return summaries


def format_report(summaries: list[DailySummary], show_hourly: bool = False) -> str:
    if not summaries:
        return "No stress data available. Sync your watch with the Zepp app and try again."

    src  = "native Amazfit scores" if summaries[0].source == "native" else "HR variability proxy"
    lines = [f"## Stress Report _{src}_\n"]

    overall    = statistics.mean(s.avg for s in summaries)
    worst_day  = max(summaries, key=lambda s: s.peak)
    calmest    = min(summaries, key=lambda s: s.avg)

    lines += [
        f"**Period:** {summaries[0].date} → {summaries[-1].date}",
        f"**Overall avg:** {overall:.1f}/100 ({_label(overall)})",
        f"**Most stressed day:** {worst_day.date} — peak {worst_day.peak}/100 ({_label(worst_day.peak)}) at {worst_day.peak_hour:02d}:00",
        f"**Calmest day:** {calmest.date} — avg {calmest.avg}/100\n",
    ]

    # Time-of-day pattern across all days
    hour_scores: dict[int, list[float]] = defaultdict(list)
    for s in summaries:
        for h, v in s.hourly.items():
            hour_scores[h].append(v)
    if hour_scores:
        avg_by_hour = {h: statistics.mean(v) for h, v in hour_scores.items()}
        ph = max(avg_by_hour, key=avg_by_hour.get)
        ch = min(avg_by_hour, key=avg_by_hour.get)
        lines += [
            f"**Most stressed time of day:** {ph:02d}:00–{ph+1:02d}:00 ({avg_by_hour[ph]:.1f}/100 avg)",
            f"**Calmest time of day:** {ch:02d}:00–{ch+1:02d}:00 ({avg_by_hour[ch]:.1f}/100 avg)\n",
            "### Daily Breakdown\n",
        ]

    for s in summaries:
        bar = "█" * int(s.avg/10) + "░" * (10 - int(s.avg/10))
        lines.append(f"**{s.date}** [{bar}] {s.avg}/100 ({_label(s.avg)}) | peak {s.peak} @ {s.peak_hour:02d}:00")
        if show_hourly:
            for h in sorted(s.hourly):
                v = s.hourly[h]
                lines.append(f"  {h:02d}:00  {'▓'*int(v/20):<5}  {v:5.1f}  {_label(v)}")

    return "\n".join(lines)
