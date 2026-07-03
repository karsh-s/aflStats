"""Squiggle API client (https://api.squiggle.com.au/).

Squiggle is free and key-less but asks clients to identify themselves (handled
via the User-Agent in ``afl.http``). We use it for the match schedule, results,
venues and the ladder/standings.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from .. import http

BASE = "https://api.squiggle.com.au/"


def _query(q: str, **params) -> list[dict]:
    payload = {"q": q, **{k: v for k, v in params.items() if v is not None}}
    data = http.get_json(BASE, params=payload)
    return data.get(q, []) if isinstance(data, dict) else []


def teams() -> pd.DataFrame:
    return pd.DataFrame(_query("teams"))


def games(year: Optional[int] = None, round_: Optional[int] = None,
          *, completed_only: bool = False) -> pd.DataFrame:
    """Return games for a season (and optionally a single round).

    Columns of interest: year, round, roundname, date (local), hteam, ateam,
    hscore, ascore, winner, venue, complete (0-100), is_final.
    """
    rows = _query("games", year=year, round=round_)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in ("hscore", "ascore", "round", "complete", "is_final", "year"):
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if completed_only:
        df = df[df["complete"] == 100].copy()
    df = df.sort_values("date").reset_index(drop=True)
    return df


def games_range(start_year: int, end_year: int, *,
                completed_only: bool = False) -> pd.DataFrame:
    frames = [games(y, completed_only=completed_only)
              for y in range(start_year, end_year + 1)]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values("date").reset_index(drop=True)


def standings(year: int, round_: Optional[int] = None) -> pd.DataFrame:
    """Ladder as at a given round (or latest if round omitted)."""
    return pd.DataFrame(_query("standings", year=year, round=round_))


def upcoming(year: int, round_: int) -> pd.DataFrame:
    """Fixtures for a round that has not yet been played."""
    return games(year, round_)
