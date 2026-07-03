#!/usr/bin/env python3
"""Scrape player positions from footywire.com and save to data/raw/player_positions.csv.

Run with:
    .venv/bin/python scripts/scrape_positions.py
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from afl import config  # noqa: E402  (for USER_AGENT + DATA_DIR)

OUT = ROOT / "data" / "raw" / "player_positions.csv"
PLAYER_STATS = ROOT / "data" / "raw" / "player_stats.pkl"

# Map our team names → footywire URL slug
_TEAM_SLUG: dict[str, str] = {
    "Adelaide":            "adelaide-crows",
    "Brisbane Lions":      "brisbane-lions",
    "Carlton":             "carlton-blues",
    "Collingwood":         "collingwood-magpies",
    "Essendon":            "essendon-bombers",
    "Fremantle":           "fremantle-dockers",
    "Geelong Cats":        "geelong-cats",
    "Geelong":             "geelong-cats",
    "Gold Coast":          "gold-coast-suns",
    "Greater Western Sydney": "greater-western-sydney-giants",
    "GWS":                 "greater-western-sydney-giants",
    "Hawthorn":            "hawthorn-hawks",
    "Melbourne":           "melbourne-demons",
    "North Melbourne":     "north-melbourne-kangaroos",
    "Port Adelaide":       "port-adelaide-power",
    "Richmond":            "richmond-tigers",
    "St Kilda":            "st-kilda-saints",
    "Sydney":              "sydney-swans",
    "West Coast":          "west-coast-eagles",
    "Western Bulldogs":    "western-bulldogs",
}

# Broad position groups used for analysis
_POS_GROUP: dict[str, str] = {
    "Ruck":                 "Ruck",
    "Ruckman":              "Ruck",
    "Centre":               "Midfielder",
    "Wing":                 "Midfielder",
    "Midfielder":           "Midfielder",
    "Midfield":             "Midfielder",
    "Half Back Flank":      "Half Back",
    "Half-Back Flank":      "Half Back",
    "Half Back":            "Half Back",
    "Key Defender":         "Key Defender",
    "Key defender":         "Key Defender",
    "Full Back":            "Key Defender",
    "Back Pocket":          "Key Defender",
    "Defender":             "Key Defender",
    "Half Forward Flank":   "Half Forward",
    "Half-Forward Flank":   "Half Forward",
    "Half Forward":         "Half Forward",
    "Small Forward":        "Forward",
    "Key Forward":          "Forward",
    "Forward Pocket":       "Forward",
    "Full Forward":         "Forward",
    "Forward":              "Forward",
}


def _player_slug(afl_name: str) -> str:
    """Convert 'Last, First' → 'first-last' for footywire URLs."""
    parts = str(afl_name).split(", ")
    if len(parts) == 2:
        first, last = parts[1], parts[0]
    else:
        words = str(afl_name).split()
        first = " ".join(words[:-1])
        last = words[-1]
    slug = f"{first}-{last}".lower()
    slug = re.sub(r"[^a-z0-9\-]", "", slug.replace(" ", "-").replace("'", ""))
    slug = re.sub(r"-+", "-", slug)
    return slug


def _pos_group(pos: str) -> str:
    for key, grp in _POS_GROUP.items():
        if key.lower() in pos.lower():
            return grp
    return "Midfielder"   # default fallback


session = requests.Session()
session.headers.update({"User-Agent": config.USER_AGENT})
_last_ts = 0.0


def _get(url: str) -> str | None:
    global _last_ts
    wait = 0.7 - (time.time() - _last_ts)
    if wait > 0:
        time.sleep(wait)
    _last_ts = time.time()
    try:
        r = session.get(url, timeout=15)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"  ERROR {url}: {e}")
        return None


def fetch_position(afl_name: str, team: str) -> tuple[str, str] | None:
    """Return (position_raw, position_group) or None on failure."""
    team_slug = _TEAM_SLUG.get(team)
    if not team_slug:
        return None
    pslug = _player_slug(afl_name)
    url = f"https://www.footywire.com/afl/footy/pp-{team_slug}--{pslug}"
    html = _get(url)
    if html is None:
        return None
    soup = BeautifulSoup(html, "html.parser")
    text_lines = [l.strip() for l in soup.get_text("\n").split("\n") if l.strip()]
    for i, line in enumerate(text_lines):
        if line == "Position:":
            if i + 1 < len(text_lines):
                pos_raw = text_lines[i + 1]
                return pos_raw, _pos_group(pos_raw)
    return None


def main() -> None:
    ps = pd.read_pickle(PLAYER_STATS)
    # All players active in 2025 or 2026 — get their most recent team
    recent = ps[ps["season"] >= 2025]
    player_team = (
        recent.sort_values("date")
        .groupby("player")["team"]
        .last()
        .reset_index()
    )
    print(f"Players to scrape: {len(player_team)}")

    # Load existing results so we can resume on interrupt
    if OUT.exists():
        existing = pd.read_csv(OUT)
        done = set(existing["player"].tolist())
        rows = existing.to_dict("records")
        print(f"Resuming — already have {len(done)} players")
    else:
        done, rows = set(), []

    for idx, row in player_team.iterrows():
        player, team = row["player"], row["team"]
        if player in done:
            continue

        result = fetch_position(player, team)
        if result:
            pos_raw, pos_group = result
        else:
            pos_raw, pos_group = "Unknown", "Midfielder"

        rows.append({"player": player, "team": team, "position_raw": pos_raw, "position_group": pos_group})
        done.add(player)

        n = len(rows)
        if n % 20 == 0 or n <= 5:
            print(f"  [{n}/{len(player_team)}] {player} ({team}) → {pos_group} ({pos_raw})")
            # Save incrementally
            pd.DataFrame(rows).to_csv(OUT, index=False)

    pd.DataFrame(rows).to_csv(OUT, index=False)
    print(f"\nDone. Saved {len(rows)} rows to {OUT}")
    print(pd.DataFrame(rows)["position_group"].value_counts())


if __name__ == "__main__":
    main()
