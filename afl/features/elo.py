"""Team Elo ratings for AFL.

A single pass over completed games, chronologically, produces:
  * the pre-game Elo of each side for every match (leak-free features), and
  * the live current ratings (used to predict future fixtures).

Refinements over textbook Elo, all standard for AFL modelling:
  * Home-ground advantage added to the home side's effective rating (skipped
    when the "home" team is actually playing away from its real home ground).
  * Margin-of-victory multiplier so blowouts move ratings more than nail-biters,
    dampened by the rating gap to avoid autocorrelation.
  * Between-season regression toward the league mean (carry-over of form).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from .. import config
from ..data import stadiums


def expected_score(rating_a: float, rating_b: float) -> float:
    """Probability A beats B given Elo ratings."""
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def _mov_multiplier(margin: float, elo_diff: float) -> float:
    """Margin-of-victory multiplier (FiveThirtyEight-style)."""
    margin = abs(margin)
    return math.log(margin + 1.0) * (2.2 / (elo_diff * 0.001 + 2.2))


@dataclass
class TeamElo:
    k: float = config.ELO_K
    hga: float = config.ELO_HGA
    mean: float = config.ELO_MEAN
    regress: float = config.ELO_REGRESS
    use_mov: bool = config.ELO_MOV
    ratings: dict[str, float] = field(default_factory=dict)
    _last_season: int | None = None

    def rating(self, team: str) -> float:
        return self.ratings.get(team, self.mean)

    def _new_season(self, season: int) -> None:
        if self._last_season is not None and season != self._last_season:
            for t in list(self.ratings):
                self.ratings[t] = (
                    self.mean * self.regress + self.ratings[t] * (1 - self.regress)
                )
        self._last_season = season

    def win_probability(self, home: str, away: str, venue: str = "") -> float:
        """Pre-game home win probability incl. home-ground advantage."""
        hga = self.hga if stadiums.is_home_ground(home, venue) else 0.0
        return expected_score(self.rating(home) + hga, self.rating(away))

    def update_one(self, home: str, away: str, hscore: float, ascore: float,
                   venue: str = "", season: int | None = None) -> dict:
        """Apply a single result, returning the pre-game feature snapshot."""
        if season is not None:
            self._new_season(season)

        r_home, r_away = self.rating(home), self.rating(away)
        hga = self.hga if stadiums.is_home_ground(home, venue) else 0.0
        exp_home = expected_score(r_home + hga, r_away)

        margin = hscore - ascore
        if margin > 0:
            result = 1.0
        elif margin < 0:
            result = 0.0
        else:
            result = 0.5

        mult = (
            _mov_multiplier(margin, (r_home + hga) - r_away)
            if self.use_mov else 1.0
        )
        change = self.k * mult * (result - exp_home)
        self.ratings[home] = r_home + change
        self.ratings[away] = r_away - change

        return {
            "home_elo_pre": r_home,
            "away_elo_pre": r_away,
            "elo_hga": hga,
            "elo_exp_home": exp_home,
            "elo_diff": (r_home + hga) - r_away,
        }


def run(games: pd.DataFrame, **kwargs) -> tuple[pd.DataFrame, TeamElo]:
    """Process completed games chronologically.

    Returns (features_df aligned to the input rows, fitted TeamElo). Rows that
    are not yet complete receive pre-game ratings but do not update the model.
    """
    elo = TeamElo(**kwargs)
    games = games.sort_values("date").reset_index(drop=True)
    records = []
    for _, g in games.iterrows():
        complete = g.get("complete", 0) == 100 and pd.notna(g.get("hscore"))
        if complete:
            snap = elo.update_one(
                g["hteam"], g["ateam"], g["hscore"], g["ascore"],
                venue=g.get("venue", ""), season=int(g.get("year", 0)) or None,
            )
        else:
            elo._new_season(int(g.get("year", 0)) or 0)
            hga = elo.hga if stadiums.is_home_ground(g["hteam"], g.get("venue", "")) else 0.0
            snap = {
                "home_elo_pre": elo.rating(g["hteam"]),
                "away_elo_pre": elo.rating(g["ateam"]),
                "elo_hga": hga,
                "elo_exp_home": elo.win_probability(g["hteam"], g["ateam"], g.get("venue", "")),
                "elo_diff": elo.rating(g["hteam"]) + hga - elo.rating(g["ateam"]),
            }
        records.append(snap)
    feats = pd.DataFrame(records, index=games.index)
    return pd.concat([games, feats], axis=1), elo
