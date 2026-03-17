#!/usr/bin/env python3
"""
GitHub Star History Generator

Fetches historical starring data for all repos owned by a GitHub user,
builds a cumulative total-stars-over-time series, and generates a chart
for embedding in a profile README.

Usage:
    python update_star_history.py                   # default: AlexAnys
    GITHUB_USER=octocat python update_star_history.py
    python update_star_history.py --top 3           # test mode: top 3 repos only
"""

import os
import sys
import csv
import time
import argparse
from datetime import datetime, date, timedelta, timezone
from collections import defaultdict
from pathlib import Path

import requests

# ── Configuration ──────────────────────────────────────────────────────────────

USERNAME = os.environ.get("GITHUB_USER", "AlexAnys")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
INCLUDE_FORKS = True
EXCLUDE_REPOS: list = []  # e.g. ["AlexAnys/some-test-repo"]

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "star_history.csv"
ASSETS_DIR = ROOT / "assets"

# ── GitHub API helpers ─────────────────────────────────────────────────────────

session = requests.Session()
session.headers.update({"X-GitHub-Api-Version": "2022-11-28"})
if TOKEN:
    session.headers["Authorization"] = f"Bearer {TOKEN}"


def _paginate(url, params=None, accept=None):
    """Fetch all pages from a GitHub API endpoint."""
    headers = {"Accept": accept} if accept else {}
    params = dict(params or {})
    results = []
    while url:
        resp = session.get(url, params=params, headers=headers)

        # Handle rate limiting
        if resp.status_code == 403 and "rate limit" in resp.text.lower():
            reset = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
            wait = max(reset - time.time(), 5)
            print(f"  ⏳ Rate limited. Waiting {wait:.0f}s...")
            time.sleep(wait + 1)
            continue

        resp.raise_for_status()
        data = resp.json()
        if not data:
            break
        results.extend(data)
        remaining = resp.headers.get("X-RateLimit-Remaining", "?")
        print(f"    page {len(results) // 100 + 1} — {len(data)} items (API remaining: {remaining})")
        url = resp.links.get("next", {}).get("url")
        params = {}  # next URL includes params
    return results


def get_repos(username):
    """Get all public repos with stars, owned by the user."""
    print(f"🔍 Fetching repos for @{username}...")
    repos = _paginate(
        f"https://api.github.com/users/{username}/repos",
        params={"type": "owner", "per_page": 100, "sort": "stars", "direction": "desc"},
        accept="application/vnd.github+json",
    )
    filtered = [
        r for r in repos
        if r["stargazers_count"] > 0
        and (INCLUDE_FORKS or not r["fork"])
        and r["full_name"] not in EXCLUDE_REPOS
    ]
    print(f"📦 {len(filtered)} repos with stars (out of {len(repos)} total)\n")
    return filtered


def get_star_dates(repo_full_name, star_count):
    """Get all starring timestamps for a repo."""
    print(f"  ⭐ {repo_full_name} ({star_count:,} stars)")
    stargazers = _paginate(
        f"https://api.github.com/repos/{repo_full_name}/stargazers",
        params={"per_page": 100},
        accept="application/vnd.github.star+json",
    )
    dates = []
    for sg in stargazers:
        ts = sg.get("starred_at")
        if ts:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            dates.append(dt.date())
    print(f"    ✓ {len(dates)} events retrieved\n")
    return dates


# ── Data processing ────────────────────────────────────────────────────────────

def build_history(username, top_n=None):
    """Build cumulative star history by fetching all starring events."""
    repos = get_repos(username)
    if top_n:
        repos = repos[:top_n]
        print(f"🧪 Test mode: processing top {top_n} repos only\n")

    all_dates = []
    total_expected = sum(r["stargazers_count"] for r in repos)
    print(f"📡 Fetching starring events (~{total_expected:,} stars across {len(repos)} repos)...\n")

    for repo in repos:
        dates = get_star_dates(repo["full_name"], repo["stargazers_count"])
        all_dates.extend(dates)

    if not all_dates:
        print("❌ No starring events found!")
        return [], []

    # Aggregate by day
    daily = defaultdict(int)
    for d in all_dates:
        daily[d] += 1

    # Build cumulative series (every day from first star to today)
    start = min(daily)
    end = date.today()
    dates_out, totals_out = [], []
    cumulative = 0
    current = start
    while current <= end:
        cumulative += daily.get(current, 0)
        dates_out.append(current)
        totals_out.append(cumulative)
        current += timedelta(days=1)

    print(f"✅ History: {dates_out[0]} → {dates_out[-1]}")
    print(f"   Retrieved {len(all_dates):,} / {total_expected:,} expected starring events")
    print(f"   Current total: {totals_out[-1]:,} ★\n")
    return dates_out, totals_out


