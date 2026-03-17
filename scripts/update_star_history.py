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
        "line": "#2563eb",
        "fill_alpha": 0.07,
        "title_color": "#111827",
        "subtitle_color": "#6b7280",
        "spine_color": "#e5e7eb",
        "grid_color": "#f3f4f6",
        "tick_color": "#9ca3af",
    },
    "dark": {
        "bg": "#0d1117",
        "line": "#58a6ff",
        "fill_alpha": 0.12,
        "title_color": "#e6edf3",
        "subtitle_color": "#8b949e",
        "spine_color": "#30363d",
        "grid_color": "#161b22",
        "tick_color": "#484f58",
    },
}


def generate_charts(dates, totals):
    """Generate light and dark theme charts."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.ticker import FuncFormatter, MaxNLocator

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    total = totals[-1]
    span_days = (dates[-1] - dates[0]).days

    for name, t in THEMES.items():
        fig = plt.figure(figsize=(10, 3.5), dpi=150)
        fig.patch.set_facecolor(t["bg"])

        # Title: star count + subtitle
        fig.text(
            0.06, 0.93, f"★ {total:,}",
            fontsize=24, fontweight="bold", color=t["title_color"],
            va="top", fontfamily="monospace",
        )
        fig.text(
            0.06, 0.79, "Total GitHub Stars · All Repos",
            fontsize=11, color=t["subtitle_color"], va="top",
        )

        # Chart axes (leave room for title)
        ax = fig.add_axes([0.07, 0.13, 0.89, 0.52])
        ax.set_facecolor(t["bg"])

        # Plot line + fill
        ax.plot(
            dates, totals,
            color=t["line"], linewidth=2.5,
            solid_capstyle="round", solid_joinstyle="round",
        )
        ax.fill_between(dates, totals, alpha=t["fill_alpha"], color=t["line"])

        # Spines
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        for s in ("bottom", "left"):
            ax.spines[s].set_color(t["spine_color"])
            ax.spines[s].set_linewidth(0.5)

        # Ticks & grid
        ax.tick_params(colors=t["tick_color"], labelsize=9, length=0)
        ax.grid(axis="y", color=t["grid_color"], linewidth=0.5)

        # X-axis: adaptive interval & format based on span
        if span_days > 730:
            ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
        elif span_days > 365:
            ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
        elif span_days > 90:
            ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
        elif span_days > 30:
            ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0, interval=2))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        else:
            ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        fig.autofmt_xdate(rotation=0, ha="center")

        # Y-axis
        ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{int(x):,}"))
        ax.yaxis.set_major_locator(MaxNLocator(nbins=5, integer=True))

        ax.set_xlim(dates[0], dates[-1])
        ax.set_ylim(bottom=0)

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
