"""Assemble the modelling matrix for match-winner prediction.

Combines, per game:
  * Elo (pre-game ratings, expected home win prob, rating gap incl. HGA)
  * recent form (rolling win%, margins, rest days, season win%)
  * head-to-head history
  * venue / home-ground flag
  * weather (temp, rain, wind) for the match day

The target is ``home_win`` (1 if the home side won). Weather lookups hit a
network API, so they are optional and cached.
"""
from __future__ import annotations

import pandas as pd

from ..data import stadiums, weather
from . import elo as elo_mod
from . import form as form_mod
from . import h2h as h2h_mod

# Columns fed to the classifier. Differences are pre-computed so the model sees
# symmetric, scale-friendly inputs.
FEATURE_COLUMNS = [
    "elo_diff",
    "elo_exp_home",
    "home_ground_adv",
    "form_win_pct_diff",
    "form_margin_diff",
    "rest_days_diff",
    "season_win_pct_diff",
    "h2h_home_win_pct",
    "h2h_home_avg_margin",
    "temp_max",
    "rain_mm",
    "wind_kmh",
]


def _add_weather(games: pd.DataFrame) -> pd.DataFrame:
    cols = {"temp_max": [], "temp_min": [], "rain_mm": [], "wind_kmh": [],
            "roofed": []}
    for _, g in games.iterrows():
        w = weather.weather_for(g.get("venue", ""), g["date"])
        for k in cols:
            cols[k].append(w[k])
    for k, v in cols.items():
        games[k] = v
    return games


def build_matrix(games: pd.DataFrame, *, with_weather: bool = True,
                 form_window: int = 5, h2h_window: int = 10,
                 elo_kwargs: dict | None = None
                 ) -> tuple[pd.DataFrame, elo_mod.TeamElo]:
    """Return (feature_frame, fitted TeamElo).

    ``feature_frame`` contains every input game (completed and not) with all
    feature columns plus ``home_win`` for completed games.
    """
    games = games.sort_values("date").reset_index(drop=True)

    games, elo = elo_mod.run(games, **(elo_kwargs or {}))
    games = form_mod.attach_form(games, window=form_window)
    games = h2h_mod.attach_h2h(games, window=h2h_window)

    if with_weather:
        games = _add_weather(games)
    else:
        for c in ("temp_max", "temp_min", "rain_mm", "wind_kmh"):
            games[c] = [weather.NEUTRAL.get(c, 0.0)] * len(games)

    # Derived symmetric features.
    games["home_ground_adv"] = (games["elo_hga"] > 0).astype(int)
    games["form_win_pct_diff"] = games["home_form_win_pct"].fillna(0.5) - \
        games["away_form_win_pct"].fillna(0.5)
    games["form_margin_diff"] = games["home_form_margin"].fillna(0) - \
        games["away_form_margin"].fillna(0)
    games["rest_days_diff"] = games["home_rest_days"].fillna(7) - \
        games["away_rest_days"].fillna(7)
    games["season_win_pct_diff"] = games["home_season_win_pct"].fillna(0.5) - \
        games["away_season_win_pct"].fillna(0.5)

    games["home_win"] = pd.NA
    done = games["complete"] == 100
    games.loc[done, "home_win"] = (
        games.loc[done, "hscore"] > games.loc[done, "ascore"]).astype(int)

    return games, elo


def feature_row_for_fixture(elo: elo_mod.TeamElo, history: pd.DataFrame,
                            home: str, away: str, venue: str,
                            match_date, *, with_weather: bool = True,
                            form_window: int = 5, h2h_window: int = 10) -> dict:
    """Build a single feature row for an unplayed fixture using current state."""
    hga = elo.hga if stadiums.is_home_ground(home, venue) else 0.0
    r_home, r_away = elo.rating(home), elo.rating(away)

    form = form_mod.team_form_table(history, window=form_window)
    def last_form(team):
        rows = form[form["team"] == team]
        if rows.empty:
            return {"form_win_pct": 0.5, "form_margin": 0.0,
                    "rest_days": 7.0, "season_win_pct": 0.5}
        r = rows.iloc[-1]
        return {"form_win_pct": r["form_win_pct"], "form_margin": r["form_margin"],
                "rest_days": r["rest_days"], "season_win_pct": r["season_win_pct"]}

    hf, af = last_form(home), last_form(away)
    h2h = h2h_mod.summary(history, home, away, last=h2h_window)
    h2h_pct = (h2h.get(f"{home}_wins", 0) / h2h["meetings"]) if h2h.get("meetings") else 0.5
    h2h_margin = h2h.get(f"{home}_avg_margin", 0.0)

    w = weather.weather_for(venue, match_date) if with_weather else weather.NEUTRAL

    return {
        "home": home, "away": away, "venue": venue, "date": match_date,
        "elo_diff": (r_home + hga) - r_away,
        "elo_exp_home": elo_mod.expected_score(r_home + hga, r_away),
        "home_ground_adv": int(hga > 0),
        "form_win_pct_diff": (hf["form_win_pct"] or 0.5) - (af["form_win_pct"] or 0.5),
        "form_margin_diff": (hf["form_margin"] or 0) - (af["form_margin"] or 0),
        "rest_days_diff": (hf["rest_days"] or 7) - (af["rest_days"] or 7),
        "season_win_pct_diff": (hf["season_win_pct"] or 0.5) - (af["season_win_pct"] or 0.5),
        "h2h_home_win_pct": h2h_pct,
        "h2h_home_avg_margin": h2h_margin,
        "temp_max": w["temp_max"], "rain_mm": w["rain_mm"], "wind_kmh": w["wind_kmh"],
    }