def load_csv():
    """Load existing star history from CSV, if available."""
    if not DATA_FILE.exists():
        return [], []
    dates, totals = [], []
    with open(DATA_FILE) as f:
        for row in csv.DictReader(f):
            dates.append(date.fromisoformat(row["date"]))
            totals.append(int(row["total_stars"]))
    return dates, totals


def save_csv(dates, totals):
    """Save the cumulative star history to CSV."""
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "total_stars"])
        for d, t in zip(dates, totals):
            w.writerow([d.isoformat(), t])
    print(f"💾 Saved {DATA_FILE}")


# ── Chart generation ───────────────────────────────────────────────────────────

THEMES = {
    "light": {
        "bg": "#ffffff",
        "line": "#3B82F6",
        "fill_top": 0.18,
        "fill_bottom": 0.02,
        "title_color": "#111827",
        "subtitle_color": "#6b7280",
        "spine_color": "#e5e7eb",
        "grid_color": "#f0f0f0",
        "tick_color": "#9ca3af",
        "milestone_color": "#d1d5db",
        "milestone_text": "#9ca3af",
        "dot_color": "#2563eb",
    },
    "dark": {
        "bg": "#0d1117",
        "line": "#58a6ff",
        "fill_top": 0.22,
        "fill_bottom": 0.02,
        "title_color": "#e6edf3",
        "subtitle_color": "#8b949e",
        "spine_color": "#30363d",
        "grid_color": "#161b22",
        "tick_color": "#484f58",
        "milestone_color": "#21262d",
        "milestone_text": "#484f58",
        "dot_color": "#58a6ff",
    },
}


def _find_milestones(dates, totals):
    """Find dates when star milestones were crossed."""
    milestones = []
    for target in [500, 1000, 2000, 3000]:
        if target > totals[-1]:
            break
        for i, t in enumerate(totals):
            if t >= target:
                milestones.append((dates[i], target))
                break
    return milestones


