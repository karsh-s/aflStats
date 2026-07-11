"""Per-game role classification from box-score signatures.

The positions CSV says what a player nominally is; the box score says where
they actually played THAT NIGHT. A midfielder thrown forward leaves a
fingerprint — goals and marks-inside-50 instead of clearances; a mid moved to
half-back racks up rebound-50s. This module classifies every player-game into
one of five on-field roles using only stats present in the data:

  Ruck        — hitouts dominate
  Forward     — goals + marks inside 50 + goal assists
  Defender    — rebound 50s + one-percenters (spoils)
  Inside Mid  — clearances + contested possession share
  Outside Mid — everything else (uncontested accumulation, wings/half-back
                distributors without a strong defensive or forward signature)

Each non-ruck signature is scaled by a league z-ish normaliser so the argmax
is comparable across stats. Rows missing the signature columns (a handful of
manually-inserted games) fall back to the static positions CSV.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

import numpy as np
import pandas as pd

from .position_adjustment import POSITIONS_CSV

ROLES = ["Ruck", "Forward", "Defender", "Inside Mid", "Outside Mid"]

RUCK_HITOUTS_MIN = 8.0        # a game with 8+ hitouts is a ruck game
# Mix-based signature thresholds (fraction of the player's involvement, so the
# classification reflects STYLE not volume — a 12-disposal defender and a
# 28-disposal defender both classify as Defender). Grid-tuned on 2026 data
# against the static positions CSV (68% agreement; the disagreements are
# largely genuine role changes, which is what this module exists to catch).
FWD_THRESH = 0.12             # (goals + 0.7*mi50 + 0.5*assists) per disposal
DEF_THRESH = 0.15             # (rebounds + 0.5*one_percenters) per disposal
MID_THRESH = 0.12             # clearances per disposal + contested-share bonus

# Static CSV fallback group -> role
_CSV_TO_ROLE = {"Ruck": "Ruck", "Forward": "Forward",
                "Key Defender": "Defender", "Midfielder": "Inside Mid"}

_SIG_COLS = ["hitouts", "goals", "marks_inside50", "goal_assists",
             "rebounds", "one_percenters", "clearances",
             "contested_poss", "uncontested_poss"]


def classify_games(player_stats: pd.DataFrame) -> pd.DataFrame:
    """Return player_stats plus a ``game_role`` column (one role per row)."""
    ps = player_stats.copy()
    ps["date"] = pd.to_datetime(ps["date"])

    csv_map: Dict[str, str] = {}
    if POSITIONS_CSV.exists():
        try:
            pos_df = pd.read_csv(POSITIONS_CSV)
            csv_map = dict(zip(pos_df["player"], pos_df["position_group"]))
        except Exception:
            pass

    have = [c for c in _SIG_COLS if c in ps.columns]

    def _row_role(r) -> str:
        vals = {c: r.get(c) for c in have}
        if any(pd.isna(v) for v in vals.values()):
            grp = csv_map.get(r["player"])
            return _CSV_TO_ROLE.get(grp, "Outside Mid")
        if vals["hitouts"] >= RUCK_HITOUTS_MIN:
            return "Ruck"
        d1 = float(r.get("disposals", 0)) + 1.0
        fwd = (vals["goals"] + 0.7 * vals["marks_inside50"]
               + 0.5 * vals["goal_assists"]) / d1 / FWD_THRESH
        dfn = (vals["rebounds"] + 0.5 * vals["one_percenters"]) / d1 / DEF_THRESH
        cont = vals["contested_poss"]
        tot = cont + vals["uncontested_poss"]
        cont_share = cont / tot if tot > 0 else 0.5
        mid = (vals["clearances"] / d1
               + 0.3 * max(0.0, cont_share - 0.45)) / MID_THRESH
        best = max(fwd, dfn, mid)
        if best < 1.0:
            return "Outside Mid"
        if fwd == best:
            return "Forward"
        if dfn == best:
            return "Defender"
        return "Inside Mid"

    ps["game_role"] = ps.apply(_row_role, axis=1)
    return ps


@dataclass
class RoleTable:
    """Per-game roles + per-player per-role disposal baselines."""
    games: pd.DataFrame = field(default_factory=pd.DataFrame)  # with game_role
    # {(player, role): (mean_disposals, n_games)}
    role_disposals: Dict[tuple, tuple] = field(default_factory=dict)
    # {player: modal role over their season}
    main_role: Dict[str, str] = field(default_factory=dict)
    # {player: modal role over their last CURRENT_N games}
    current_role: Dict[str, str] = field(default_factory=dict)

    def role_mean(self, player: str, role: str):
        return self.role_disposals.get((player, role))


CURRENT_N = 3   # games defining a player's "current" role


def build_table(player_stats: pd.DataFrame) -> RoleTable | None:
    if player_stats.empty:
        return None
    games = classify_games(player_stats).sort_values("date")

    role_disp: Dict[tuple, tuple] = {}
    main: Dict[str, str] = {}
    current: Dict[str, str] = {}
    for player, g in games.groupby("player"):
        counts = g["game_role"].value_counts()
        main[str(player)] = str(counts.index[0])
        cur = g.tail(CURRENT_N)["game_role"].value_counts()
        current[str(player)] = str(cur.index[0])
        for role, grp in g.groupby("game_role"):
            role_disp[(str(player), str(role))] = (
                float(grp["disposals"].mean()), int(len(grp)))

    return RoleTable(games=games, role_disposals=role_disp,
                     main_role=main, current_role=current)


# ---------------------------------------------------------------------------
# Role-form projection adjustment
# ---------------------------------------------------------------------------
# When a player's CURRENT role (modal over their last CURRENT_N games) differs
# from the role they played across most of the form window, the standard
# recency projection averages over two different jobs. This blends the
# projection toward the player's own historical output in the CURRENT role.
# Backtest (cutoff 2026-06-01, 136 fired games): w=0.20 captures most of the
# subset MAE gain (3.99 -> 3.96) with the least bias cost; heavier weights
# over-penalise players in new roles (they outperform their role history).
ROLE_FORM_WEIGHT = 0.20   # how far to pull toward the current-role mean

# Role instability: taggers / utility players whose on-field role changes
# week to week (no modal role dominates). Their output depends on the
# assignment, so recency decay overreacts to their spiky games — backtest
# (cutoff 2026-06-01, 420 unstable player-games) shows a FLAT form window
# beats decay for them: MAE 3.826 vs 3.856, ECE 0.0135 vs 0.0140. SD widening
# was tested and made ECE worse; the problem is mean placement, not spread.
ROLE_INSTABILITY_THRESH = 0.35   # 1 - modal-role share; >= this = unstable
USE_ROLE_INSTABILITY = True


def role_instability(prior: pd.DataFrame) -> float:
    """1 - modal role share over the player's prior games (0 = one job)."""
    if "game_role" not in prior.columns or len(prior) < 8:
        return 0.0
    return float(1.0 - prior["game_role"].value_counts(normalize=True).iloc[0])
