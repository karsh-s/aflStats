"""Game-script adjustment: how expected blowouts move player stats.

Learned from history: for each (position_group, stat, expected-margin bucket),
the mean fractional residual of a player's actual output vs their pre-game
rolling baseline. Margins for historical games come from a ``MarginModel``
trained only on seasons BEFORE the player data (leak-free); the middle bucket
(close games) is the zero reference.

At prediction time ``adj()`` buckets the fixture's team-relative expected
margin and returns the learned positional effect. Heavily shrunk and capped —
game-script is a real but weak signal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple

import numpy as np
import pandas as pd

from .position_adjustment import POSITIONS_CSV

# Team-relative expected margin buckets. Middle bucket is the reference (0).
BUCKETS: list[tuple[float, float]] = [
    (-999.0, -24.0), (-24.0, -12.0), (-12.0, 12.0), (12.0, 24.0), (24.0, 999.0),
]
GS_SHRINK = 40.0
FRAC_CAP = 0.08
# Backtest (cutoff 2026-06-01): disposals |bias| 0.019 vs 0.058 and ECE 0.008
# vs 0.0099, blowout-subset bias 0.05 vs 0.19 — the strongest signal of the
# five. Tackles improved overall bias/ECE too. Marks worsened bias and goals
# were flat-to-worse -> both off.
GS_WEIGHT_BY_STAT: Dict[str, float] = {
    "disposals": 0.5, "marks": 0.0, "tackles": 0.5, "goals": 0.0,
}
STATS = ["disposals", "marks", "tackles", "goals"]
ROLLING_N = 6
MIN_PRIOR = 5

USE_GAME_SCRIPT = True


def _bucket(margin: float) -> int:
    for i, (lo, hi) in enumerate(BUCKETS):
        if lo <= margin < hi:
            return i
    return len(BUCKETS) // 2


@dataclass
class GameScriptTable:
    # {(position_group, stat, bucket_idx): frac}
    _table: Dict[Tuple[str, str, int], float] = field(default_factory=dict)
    _positions: Dict[str, str] = field(default_factory=dict)

    def adj(self, player: str, stat: str, exp_margin_team: float,
            player_mean: float) -> float:
        """Additive delta from the expected game script (team-relative margin)."""
        weight = GS_WEIGHT_BY_STAT.get(stat, 0.0)
        if weight == 0.0:
            return 0.0
        pos = self._positions.get(player)
        if pos is None:
            return 0.0
        frac = self._table.get((pos, stat, _bucket(exp_margin_team)), 0.0)
        return frac * weight * player_mean

    def summary(self) -> dict:
        out: dict = {}
        for (pos, stat, b), frac in sorted(self._table.items()):
            out.setdefault(f"{pos}/{stat}", {})[f"bucket{b}"] = round(frac, 4)
        return out


def build_table(player_stats: pd.DataFrame,
                margins: Dict[tuple, float] | None = None
                ) -> GameScriptTable | None:
    """Build the game-script table.

    ``margins`` maps ``(normalized_date, hteam, ateam) -> predicted home
    margin`` for the games in ``player_stats``. When None, it is computed
    here from a MarginModel trained on seasons before the player data.
    """
    if player_stats.empty or not POSITIONS_CSV.exists():
        return None
    try:
        pos_df = pd.read_csv(POSITIONS_CSV)
    except Exception:
        return None
    pos_map: Dict[str, str] = dict(zip(pos_df["player"], pos_df["position_group"]))

    if margins is None:
        margins = _predicted_margins_for(player_stats)
    if not margins:
        return None

    ps = player_stats.copy()
    ps["date"] = pd.to_datetime(ps["date"])
    ps["position_group"] = ps["player"].map(pos_map)
    ps = ps.dropna(subset=["position_group"]).sort_values("date")

    # Fractional residual vs pre-game rolling mean, bucketed by the
    # team-relative predicted margin of that game.
    rows = []
    for (player, pos), grp in ps.groupby(["player", "position_group"]):
        for stat in STATS:
            if stat not in grp.columns:
                continue
            vals = grp[stat].to_numpy(dtype=float)
            if len(vals) <= MIN_PRIOR:
                continue
            for i in range(MIN_PRIOR, len(vals)):
                if np.isnan(vals[i]):
                    continue
                window = vals[max(0, i - ROLLING_N):i]
                window = window[~np.isnan(window)]
                if len(window) < MIN_PRIOR:
                    continue
                baseline = float(window.mean())
                row = grp.iloc[i]
                key_h = (row["date"].normalize(), str(row["team"]), str(row["opponent"]))
                key_a = (row["date"].normalize(), str(row["opponent"]), str(row["team"]))
                if key_h in margins:          # player's team is home
                    m_team = margins[key_h]
                elif key_a in margins:        # player's team is away
                    m_team = -margins[key_a]
                else:
                    continue
                f = (vals[i] - baseline) / max(baseline, 2.0)
                rows.append((pos, stat, _bucket(m_team), f))

    if not rows:
        return None

    df = pd.DataFrame(rows, columns=["pos", "stat", "bucket", "f"])
    mid = len(BUCKETS) // 2
    table: Dict[Tuple[str, str, int], float] = {}
    for (pos, stat, b), grp in df.groupby(["pos", "stat", "bucket"]):
        if b == mid:
            continue  # reference bucket stays 0
        n = len(grp)
        frac = float(grp["f"].mean()) * (n / (n + GS_SHRINK))
        table[(str(pos), str(stat), int(b))] = float(np.clip(frac, -FRAC_CAP, FRAC_CAP))

    return GameScriptTable(_table=table, _positions=pos_map)


def _predicted_margins_for(player_stats: pd.DataFrame) -> Dict[tuple, float]:
    """Leak-free predicted margins for the games in the player data.

    Trains a MarginModel on feature rows from seasons strictly before the
    earliest player-stats season, then predicts every game in the player-data
    seasons.
    """
    from . import margin_model as mm
    try:
        from .. import pipeline
        feat = pipeline.load_features()
    except Exception:
        return {}
    if feat is None or feat.empty:
        return {}

    ps_years = pd.to_datetime(player_stats["date"]).dt.year.unique()
    first_year = int(min(ps_years))
    train_feat = feat[feat["year"] < first_year]
    target_feat = feat[feat["year"].isin(ps_years)].copy()
    if len(train_feat) < 400 or target_feat.empty:
        return {}

    model = mm.train(train_feat)
    preds = model.predict(target_feat)
    target_feat["date"] = pd.to_datetime(target_feat["date"])
    return {
        (d.normalize(), str(h), str(a)): float(p)
        for d, h, a, p in zip(target_feat["date"], target_feat["hteam"],
                              target_feat["ateam"], preds)
    }


# ---------------------------------------------------------------------------
# Module-level cache
# ---------------------------------------------------------------------------
_cached_table: GameScriptTable | None = None
_cache_dirty: bool = True


def get_table(player_stats: pd.DataFrame) -> GameScriptTable | None:
    global _cached_table, _cache_dirty
    if _cache_dirty or _cached_table is None:
        _cached_table = build_table(player_stats)
        _cache_dirty = False
    return _cached_table


def invalidate_cache() -> None:
    global _cache_dirty
    _cache_dirty = True