def generate_charts(dates, totals):
    """Generate light and dark theme charts."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.ticker import FuncFormatter, MultipleLocator
    import numpy as np

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    total = totals[-1]
    span_days = (dates[-1] - dates[0]).days
    milestones = _find_milestones(dates, totals)

    for name, t in THEMES.items():
        # Taller ratio → steeper-looking growth curve
        fig = plt.figure(figsize=(8, 5), dpi=150)
        fig.patch.set_facecolor(t["bg"])

        # ── Title block ──
        fig.text(
            0.10, 0.95, f"★ {total:,}",
            fontsize=28, fontweight="bold", color=t["title_color"],
            va="top",
        )
        fig.text(
            0.10, 0.875,
            f"Total GitHub Stars  ·  {span_days} days  ·  all repos",
            fontsize=10, color=t["subtitle_color"], va="top",
        )

        # ── Chart area ──
        ax = fig.add_axes([0.10, 0.10, 0.86, 0.62])
        ax.set_facecolor(t["bg"])

        # Clean area fill
        ax.fill_between(dates, totals, alpha=t["fill_top"], color=t["line"], linewidth=0)

        # Main line
        ax.plot(
            dates, totals,
            color=t["line"], linewidth=3,
            solid_capstyle="round", solid_joinstyle="round",
            zorder=5,
        )

        # End-point dot
        ax.plot(dates[-1], totals[-1], "o",
                color=t["dot_color"], markersize=7,
                markeredgecolor=t["bg"], markeredgewidth=2, zorder=6)

        # ── Milestone dots on the curve (subtle) ──
        for mdate, mvalue in milestones:
            ax.plot(mdate, mvalue, "o",
                    color=t["line"], markersize=4,
                    markeredgecolor=t["bg"], markeredgewidth=1.5, zorder=6)

        # ── Axes styling ──
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        for s in ("bottom", "left"):
            ax.spines[s].set_color(t["spine_color"])
            ax.spines[s].set_linewidth(0.5)

        ax.tick_params(colors=t["tick_color"], labelsize=9, length=0)

        # X-axis
        if span_days > 730:
            ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
            date_fmt = "%b %Y"
        elif span_days > 365:
            ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
            date_fmt = "%b %Y"
        elif span_days > 90:
            ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
            date_fmt = "%b %Y"
        elif span_days > 30:
            ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0, interval=2))
            date_fmt = "%b %d"
        else:
            ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0))
            date_fmt = "%b %d"
        ax.xaxis.set_major_formatter(mdates.DateFormatter(date_fmt))
        fig.autofmt_xdate(rotation=0, ha="center")

        # Y-axis: clean intervals
        y_max = total * 1.08
        if total > 5000:
            ax.yaxis.set_major_locator(MultipleLocator(1000))
        elif total > 2000:
            ax.yaxis.set_major_locator(MultipleLocator(500))
        elif total > 500:
            ax.yaxis.set_major_locator(MultipleLocator(250))
        else:
            ax.yaxis.set_major_locator(MultipleLocator(100))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{int(x):,}"))

        ax.set_xlim(dates[0], dates[-1])
        ax.set_ylim(bottom=0, top=y_max)

        # Expand right margin slightly for milestone labels
        ax.margins(x=0.02)

        # Save
        path = ASSETS_DIR / f"star-history-{name}.png"
        fig.savefig(
            path, facecolor=t["bg"], edgecolor="none",
            bbox_inches="tight", pad_inches=0.3,
        )
        plt.close(fig)
        print(f"📊 Saved {path}")


# ── Main ───────────────────────────────────────────────────────────────────────

def quick_update(username):
    """Incremental update: read cached CSV + fetch current star counts.

    Only makes ~1 API call (repo list) instead of ~50 (full stargazer backfill).
    Used automatically when CSV data already exists.
    """
    print(f"⚡ Quick update mode (CSV exists)\n")

    # Load existing history
    dates, totals = load_csv()
    print(f"📂 Loaded {len(dates)} days of history from CSV")

    # Fetch current total
    repos = get_repos(username)
    current_total = sum(r["stargazers_count"] for r in repos)
    today = date.today()

    # Fill any gaps between last CSV date and today
    if dates:
        last_date = dates[-1]
        last_total = totals[-1]
        gap = (today - last_date).days
        if gap > 1:
            # Interpolate missing days (linear)
            daily_gain = (current_total - last_total) / gap
            for i in range(1, gap):
                fill_date = last_date + timedelta(days=i)
                dates.append(fill_date)
                totals.append(int(last_total + daily_gain * i))

    # Update or append today's value
    if dates and dates[-1] == today:
        totals[-1] = current_total
    else:
        dates.append(today)
        totals.append(current_total)

    print(f"✅ Updated: {current_total:,} ★ (as of {today})\n")
    return dates, totals


def main():
    parser = argparse.ArgumentParser(description="Generate GitHub star history chart")
    parser.add_argument("--top", type=int, default=None,
                        help="Only process top N repos (for testing)")
    parser.add_argument("--full", action="store_true",
                        help="Force full backfill (ignore cached CSV)")
    args = parser.parse_args()

    # Auto-detect mode: use quick update if CSV exists, full backfill otherwise
    if not args.full and DATA_FILE.exists():
        dates, totals = quick_update(USERNAME)
    else:
        dates, totals = build_history(USERNAME, top_n=args.top)

    if not dates:
        sys.exit(1)

    save_csv(dates, totals)
    generate_charts(dates, totals)

    print(f"\n🎉 Done! @{USERNAME}: {totals[-1]:,} ★ across all repos")


if __name__ == "__main__":
    main()
