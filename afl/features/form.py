"""Recent-form and contextual features derived purely from past results.

Everything here is strictly backward-looking (computed from games that kicked
off before the current match) so there is no target leakage.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _long_results(games: pd.DataFrame) -> pd.DataFrame:
    """Explode each game into two team-centric rows (one per side)."""
    completed = games[games.get("complete", 0) == 100].copy()
    home = pd.DataFrame({
        "game_id": completed["id"],
        "date": completed["date"],
        "season": completed["year"],
        "team": completed["hteam"],
        "opponent": completed["ateam"],
        "score": completed["hscore"],
        "against": completed["ascore"],
        "is_home": True,
    })
    away = pd.DataFrame({
        "game_id": completed["id"],
        "date": completed["date"],
        "season": completed["year"],
        "team": completed["ateam"],
        "opponent": completed["hteam"],
        "score": completed["ascore"],
        "against": completed["hscore"],
        "is_home": False,
    })
    long = pd.concat([home, away], ignore_index=True)
    long["margin"] = long["score"] - long["against"]
    long["win"] = (long["margin"] > 0).astype(float)
    long.loc[long["margin"] == 0, "win"] = 0.5
    return long.sort_values("date").reset_index(drop=True)


def team_form_table(games: pd.DataFrame, window: int = 5) -> pd.DataFrame:
    """Per-team, per-game rolling form *as known before each game*.

    Returns columns keyed by game_id+team that ``build`` joins back on.
    """
    long = _long_results(games)
    g = long.groupby("team", group_keys=False)

    def roll(series):
        return series.shift(1).rolling(window, min_periods=1).mean()

    long["form_win_pct"] = g["win"].apply(roll)
    long["form_margin"] = g["margin"].apply(roll)
    long["form_score_for"] = g["score"].apply(roll)
    long["form_score_against"] = g["against"].apply(roll)

    # Days of rest since previous match and a season-long win rate to date.
    long["prev_date"] = g["date"].shift(1)
    long["rest_days"] = (long["date"] - long["prev_date"]).dt.days
    long["rest_days"] = long["rest_days"].clip(upper=30).fillna(7)

    long["season_win_pct"] = (
        long.groupby(["team", "season"])["win"]
        .apply(lambda s: s.shift(1).expanding().mean())
        .reset_index(level=[0, 1], drop=True)
    )

    keep = ["game_id", "team", "is_home", "form_win_pct", "form_margin",
            "form_score_for", "form_score_against", "rest_days", "season_win_pct"]
    return long[keep]


def attach_form(games: pd.DataFrame, window: int = 5) -> pd.DataFrame:
    """Attach home_* and away_* form columns to each game row."""
    form = team_form_table(games, window=window)
    home = form[form["is_home"]].add_prefix("home_").rename(
        columns={"home_game_id": "id"})
    away = form[~form["is_home"]].add_prefix("away_").rename(
        columns={"away_game_id": "id"})
    out = games.merge(home.drop(columns=["home_is_home"]), on="id", how="left")
    out = out.merge(away.drop(columns=["away_is_home"]), on="id", how="left")
    return out
