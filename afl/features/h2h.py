"""Direct head-to-head history between two clubs.

Provides both a point-in-time feature (recent H2H win rate for the home side,
computed only from prior meetings) and an on-demand summary for reporting.
"""
from __future__ import annotations

import pandas as pd


def _completed(games: pd.DataFrame) -> pd.DataFrame:
    df = games[games.get("complete", 0) == 100].copy()
    return df.sort_values("date").reset_index(drop=True)


def attach_h2h(games: pd.DataFrame, window: int = 10) -> pd.DataFrame:
    """Add ``h2h_home_win_pct`` and ``h2h_home_avg_margin`` to each game.

    Looks at the last ``window`` meetings between the two clubs *before* the
    current match, regardless of which side was home, from the home team's view.
    """
    games = games.sort_values("date").reset_index(drop=True)
    completed = _completed(games)

    home_pct, home_margin = [], []
    for _, g in games.iterrows():
        a, b, when = g["hteam"], g["ateam"], g["date"]
        prior = completed[
            (completed["date"] < when)
            & (
                ((completed["hteam"] == a) & (completed["ateam"] == b))
                | ((completed["hteam"] == b) & (completed["ateam"] == a))
            )
        ].tail(window)
        if prior.empty:
            home_pct.append(0.5)
            home_margin.append(0.0)
            continue
        # margin from team a's perspective
        margin_a = prior.apply(
            lambda r: (r["hscore"] - r["ascore"]) if r["hteam"] == a
            else (r["ascore"] - r["hscore"]), axis=1)
        wins_a = (margin_a > 0).mean()
        home_pct.append(float(wins_a))
        home_margin.append(float(margin_a.mean()))

    games["h2h_home_win_pct"] = home_pct
    games["h2h_home_avg_margin"] = home_margin
    return games


def summary(games: pd.DataFrame, team_a: str, team_b: str,
            last: int | None = None) -> dict:
    """Human-readable H2H summary between two clubs (for reports/UI)."""
    completed = _completed(games)
    meetings = completed[
        ((completed["hteam"] == team_a) & (completed["ateam"] == team_b))
        | ((completed["hteam"] == team_b) & (completed["ateam"] == team_a))
    ].copy()
    if last:
        meetings = meetings.tail(last)
    if meetings.empty:
        return {"meetings": 0}

    margin_a = meetings.apply(
        lambda r: (r["hscore"] - r["ascore"]) if r["hteam"] == team_a
        else (r["ascore"] - r["hscore"]), axis=1)
    return {
        "meetings": int(len(meetings)),
        f"{team_a}_wins": int((margin_a > 0).sum()),
        f"{team_b}_wins": int((margin_a < 0).sum()),
        "draws": int((margin_a == 0).sum()),
        f"{team_a}_avg_margin": round(float(margin_a.mean()), 1),
        "last_meeting": meetings.iloc[-1]["date"].date().isoformat(),
    }
