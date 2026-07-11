"""Tactical-analysis context for player-prop projections.

Bundles the tactical adjustment tables (pace/pressure, tagging, game script,
teammate absence) plus the game-level inputs they need (expected margin,
inferred probable outs) into a single ``TacticalContext`` so that
``player_props.project`` gains one kwarg instead of five.

``apply_tactical`` is the single application code path, used by both the live
``project()`` and the calibration backtest, so backtested numbers measure
exactly what runs in production. The sum of all tactical deltas is capped at
``TACTICAL_TOTAL_CAP`` of the projected mean so stacked weak signals cannot
blow up a projection.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# |sum of all tactical deltas| <= this fraction of the projected mean.
TACTICAL_TOTAL_CAP = 0.12


@dataclass
class TacticalContext:
    pace: object | None = None          # pace_pressure.PacePressureTable
    tagging: object | None = None       # tagging.TaggingTable
    game_script: object | None = None   # game_script.GameScriptTable
    absence: object | None = None       # absence.AbsenceTable
    exp_margin: float | None = None     # predicted HOME margin (points)
    home_team: str | None = None
    probable_outs: dict[str, set] = field(default_factory=dict)  # team -> outs


def build_context(player_stats: pd.DataFrame, *, home: str, away: str,
                  legs: pd.DataFrame | None = None,
                  exp_margin: float | None = None) -> TacticalContext:
    """Assemble all enabled tactical tables plus per-game inference.

    Each module's ``USE_*`` flag gates its table; ``legs`` (SportsBet's
    published player markets) enables probable-out inference for both teams.
    """
    from . import pace_pressure, tagging, game_script, absence

    ctx = TacticalContext(exp_margin=exp_margin, home_team=home)

    if pace_pressure.USE_PACE:
        ctx.pace = pace_pressure.get_table(player_stats)
    if tagging.USE_TAGGING:
        ctx.tagging = tagging.get_table(player_stats)
    if game_script.USE_GAME_SCRIPT and exp_margin is not None:
        ctx.game_script = game_script.get_table(player_stats)
    if absence.USE_ABSENCE:
        ctx.absence = absence.get_table(player_stats)
        if ctx.absence is not None and legs is not None:
            for team in (home, away):
                ctx.probable_outs[team] = absence.infer_probable_outs(
                    legs, player_stats, team, ctx.absence)

    return ctx


def apply_tactical(mean: float, comp: dict, *, player: str, stat: str,
                   opponent: str, team: str | None,
                   tactical: TacticalContext | None) -> float:
    """Apply all tactical adjustments to ``mean``, recording each in ``comp``.

    Returns the adjusted mean. Shared by the live projection path and the
    calibration backtest.
    """
    comp["pace_adj"] = comp["tagging_adj"] = 0.0
    comp["game_script"] = comp["absence_adj"] = 0.0
    if tactical is None:
        return mean

    if tactical.pace is not None:
        comp["pace_adj"] = round(tactical.pace.adj(player, opponent, stat, mean), 2)

    if tactical.tagging is not None:
        comp["tagging_adj"] = round(tactical.tagging.adj(player, opponent, stat, mean), 2)

    if (tactical.game_script is not None and tactical.exp_margin is not None
            and team):
        m_team = (tactical.exp_margin if team == tactical.home_team
                  else -tactical.exp_margin)
        comp["game_script"] = round(
            tactical.game_script.adj(player, stat, m_team, mean), 2)

    if tactical.absence is not None and team:
        outs = tactical.probable_outs.get(team, set())
        if outs:
            comp["absence_adj"] = round(
                tactical.absence.adj(player, stat, outs, mean), 2)

    total = (comp["pace_adj"] + comp["tagging_adj"]
             + comp["game_script"] + comp["absence_adj"])
    cap = TACTICAL_TOTAL_CAP * mean
    total = float(np.clip(total, -cap, cap))
    if total:
        comp["projection"] = round(max(0.05, mean + total), 2)
    return max(0.05, mean + total)


def invalidate_all_caches() -> None:
    """Invalidate every tactical module's table cache (call after data refresh)."""
    from . import pace_pressure, tagging, game_script, absence, game_roles
    for mod in (pace_pressure, tagging, game_script, absence, game_roles):
        mod.invalidate_cache()
