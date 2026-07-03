"""Team pace / pressure style effects on player prop projections.

Two team-level indices, computed from box scores over each team's recent
games:

  * pressure — mean tackles laid per game (vs league average). High-pressure
    teams suppress uncontested ball; players who live on uncontested
    possessions suffer most, contested bulls are barely affected.
  * pace — mean opposition disposals conceded per game (vs league average).
    Fast/leaky teams concede more ball to everyone.

The per-player exposure to the pressure effect is their uncontested share
``Σ uncontested / Σ (contested + uncontested)``; when that column is too
sparse (NaN rows in 2026 data) it falls back to a position-group default.

Follows the ``position_adjustment`` module pattern:
``build_table`` / ``get_table`` + cache / ``adj(player, opponent, stat,
player_mean) -> additive delta``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

import numpy as np
import pandas as pd

from .position_adjustment import POSITIONS_CSV

PACE_WINDOW = 10          # last N team-games for the indices
IDX_SHRINK = 5.0          # z *= n/(n+5)
PACE_COEF = 0.02          # frac per 1 sd of opponent pace
PRESS_COEF = 0.08         # frac per (1 sd pressure × exposure offset)
FRAC_CAP = 0.06

# Backtest (cutoff 2026-06-01): disposals MAE 3.719 vs 3.745 and ECE 0.0086
# vs 0.0099 — clear win. Marks' tiny MAE gain didn't cover its ECE slip (even
# at half weight) and tackles showed no MAE gain with worse ECE -> both off.
WEIGHT_BY_STAT: Dict[str, float] = {
    "disposals": 1.0,
    "kicks": 1.0,
    "handballs": 1.0,
    "marks": 0.0,
    "tackles": 0.0,
}
DEFAULT_WEIGHT = 0.0      # goals etc. -> off

UNCONT_DEFAULT_BY_POS: Dict[str, float] = {
    "Midfielder": 0.55,
    "Forward": 0.60,
    "Key Defender": 0.65,
    "Ruck": 0.40,
}
MIN_EXPOSURE_GAMES = 3    # valid contested/uncontested games needed for own rate

USE_PACE = True


@dataclass
class PacePressureTable:
    z_pace: Dict[str, float] = field(default_factory=dict)     # team -> z
    z_press: Dict[str, float] = field(default_factory=dict)    # team -> z
    exposure: Dict[str, float] = field(default_factory=dict)   # player -> uncont share
    league_exposure: float = 0.55
    _positions: Dict[str, str] = field(default_factory=dict)

    def _player_exposure(self, player: str) -> float:
        e = self.exposure.get(player)
        if e is not None:
            return e
        pos = self._positions.get(player)
        return UNCONT_DEFAULT_BY_POS.get(pos, self.league_exposure)

    def adj(self, player: str, opponent: str, stat: str,
            player_mean: float) -> float:
        """Additive projection delta from the opponent's pace/pressure style."""
        weight = WEIGHT_BY_STAT.get(stat, DEFAULT_WEIGHT)
        if weight == 0.0:
            return 0.0
        zp = self.z_pace.get(opponent, 0.0)
        zt = self.z_press.get(opponent, 0.0)
        if stat == "tackles":
            # More ball in play -> more tackle opportunities; pressure style
            # of the opponent doesn't suppress the player's own tackling.
            frac = PACE_COEF * zp
        else:
            e = self._player_exposure(player)
            frac = PACE_COEF * zp - PRESS_COEF * zt * (e - self.league_exposure)
        frac = float(np.clip(frac, -FRAC_CAP, FRAC_CAP))
        return frac * weight * player_mean

    def summary(self, opponent: str) -> dict:
        return {"z_pace": round(self.z_pace.get(opponent, 0.0), 2),
                "z_press": round(self.z_press.get(opponent, 0.0), 2)}


def build_table(player_stats: pd.DataFrame) -> PacePressureTable | None:
    """Build pace/pressure indices from box scores (NaN-tolerant)."""
    needed = {"team", "opponent", "date", "player", "tackles", "disposals"}
    if player_stats.empty or not needed <= set(player_stats.columns):
        return None

    ps = player_stats.copy()
    ps["date"] = pd.to_datetime(ps["date"])

    # Team-game aggregates.
    team_games = (ps.groupby(["team", "date"])
                    .agg(tackles_made=("tackles", "sum"))
                    .reset_index())
    # Disposals conceded BY team T = total disposals of rows whose opponent is T.
    conceded = (ps.groupby(["opponent", "date"])
                  .agg(disposals_conceded=("disposals", "sum"))
                  .reset_index()
                  .rename(columns={"opponent": "team"}))
    team_games = team_games.merge(conceded, on=["team", "date"], how="inner")

    press: Dict[str, float] = {}
    pace: Dict[str, float] = {}
    counts: Dict[str, int] = {}
    for team, grp in team_games.groupby("team"):
        recent = grp.sort_values("date").tail(PACE_WINDOW)
        press[str(team)] = float(recent["tackles_made"].mean())
        pace[str(team)] = float(recent["disposals_conceded"].mean())
        counts[str(team)] = len(recent)

    if len(press) < 4:
        return None

    def zscores(vals: Dict[str, float]) -> Dict[str, float]:
        arr = np.array(list(vals.values()), dtype=float)
        mu, sd = float(arr.mean()), float(arr.std(ddof=0))
        if sd <= 0:
            return {t: 0.0 for t in vals}
        return {t: ((v - mu) / sd) * (counts[t] / (counts[t] + IDX_SHRINK))
                for t, v in vals.items()}

    z_press = zscores(press)
    z_pace = zscores(pace)

    # Player uncontested-ball exposure (skipna; needs MIN_EXPOSURE_GAMES valid).
    exposure: Dict[str, float] = {}
    league_num = league_den = 0.0
    if {"contested_poss", "uncontested_poss"} <= set(ps.columns):
        valid = ps.dropna(subset=["contested_poss", "uncontested_poss"])
        for player, grp in valid.groupby("player"):
            if len(grp) < MIN_EXPOSURE_GAMES:
                continue
            unc = float(grp["uncontested_poss"].sum())
            tot = unc + float(grp["contested_poss"].sum())
            if tot > 0:
                exposure[str(player)] = unc / tot
                league_num += unc
                league_den += tot
    league_exposure = league_num / league_den if league_den > 0 else 0.55

    positions: Dict[str, str] = {}
    if POSITIONS_CSV.exists():
        try:
            pos_df = pd.read_csv(POSITIONS_CSV)
            positions = dict(zip(pos_df["player"], pos_df["position_group"]))
        except Exception:
            pass

    return PacePressureTable(z_pace=z_pace, z_press=z_press, exposure=exposure,
                             league_exposure=league_exposure,
                             _positions=positions)


# ---------------------------------------------------------------------------
# Module-level cache
# ---------------------------------------------------------------------------
_cached_table: PacePressureTable | None = None
_cache_dirty: bool = True


def get_table(player_stats: pd.DataFrame) -> PacePressureTable | None:
    global _cached_table, _cache_dirty
    if _cache_dirty or _cached_table is None:
        _cached_table = build_table(player_stats)
        _cache_dirty = False
    return _cached_table


def invalidate_cache() -> None:
    global _cache_dirty
    _cache_dirty = True
