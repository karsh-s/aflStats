"""Tagging / star-suppression detection from box-score history.

Some teams deploy run-with taggers against the opposition's best midfielders.
That never appears in any feed — but it leaves a statistical fingerprint: the
opposing TOP midfielders underperform their form against that team by more
than ordinary midfielders do.

For each defending team, per stat:

  suppression = wmean(star residuals) - wmean(all-mid residuals)

where a residual is ``(actual - pregame rolling mean) / max(rolling mean, 2)``
and "stars" are the top TOP_K opposing mids by pre-game form (leak-free by
construction). Differencing against ALL opposing mids subtracts what the
existing position-concession and per-player opponent splits already capture —
only the star-specific excess (the tag) survives.

``adj()`` only fires for players who are currently one of their own team's
top TOP_K form midfielders.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Set, Tuple

import numpy as np
import pandas as pd

from .position_adjustment import POSITIONS_CSV

TOP_K = 3           # "stars" = top-K opposing mids by recent form
FORM_N = 6          # window for both star ranking and the residual baseline
MIN_PRIOR = 4       # prior games needed before a player can be ranked
SHRINK = 20.0       # n_star/(n_star+20); full season gives n_star ~ 45
FRAC_CAP = 0.12
TAG_WEIGHT_BY_STAT: Dict[str, float] = {
    "disposals": 0.5, "clearances": 0.5, "marks": 0.3,
}
STATS = ["disposals", "clearances", "marks"]

# Backtest (cutoff 2026-06-01): FAILED the shipping gate. Pre-cutoff star
# suppression did not generalise — on star-vs-tagger games post-cutoff the
# adjustment made disposals bias WORSE (+0.50 vs +0.38 baseline). One season
# of data is not enough to separate a real tag from noise. Off by default;
# re-test when multi-season player data is available.
USE_TAGGING = False


@dataclass
class TaggingTable:
    # {(defending_team, stat): suppression frac (negative = suppresses stars)}
    _table: Dict[Tuple[str, str], float] = field(default_factory=dict)
    # current top-K form mids per team
    _stars: Dict[str, Set[str]] = field(default_factory=dict)

    def is_star(self, player: str, team: str | None = None) -> bool:
        if team is not None:
            return player in self._stars.get(team, set())
        return any(player in s for s in self._stars.values())

    def adj(self, player: str, opponent: str, stat: str,
            player_mean: float) -> float:
        """Additive delta: star-suppression effect of ``opponent`` on ``player``.

        Zero unless the player is currently one of their team's top form mids.
        """
        weight = TAG_WEIGHT_BY_STAT.get(stat, 0.0)
        if weight == 0.0 or not self.is_star(player):
            return 0.0
        frac = self._table.get((opponent, stat), 0.0)
        return frac * weight * player_mean

    def summary(self, opponent: str) -> dict:
        return {stat: round(self._table.get((opponent, stat), 0.0), 4)
                for stat in STATS}


def build_table(player_stats: pd.DataFrame) -> TaggingTable | None:
    """Build per-team star-suppression fractions (leak-free star ranking)."""
    if player_stats.empty or not POSITIONS_CSV.exists():
        return None
    try:
        pos_df = pd.read_csv(POSITIONS_CSV)
    except Exception:
        return None
    mids = set(pos_df.loc[pos_df["position_group"] == "Midfielder", "player"])

    ps = player_stats[player_stats["player"].isin(mids)].copy()
    if ps.empty:
        return None
    ps["date"] = pd.to_datetime(ps["date"])
    ps = ps.sort_values("date")

    # Pre-game rolling mean per player per stat (shifted -> leak-free).
    for stat in STATS + ["disposals"]:
        if stat not in ps.columns:
            return None
    grouped = ps.groupby("player", sort=False)
    ps["form_disposals"] = grouped["disposals"].transform(
        lambda s: s.shift(1).rolling(FORM_N, min_periods=MIN_PRIOR).mean())
    for stat in STATS:
        ps[f"roll_{stat}"] = grouped[stat].transform(
            lambda s: s.shift(1).rolling(FORM_N, min_periods=MIN_PRIOR).mean())

    ps = ps.dropna(subset=["form_disposals"]).copy()
    if ps.empty:
        return None

    # Rank opposing mids within each (defending team, game date): stars = top-K
    # by pre-game disposal form.
    ps["star_rank"] = (ps.groupby(["opponent", "date"])["form_disposals"]
                         .rank(method="first", ascending=False))
    ps["is_star"] = ps["star_rank"] <= TOP_K

    # Residuals per stat, then per-defending-team difference star vs all-mid.
    table: Dict[Tuple[str, str], float] = {}
    span = (ps["date"].max() - ps["date"].min()).days or 1
    ps["_recency_w"] = 0.6 + 0.4 * (ps["date"] - ps["date"].min()).dt.days / span

    for stat in STATS:
        roll = ps[f"roll_{stat}"]
        valid = ps[roll.notna() & ps[stat].notna()].copy()
        if valid.empty:
            continue
        valid["_f"] = ((valid[stat] - valid[f"roll_{stat}"])
                       / valid[f"roll_{stat}"].clip(lower=2.0))
        for team, grp in valid.groupby("opponent"):
            stars = grp[grp["is_star"]]
            if len(stars) < 5:
                continue
            w_star = stars["_recency_w"].to_numpy()
            w_all = grp["_recency_w"].to_numpy()
            f_star = float(np.average(stars["_f"], weights=w_star))
            f_all = float(np.average(grp["_f"], weights=w_all))
            n_star = len(stars)
            sup = (f_star - f_all) * (n_star / (n_star + SHRINK))
            table[(str(team), stat)] = float(np.clip(sup, -FRAC_CAP, FRAC_CAP))

    # Current stars: per team, top-K mids by disposal form over the team's
    # most recent appearance of each player.
    stars_now: Dict[str, Set[str]] = {}
    latest = ps.loc[ps.groupby("player")["date"].idxmax()]
    for team, grp in latest.groupby("team"):
        top = grp.nlargest(TOP_K, "form_disposals")
        stars_now[str(team)] = set(top["player"])

    return TaggingTable(_table=table, _stars=stars_now)


# ---------------------------------------------------------------------------
# Module-level cache
# ---------------------------------------------------------------------------
_cached_table: TaggingTable | None = None
_cache_dirty: bool = True


def get_table(player_stats: pd.DataFrame) -> TaggingTable | None:
    global _cached_table, _cache_dirty
    if _cache_dirty or _cached_table is None:
        _cached_table = build_table(player_stats)
        _cache_dirty = False
    return _cached_table


def invalidate_cache() -> None:
    global _cache_dirty
    _cache_dirty = True