ROLE_FORM_MIN_N = 3       # prior games needed in the current role
ROLE_FORM_CAP = 4.0       # max absolute delta (disposals-scale units)
ROLE_FORM_STATS = {"disposals"}
USE_ROLE_FORM = True


def role_form_delta(prior: pd.DataFrame, stat: str, mean: float) -> float:
    """Additive delta pulling the projection toward the current-role mean.

    ``prior`` must carry a ``game_role`` column (from ``classify_games``),
    chronologically ordered. Returns 0 when the player hasn't changed role,
    lacks history in the new role, or the stat isn't role-sensitive.
    """
    if stat not in ROLE_FORM_STATS or "game_role" not in prior.columns:
        return 0.0
    roles = prior["game_role"].astype(str)
    if len(roles) < CURRENT_N + ROLE_FORM_MIN_N:
        return 0.0
    cur_role = roles.tail(CURRENT_N).mode().iloc[0]
    window_role = roles.tail(10).mode().iloc[0]
    if cur_role == window_role:
        return 0.0
    in_role = prior[roles == cur_role]
    if len(in_role) < ROLE_FORM_MIN_N:
        return 0.0
    role_mean = float(in_role[stat].mean())
    delta = ROLE_FORM_WEIGHT * (role_mean - mean)
    return float(np.clip(delta, -ROLE_FORM_CAP, ROLE_FORM_CAP))


# ---------------------------------------------------------------------------
# Module-level cache
# ---------------------------------------------------------------------------
_cached_table: RoleTable | None = None
_cache_dirty: bool = True


def get_table(player_stats: pd.DataFrame) -> RoleTable | None:
    global _cached_table, _cache_dirty
    if _cache_dirty or _cached_table is None:
        _cached_table = build_table(player_stats)
        _cache_dirty = False
    return _cached_table


def invalidate_cache() -> None:
    global _cache_dirty
    _cache_dirty = True
