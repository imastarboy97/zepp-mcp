"""
Zepp Health MCP Server
Ask Claude about your Amazfit stress, sleep, and heart rate data.

Setup: set ZEPP_EMAIL + ZEPP_PASSWORD in your Claude Desktop config.
       Tokens are cached in ~/.zepp_mcp_token and auto-refreshed.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import datetime

from mcp.server.fastmcp import FastMCP

from .stress_analyzer import format_report, parse_stress_events, summarize_hr_proxy, summarize_stress
from .zepp_client import ZeppClient

mcp = FastMCP("zepp-health")


@mcp.tool()
def analyze_stress(days: int = 7, show_hourly: bool = False) -> str:
    """
    Analyze your stress levels for the past N days.
    Uses real Amazfit scores when available, falls back to HR variability proxy.

    Args:
        days: Days to analyze (1–30). Default 7.
        show_hourly: Show hour-by-hour breakdown. Default False.
    """
    client = ZeppClient()

    # Try native stress scores first
    try:
        events = client.get_stress_events(days=min(days, 30))
        points = parse_stress_events(events)
        if points:
            return format_report(summarize_stress(points), show_hourly)
    except Exception:
        pass

    # Fall back to HR variability proxy
    readings = client.get_heart_rate_readings(days=min(days, 30))
    return format_report(summarize_hr_proxy(readings), show_hourly)


@mcp.tool()
def get_sleep(days: int = 7) -> str:
    """
    Fetch sleep data: deep/light sleep duration per night.

    Args:
        days: Days to fetch (1–30). Default 7.
    """
    summaries = ZeppClient().get_sleep_summaries(days=min(days, 30))
    if not summaries:
        return "No sleep data. Make sure your watch synced with the Zepp app recently."

    lines = [f"## Sleep — Last {days} Days\n"]
    for s in summaries:
        slp  = s.get("sleep") or {}
        stp  = s.get("steps") or {}
        deep, light = slp.get("dp", 0), slp.get("lt", 0)
        st, ed = slp.get("st"), slp.get("ed")
        times = f" | {_fmt_ts(st)}→{_fmt_ts(ed)}" if st and ed else ""
        lines.append(
            f"**{s['date']}** — {deep+light}min total | deep {deep}min | "
            f"light {light}min{times} | steps {stp.get('ttl','N/A')}"
        )
    return "\n".join(lines)


@mcp.tool()
def get_heart_rate(days: int = 1) -> str:
    """
    Fetch heart rate summary (avg/min/max per day).

    Args:
        days: Days to fetch (1–7). Default 1.
    """
    readings = ZeppClient().get_heart_rate_readings(days=min(days, 7))
    if not readings:
        return "No heart rate data available."

    by_date: dict[str, list[int]] = defaultdict(list)
    for r in readings:
        by_date[r["date"]].append(r["hr"])

    lines = [f"## Heart Rate — Last {days} Day(s)\n"]
    for d, hrs in sorted(by_date.items()):
        lines.append(
            f"**{d}** — avg {round(statistics.mean(hrs),1)} bpm | "
            f"min {min(hrs)} | max {max(hrs)} | {len(hrs)} readings"
        )
    return "\n".join(lines)


@mcp.tool()
def get_today_overview() -> str:
    """Quick health snapshot for today: steps, HR, stress, and last night's sleep."""
    client = ZeppClient()
    lines  = [f"## Today ({_fmt_ts(None, date_only=True)})\n"]

    try:
        summaries = client.get_sleep_summaries(days=2)
        if summaries:
            s   = summaries[-1]
            slp = s.get("sleep") or {}
            stp = s.get("steps") or {}
            if stp:
                lines.append(f"**Steps:** {stp.get('ttl','N/A')}")
            if slp:
                lines.append(f"**Last night's sleep:** {slp.get('dp',0)+slp.get('lt',0)}min "
                             f"| deep {slp.get('dp',0)}min")
    except Exception as e:
        lines.append(f"**Steps/Sleep:** unavailable ({e})")

    try:
        hrs = [r["hr"] for r in client.get_heart_rate_readings(days=1)]
        if hrs:
            lines.append(f"**Heart rate:** avg {round(statistics.mean(hrs),1)} bpm "
                        f"| min {min(hrs)} | max {max(hrs)}")
    except Exception:
        pass

    try:
        events = client.get_stress_events(days=1)
        points = parse_stress_events(events)
        if points:
            s = summarize_stress(points)
            if s:
                lines.append(f"**Stress:** avg {s[0].avg}/100 | peak {s[0].peak}/100 "
                            f"at {s[0].peak_hour:02d}:00")
    except Exception:
        pass

    return "\n".join(lines)


def _fmt_ts(ts: int | None, date_only: bool = False) -> str:
    if ts is None:
        return datetime.now().strftime("%Y-%m-%d") if date_only else "?"
    dt = datetime.fromtimestamp(ts)
    return dt.strftime("%Y-%m-%d") if date_only else dt.strftime("%H:%M")


def main():
    mcp.run()


if __name__ == "__main__":
    main()
