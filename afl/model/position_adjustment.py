"""Position-group concession adjustment for player prop projections.

Teams defend differently against position groups. A ruck going up against
Brisbane (which concedes -1.73 disposals vs the league average to rucks)
should see their projection trimmed; the same ruck against Collingwood
(+3.89) should see it lifted.

This module builds a ``PositionConcessionTable`` from the season's player
stats + the scraped positions CSV, then exposes a single ``adj()`` method
that returns an additive delta (in the same units as the stat) for a given
player vs opponent.

Design:
  * The raw delta is the fractional deviation from the league average for
    that position group: ``(team_avg - league_avg) / league_avg``. Using a
    fraction (not absolute) means the same team effect scales correctly
    across high-volume midfielders (30+ disposals) and low-volume forwards.
  * The fraction is multiplied back into the player's own mean projection
    OUTSIDE this module (by the caller in player_props.project), so the
    returned value here is just the raw fractional effect, capped at ±25%.
  * The effect is shrunk by sample size: ``n_games / (n_games + SHRINK)``.
    With SHRINK=15 you need ~15 player-games against a team before the
    effect carries half weight, which filters out one-game noise.
  * Weights applied by the caller are stat-specific (heavier for disposals
    where the signal is largest, lighter for goals where variance swamps it).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
import pandas as pd

POS_ORDER = ["Key Defender", "Midfielder", "Ruck", "Forward"]
POSITIONS_CSV = Path(__file__).parent.parent.parent / "data" / "raw" / "player_positions.csv"

# Shrinkage: n/(n+SHRINK). With 15, a team needs ~15 player-game samples
# per position before the signal carries half weight.
SHRINK = 15.0

# Cap raw fractional effect before weighting to avoid one outlier team
# (e.g., very few ruck games) dominating projections.
FRAC_CAP = 0.25

# Per-stat weight given to the position concession signal. These sit on top
# of the existing opp/venue splits already in player_props and are calibrated
# to be meaningful without double-counting opponent-specific form.
WEIGHT_BY_STAT: Dict[str, float] = {
    "disposals":  0.40,
    "goals":      0.25,
    "marks":      0.35,
    "tackles":    0.20,
    "clearances": 0.30,
}
DEFAULT_WEIGHT = 0.20


@dataclass
class PositionConcessionTable:
    """Pre-computed fractional position effects per (opponent, position_group, stat)."""

    # {(opponent, position_group): {stat: frac_effect}}
    _table: Dict[Tuple[str, str], Dict[str, float]] = field(default_factory=dict)
    # {player: position_group}
    _positions: Dict[str, str] = field(default_factory=dict)

    def position_of(self, player: str) -> str | None:
        return self._positions.get(player)

    def raw_frac(self, opponent: str, position_group: str, stat: str) -> float:
        """Fractional deviation from league avg (e.g. +0.10 = 10% more than average)."""
        return self._table.get((opponent, position_group), {}).get(stat, 0.0)

    def adj(self, player: str, opponent: str, stat: str,
            player_mean: float) -> float:
        """Additive projection delta for ``player`` vs ``opponent`` on ``stat``.

        Returns the number of extra/fewer units to add to the player's
        projection. Zero if position data is missing for this player.

        ``player_mean`` is the player's base projection (before this call)
        so the fractional effect can be converted to absolute units.
        """
        pos = self._positions.get(player)
        if pos is None:
            return 0.0
        frac = self._table.get((opponent, pos), {}).get(stat, 0.0)
        if frac == 0.0:
            return 0.0
        weight = WEIGHT_BY_STAT.get(stat, DEFAULT_WEIGHT)
        return float(frac * weight * player_mean)

    def summary(self, opponent: str) -> Dict[str, Dict[str, float]]:
        """Human-readable concession fractions for an opponent."""
        out = {}
        for pos in POS_ORDER:
            entry = self._table.get((opponent, pos), {})
            if entry:
                out[pos] = {k: round(v, 3) for k, v in entry.items()}
        return out


def build_table(player_stats: pd.DataFrame) -> PositionConcessionTable | None:
    """Build a PositionConcessionTable from player stats + the positions CSV.

    Returns ``None`` if the positions file hasn't been scraped yet.
    ``player_stats`` should be the full season's data (all games so far).
    """
    if not POSITIONS_CSV.exists():
        return None

    try:
        pos_df = pd.read_csv(POSITIONS_CSV)
    except Exception:
        return None

    pos_map: Dict[str, str] = dict(zip(pos_df["player"], pos_df["position_group"]))

    ps = player_stats.copy()
    ps["position_group"] = ps["player"].map(pos_map)
    ps = ps.dropna(subset=["position_group"])
    if ps.empty:
        return None

    stats_of_interest = [s for s in ["disposals", "goals", "marks", "tackles", "clearances"]
                         if s in ps.columns]

    # League average per position group per stat
    league_avg: Dict[str, Dict[str, float]] = {}
    for pos in POS_ORDER:
        sub = ps[ps["position_group"] == pos]
        league_avg[pos] = {s: float(sub[s].mean()) for s in stats_of_interest
                           if sub[s].count() > 0}

    # Per-(opponent, position_group) aggregate
    table: Dict[Tuple[str, str], Dict[str, float]] = {}
    for (opp, pos), grp in ps.groupby(["opponent", "position_group"]):
        la = league_avg.get(pos, {})
        n = len(grp)
        shrink_factor = n / (n + SHRINK)
        entry: Dict[str, float] = {}
        for s in stats_of_interest:
            la_val = la.get(s, 0.0)
            if la_val <= 0:
                continue
            raw_frac = (float(grp[s].mean()) - la_val) / la_val
            raw_frac = float(np.clip(raw_frac, -FRAC_CAP, FRAC_CAP))
            entry[s] = round(raw_frac * shrink_factor, 4)
        if entry:
            table[(str(opp), str(pos))] = entry

    return PositionConcessionTable(_table=table, _positions=pos_map)


# ---------------------------------------------------------------------------
# Module-level cache — rebuilt once per process (or on explicit refresh)
# ---------------------------------------------------------------------------
_cached_table: PositionConcessionTable | None = None
_cache_dirty: bool = True


def get_table(player_stats: pd.DataFrame) -> PositionConcessionTable | None:
    """Return (and cache) the position concession table for this season's data."""
    global _cached_table, _cache_dirty
    if _cache_dirty or _cached_table is None:
        _cached_table = build_table(player_stats)
        _cache_dirty = False
    return _cached_table


def invalidate_cache() -> None:
    global _cache_dirty
    _cache_dirty = True
