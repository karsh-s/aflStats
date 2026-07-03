"""Per-player, per-stat skill ratings (an Elo-style running rating).

Classic win/loss Elo doesn't fit a continuous output like "disposals", so we
use the same self-correcting update on a continuous target instead:

    rating <- rating + K * (actual - expected)

where ``expected`` is the player's current rating adjusted for the opponent's
defensive strength for that stat and a home/away term. A player who keeps
beating expectation drifts up; the rating therefore tracks both baseline skill
and current form, and naturally accounts for *who* they did it against.

It also accumulates an opponent "defence allowed" factor per stat — how much
more/less of a stat teams concede against a given opponent than league average.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# Stats we rate. These line up with afltables column names.
RATED_STATS = ["disposals", "goals", "marks", "tackles"]

_K = {"disposals": 0.18, "goals": 0.20, "marks": 0.18, "tackles": 0.18}
_HOME_BONUS = {"disposals": 0.3, "goals": 0.05, "marks": 0.1, "tackles": 0.1}


@dataclass
class PlayerEloModel:
    stat: str
    k: float = 0.18
    home_bonus: float = 0.0
    league_mean: float = 0.0
    player_rating: dict[str, float] = field(default_factory=dict)
    player_games: dict[str, int] = field(default_factory=dict)
    # opponent defensive factor: avg (allowed - league_mean) for this stat
    def_allowed: dict[str, float] = field(default_factory=dict)
    _def_count: dict[str, int] = field(default_factory=dict)

    def rating(self, player: str) -> float:
        return self.player_rating.get(player, self.league_mean)

    def expected(self, player: str, opponent: str, is_home: bool) -> float:
        base = self.rating(player)
        opp = self.def_allowed.get(opponent, 0.0)
        home = self.home_bonus if is_home else 0.0
        return max(0.0, base + opp + home)

    def update(self, player: str, opponent: str, is_home: bool,
               actual: float) -> float:
        exp = self.expected(player, opponent, is_home)
        n = self.player_games.get(player, 0)
        # Faster learning for a player's first handful of games.
        k = self.k * (3.0 if n < 5 else 1.0)
        new = self.rating(player) + k * (actual - exp)
        self.player_rating[player] = max(0.0, new)
        self.player_games[player] = n + 1

        # update opponent defensive factor toward (actual - league_mean)
        dc = self._def_count.get(opponent, 0)
        cur = self.def_allowed.get(opponent, 0.0)
        self.def_allowed[opponent] = (cur * dc + (actual - self.league_mean)) / (dc + 1)
        self._def_count[opponent] = dc + 1
        return exp


def fit(player_stats: pd.DataFrame, stat: str) -> PlayerEloModel:
    """Run a single chronological pass to fit the rating for one stat."""
    df = player_stats.dropna(subset=["date"]).sort_values("date")
    model = PlayerEloModel(
        stat=stat,
        k=_K.get(stat, 0.18),
        home_bonus=_HOME_BONUS.get(stat, 0.0),
        league_mean=float(df[stat].mean()) if stat in df else 0.0,
    )
    for _, r in df.iterrows():
        model.update(r["player"], r["opponent"], bool(r["home"]), float(r[stat]))
    return model


def fit_all(player_stats: pd.DataFrame) -> dict[str, PlayerEloModel]:
    return {s: fit(player_stats, s) for s in RATED_STATS if s in player_stats}
