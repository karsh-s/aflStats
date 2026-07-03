"""AFL Tables scraper for player box-score statistics.

AFL Tables (https://afltables.com) publishes a full per-player statline for
every match. We scrape the season index to find each game page, then parse the
two team stat tables plus the match header (round / venue / date / home-away).

The result is a tidy one-row-per-player-per-game DataFrame, which the player
Elo and player-prop models consume.

Scraping is best-effort and cached aggressively; a single unparseable game is
skipped with a warning rather than failing the whole season.
"""
from __future__ import annotations

import re
import sys
from io import StringIO

import pandas as pd
from bs4 import BeautifulSoup

from .. import http
from .teams import normalise_team

SEASON_INDEX = "https://afltables.com/afl/seas/{year}.html"
GAME_URL = "https://afltables.com/afl/stats/games/{year}/{slug}"

# AFL Tables column code -> friendly name. We keep the props-relevant ones.
STAT_COLUMNS = {
    "KI": "kicks",
    "MK": "marks",
    "HB": "handballs",
    "DI": "disposals",
    "GL": "goals",
    "BH": "behinds",
    "HO": "hitouts",
    "TK": "tackles",
    "RB": "rebounds",
    "IF": "inside50s",
    "CL": "clearances",
    "CG": "clangers",
    "FF": "frees_for",
    "FA": "frees_against",
    "CP": "contested_poss",
    "UP": "uncontested_poss",
    "CM": "contested_marks",
    "MI": "marks_inside50",
    "1%": "one_percenters",
    "GA": "goal_assists",
}

_DATE_RE = re.compile(r"Date:\s*[A-Za-z]{3},\s*(\d{1,2}-[A-Za-z]{3}-\d{4})")
_ROUND_RE = re.compile(r"Round:\s*([0-9A-Za-z ]+?)\s+Venue:")
_VENUE_RE = re.compile(r"Venue:\s*(.+?)\s+Date:")


def _game_slugs(year: int) -> list[str]:
    html = http.get_text(SEASON_INDEX.format(year=year))
    slugs = re.findall(rf"stats/games/{year}/([0-9]+\.html)", html)
    # de-dupe while preserving order
    seen, out = set(), []
    for s in slugs:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _parse_header(tables: list[pd.DataFrame]) -> dict | None:
    hdr = tables[0]
    try:
        # Col 0 / last col are "←"/"→" nav arrows; real content is in col 1.
        meta_text = str(hdr.iloc[0, 1])
        home = normalise_team(str(hdr.iloc[1, 1]).strip())
        away = normalise_team(str(hdr.iloc[2, 1]).strip())
    except Exception:
        return None
    rnd = _ROUND_RE.search(meta_text)
    ven = _VENUE_RE.search(meta_text)
    dat = _DATE_RE.search(meta_text)
    return {
        "round_raw": rnd.group(1).strip() if rnd else "",
        "venue": ven.group(1).strip() if ven else "",
        "date": pd.to_datetime(dat.group(1), format="%d-%b-%Y", errors="coerce")
        if dat else pd.NaT,
        "home_team": home,
        "away_team": away,
    }


def _parse_player_table(tbl: pd.DataFrame, team: str, opponent: str,
                        is_home: bool, meta: dict, season: int) -> pd.DataFrame:
    # Columns are a 2-level MultiIndex ("<Team> Match Statistics ...", "KI"...)
    tbl = tbl.copy()
    tbl.columns = [c[1] if isinstance(c, tuple) else c for c in tbl.columns]
    if "Player" not in tbl.columns:
        return pd.DataFrame()
    # Drop the trailing summary rows (Rushed / Totals / Opposition).
    tbl = tbl[~tbl["Player"].isin(["Rushed", "Totals", "Opposition"])].copy()
    tbl = tbl[tbl["Player"].notna()]

    out = pd.DataFrame()
    out["player"] = tbl["Player"].astype(str).str.strip()
    for code, name in STAT_COLUMNS.items():
        if code in tbl.columns:
            out[name] = pd.to_numeric(tbl[code], errors="coerce").fillna(0)
        else:
            out[name] = 0
    out.insert(0, "season", season)
    out.insert(1, "round", meta["round_raw"])
    out.insert(2, "date", meta["date"])
    out.insert(3, "venue", meta["venue"])
    out.insert(4, "team", team)
    out.insert(5, "opponent", opponent)
    out.insert(6, "home", is_home)
    return out


def game_player_stats(year: int, slug: str) -> pd.DataFrame:
    html = http.get_text(GAME_URL.format(year=year, slug=slug))
    try:
        tables = pd.read_html(StringIO(html))
    except ValueError:
        return pd.DataFrame()
    if len(tables) < 5:
        return pd.DataFrame()
    meta = _parse_header(tables)
    if meta is None:
        return pd.DataFrame()

    home, away = meta["home_team"], meta["away_team"]
    # Player tables are the two whose top-level header contains the team name.
    home_tbl = _parse_player_table(tables[2], home, away, True, meta, year)
    away_tbl = _parse_player_table(tables[4], away, home, False, meta, year)
    frames = [f for f in (home_tbl, away_tbl) if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def season_player_stats(year: int, *, progress: bool = True) -> pd.DataFrame:
    """Scrape every player statline for a season. Cached per game page."""
    slugs = _game_slugs(year)
    frames = []
    for i, slug in enumerate(slugs, 1):
        if progress:
            print(f"  [{year}] game {i}/{len(slugs)}", end="\r", file=sys.stderr)
        try:
            df = game_player_stats(year, slug)
            if not df.empty:
                frames.append(df)
        except Exception as exc:  # noqa: BLE001 - keep going on bad pages
            print(f"\n  warn: {slug}: {exc}", file=sys.stderr)
    if progress:
        print(file=sys.stderr)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def season_player_stats_range(start: int, end: int) -> pd.DataFrame:
    frames = [season_player_stats(y) for y in range(start, end + 1)]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
