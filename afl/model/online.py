"""Online (walk-forward) learning for games and player stats.

The idea the user asked for: freeze the model at a cutoff (Round 5, 2026), then
march through every later game one at a time — predict, see the result, measure
the mistake, and nudge the model so it does better next time. That is exactly
online / sequential learning (the honest name for "RL" in a forecasting setting:
each result is a gradient signal, not a reward for an action).

What actually adapts from its mistakes:

  Game outcome
    * Team Elo ratings   -- the classic error-driven update r += K(actual-exp).
    * Home-ground edge   -- ``hga`` is nudged by SGD on the win-probability error
                            (if home teams keep over/under-performing, it moves).
    * Probability calib. -- an online logistic (Platt) layer a*logit(p)+b keeps
                            the stated probabilities honest as the season evolves.

  Player stats (disposals / goals / tackles)
    * Player Elo ratings -- per-stat skill, updated after each game.
    * Bias correction    -- a per-stat running term that learns any systematic
                            over/under-projection and removes it.

Each learner can run with adaptation on (``online``) or off (``frozen``) so we
can measure how much the learning actually helps.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .. import config
from ..data import stadiums
from ..features.elo import TeamElo, expected_score
from . import player_elo, player_props

PLAYER_STATS = ["disposals", "goals", "tackles"]


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


# ===========================================================================
# Game outcome
# ===========================================================================
@dataclass
class OnlineGameLearner:
    elo: TeamElo
    hga: float = config.ELO_HGA
    a: float = 1.0                 # calibration slope
    b: float = 0.0                 # calibration intercept
    lr_hga: float = 2.0
    lr_cal: float = 0.03
    adapt_ratings: bool = True
    adapt_params: bool = True

    def _elo_prob(self, home: str, away: str, venue: str) -> tuple[float, bool]:
        on_home = stadiums.is_home_ground(home, venue)
        hga = self.hga if on_home else 0.0
        return expected_score(self.elo.rating(home) + hga, self.elo.rating(away)), on_home

    def predict(self, home: str, away: str, venue: str) -> float:
        base, _ = self._elo_prob(home, away, venue)
        return _sigmoid(self.a * _logit(base) + self.b)

    def observe(self, home, away, hscore, ascore, venue, season) -> tuple[float, float]:
        base, on_home = self._elo_prob(home, away, venue)
        p = _sigmoid(self.a * _logit(base) + self.b)
        y = 1.0 if hscore > ascore else (0.0 if hscore < ascore else 0.5)

        if self.adapt_params:
            # Online logistic calibration (gradient of log-loss).
            z, e = _logit(base), (p - y)
            self.a -= self.lr_cal * e * z
            self.b -= self.lr_cal * e
            # Home-ground edge: nudge by the win-probability error (in Elo
            # points). dLoss/dhga is proportional to (p - y), so step toward
            # (y - base); kept in a sane range.
            if on_home:
                self.hga = float(np.clip(self.hga + self.lr_hga * (y - base), 0, 90))
        if self.adapt_ratings:
            self.elo.update_one(home, away, hscore, ascore, venue=venue, season=season)
        return p, y


# ===========================================================================
# Player stats
# ===========================================================================
@dataclass
class OnlinePlayerLearner:
    elos: dict
    bias: dict = field(default_factory=lambda: {s: 0.0 for s in PLAYER_STATS})
    lr_bias: float = 0.03
    adapt: bool = True

    def predict(self, prior: pd.DataFrame, player: str, stat: str, opponent: str,
                venue_norm: str | None, is_home: bool, forecast: dict | None) -> float:
        elo = self.elos.get(stat)
        elo_exp = elo.expected(player, opponent, is_home) if elo is not None else None
        mean, _, _, _ = player_props.project_from_history(
            prior, stat, opponent=opponent, venue_norm=venue_norm, is_home=is_home,
            forecast=forecast, elo_exp=elo_exp,
            recent_n=player_props.RECENT_N_BY_STAT.get(stat, player_props.DEFAULT_RECENT_N),
            elo_weight=player_props.ELO_WEIGHT_BY_STAT.get(stat, player_props.DEFAULT_ELO_WEIGHT),
            dispersion_scale=player_props.DEFAULT_DISPERSION_SCALE,
            decay=player_props.DECAY_BY_STAT.get(stat, player_props.DEFAULT_DECAY))
        return max(0.0, mean + self.bias[stat])

    def observe(self, player, stat, predicted, actual, opponent, is_home) -> None:
        if not self.adapt:
            return
        # Learn any systematic over/under-projection (running residual).
        self.bias[stat] += self.lr_bias * (actual - predicted)
        elo = self.elos.get(stat)
        if elo is not None:
            elo.update(player, opponent, is_home, float(actual))
