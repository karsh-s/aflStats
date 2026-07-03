"""Teammate-absence effects with lineup inference from bookmaker markets.

No team sheets are available, but two facts substitute:

  1. History records absences: a team-game with no row for a player IS an
     absence, and the box scores show how their teammates' output shifted.
  2. SportsBet's published player markets reveal who is expected to play:
     a regular starter with no market this week is probably out.

The module learns, per team, the fractional boost to "beneficiary" players
when a pillar (main ruck / top mids) is absent. Because pillars miss only a
handful of games each, team-specific estimates are blended with league-pooled
priors. At prediction time, ``infer_probable_outs`` compares the team's recent
regulars against the players with markets; only PILLAR absences trigger
adjustments (fringe players without markets never fire — the noise guard).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Set, Tuple

import numpy as np
import pandas as pd

PILLAR_MIN_GAMES = 6
RUCK_MIN_HITOUTS = 15.0   # pillar ruck = team's top mean-hitouts player >= this
MID_PILLARS = 3           # top-N mids by mean disposals
PRIOR_N = 8.0             # blend weight of the league-pooled prior
CAP_BY_STAT: Dict[str, float] = {
    "hitouts": 0.20, "marks": 0.10, "disposals": 0.10, "clearances": 0.10,
}
ABS_WEIGHT = 0.6          # single conservative global weight
ROLLING_N = 6
REGULAR_MIN = 4           # played >= 4 of team's last 5 games
MIN_MARKET_PLAYERS = 10   # per-game market coverage needed before inferring outs

RUCK_BENEFIT_STATS = ["hitouts", "marks"]
MID_BENEFIT_STATS = ["disposals", "clearances"]

# Backtest (cutoff 2026-06-01): marginal pass. On real pillar-absence games
# the disposals bias improved slightly (-0.23 vs -0.26) with flat MAE; the
# strongest learned effect (stand-in ruck hitouts +20%) isn't covered by the
# scored stats. Live firing is rare (pillar-gated, needs >=10 market players),
# so kept on.
USE_ABSENCE = True


@dataclass
class AbsenceTable:
    # {(team, pillar): {"role": "ruck"|"mid"}}
    _pillars: Dict[Tuple[str, str], str] = field(default_factory=dict)
    # {(team, pillar, stat): blended fractional boost to beneficiaries}
    _frac: Dict[Tuple[str, str, str], float] = field(default_factory=dict)
    # {team: current stand-in ruck / current mid pillars} for beneficiary checks
    _ruck_standin: Dict[str, str] = field(default_factory=dict)
    _mid_pillars: Dict[str, Set[str]] = field(default_factory=dict)
    _ruck_pillar: Dict[str, str] = field(default_factory=dict)

    def pillars(self, team: str) -> Set[str]:
        return {p for (t, p) in self._pillars if t == team}

    def adj(self, player: str, stat: str, outs: Set[str],
            player_mean: float) -> float:
        """Additive delta when pillar teammates in ``outs`` are missing."""
        if not outs:
            return 0.0
        total_frac = 0.0
        for (team, pillar), role in self._pillars.items():
            if pillar not in outs or pillar == player:
                continue
            if role == "ruck":
                # Beneficiary: the stand-in ruck.
                if player != self._ruck_standin.get(team):
                    continue
                if stat not in RUCK_BENEFIT_STATS:
                    continue
            else:
                # Beneficiary: the team's other current mid pillars.
                if player not in self._mid_pillars.get(team, set()):
                    continue
                if stat not in MID_BENEFIT_STATS:
                    continue
            total_frac += self._frac.get((team, pillar, stat), 0.0)
        if total_frac == 0.0:
            return 0.0
        cap = CAP_BY_STAT.get(stat, 0.10)
        total_frac = float(np.clip(total_frac, -cap, cap))
        return total_frac * ABS_WEIGHT * player_mean

    def summary(self, team: str) -> dict:
        out = {}
        for (t, pillar), role in self._pillars.items():
            if t != team:
                continue
            fr = {s: round(self._frac.get((t, pillar, s), 0.0), 3)
                  for s in (RUCK_BENEFIT_STATS if role == "ruck" else MID_BENEFIT_STATS)}
            out[pillar] = {"role": role, **fr}
        return out


def _team_game_dates(ps: pd.DataFrame, team: str) -> list:
    return sorted(ps.loc[ps["team"] == team, "date"].unique())


def build_table(player_stats: pd.DataFrame) -> AbsenceTable | None:
    """Learn absence-boost fractions from box-score history."""
    needed = {"team", "date", "player", "hitouts", "disposals", "marks", "clearances"}
    if player_stats.empty or not needed <= set(player_stats.columns):
        return None

    ps = player_stats.copy()
    ps["date"] = pd.to_datetime(ps["date"])
    ps = ps.sort_values("date")

    table = AbsenceTable()

    # --- identify pillars per team -----------------------------------------
    for team, tgrp in ps.groupby("team"):
        agg = tgrp.groupby("player").agg(
            games=("date", "nunique"),
            mean_hitouts=("hitouts", "mean"),
            mean_disposals=("disposals", "mean"))
        elig = agg[agg["games"] >= PILLAR_MIN_GAMES]
        if elig.empty:
            continue
        # Ruck pillar: top mean hitouts above the floor (hitouts-based — the
        # positions CSV tags too few rucks to be reliable).
        ruck = elig["mean_hitouts"].idxmax()
        if elig.loc[ruck, "mean_hitouts"] >= RUCK_MIN_HITOUTS:
            table._pillars[(str(team), str(ruck))] = "ruck"
            table._ruck_pillar[str(team)] = str(ruck)
        # Mid pillars: top-N mean disposals.
        for mid in elig.nlargest(MID_PILLARS, "mean_disposals").index:
            if (str(team), str(mid)) not in table._pillars:
                table._pillars[(str(team), str(mid))] = "mid"
        table._mid_pillars[str(team)] = set(
            elig.nlargest(MID_PILLARS, "mean_disposals").index.astype(str))

    if not table._pillars:
        return None

    # Current stand-in ruck: second-best mean hitouts among eligible players.
    for team, tgrp in ps.groupby("team"):
        agg = tgrp.groupby("player").agg(
            games=("date", "nunique"), mean_hitouts=("hitouts", "mean"))
        elig = agg[agg["games"] >= 3].nlargest(2, "mean_hitouts")
        if len(elig) == 2:
            table._ruck_standin[str(team)] = str(elig.index[1])

    # --- per-player pre-game rolling means (leak-free residual baseline) ----
    all_stats = sorted(set(RUCK_BENEFIT_STATS + MID_BENEFIT_STATS))
    grouped = ps.groupby("player", sort=False)
    for stat in all_stats:
        ps[f"roll_{stat}"] = grouped[stat].transform(
            lambda s: s.shift(1).rolling(ROLLING_N, min_periods=3).mean())

    # --- collect absence residuals ------------------------------------------
    # league_pool[(role, stat)] -> list of residuals across all teams
    league_pool: Dict[Tuple[str, str], list] = {}
    team_obs: Dict[Tuple[str, str, str], list] = {}

    for (team, pillar), role in table._pillars.items():
        tp = ps[ps["team"] == team]
        pillar_dates = set(tp.loc[tp["player"] == pillar, "date"])
        if not pillar_dates:
            continue
        first = min(pillar_dates)
        absent_dates = [d for d in _team_game_dates(ps, team)
                        if d >= first and d not in pillar_dates]
        if not absent_dates:
            continue

        for d in absent_dates:
            game = tp[tp["date"] == d]
            if role == "ruck":
                # Stand-in = that game's top-hitouts player for the team.
                if game["hitouts"].isna().all():
                    continue
                standin = game.loc[game["hitouts"].idxmax()]
                bene_rows = [standin]
                stats = RUCK_BENEFIT_STATS
            else:
                bene = table._mid_pillars.get(str(team), set()) - {pillar}
                bene_rows = [r for _, r in game[game["player"].isin(bene)].iterrows()]
                stats = MID_BENEFIT_STATS
            for row in bene_rows:
                for stat in stats:
                    base = row.get(f"roll_{stat}")
                    actual = row.get(stat)
                    if pd.isna(base) or pd.isna(actual) or base < 1.0:
                        continue
                    f = (float(actual) - float(base)) / max(float(base), 2.0)
                    league_pool.setdefault((role, stat), []).append(f)
                    team_obs.setdefault((str(team), str(pillar), stat), []).append(f)

    # --- blend team estimates with league priors ----------------------------
    league_frac = {k: float(np.mean(v)) for k, v in league_pool.items() if v}
    for (team, pillar), role in table._pillars.items():
        stats = RUCK_BENEFIT_STATS if role == "ruck" else MID_BENEFIT_STATS
        for stat in stats:
            obs = team_obs.get((team, pillar, stat), [])
            lg = league_frac.get((role, stat), 0.0)
            n_t = len(obs)
            team_mean = float(np.mean(obs)) if obs else 0.0
            frac = (n_t * team_mean + PRIOR_N * lg) / (n_t + PRIOR_N)
            cap = CAP_BY_STAT.get(stat, 0.10)
            table._frac[(team, pillar, stat)] = float(np.clip(frac, -cap, cap))

    return table


def infer_probable_outs(legs: pd.DataFrame, player_stats: pd.DataFrame,
                        team: str, table: AbsenceTable) -> Set[str]:
    """Infer probable outs for ``team`` from SportsBet's published markets.

    outs = (regulars in >= REGULAR_MIN of the last 5 team games)
           - (players with a resolved market), intersected with pillars.
    Returns an empty set when market coverage is too thin to trust.
    """
    from . import player_props as pp

    if legs is None or len(legs) == 0:
        return set()

    ps = player_stats.copy()
    ps["date"] = pd.to_datetime(ps["date"])

    # Resolve market player names to scraped names.
    index = pp.build_player_index(ps)
    market_players: Set[str] = set()
    leg_players = legs["player"] if "player" in legs else pd.Series(dtype=str)
    for name in pd.Series(leg_players).dropna().unique():
        resolved = pp.resolve_player(str(name), index)
        if resolved is not None:
            market_players.add(resolved)

    if len(market_players) < MIN_MARKET_PLAYERS:
        return set()

    # Regulars: on the team list in >= REGULAR_MIN of the last 5 team games.
    dates = _team_game_dates(ps, team)[-5:]
    if not dates:
        return set()
    tp = ps[(ps["team"] == team) & (ps["date"].isin(dates))]
    counts = tp.groupby("player")["date"].nunique()
    regulars = set(counts[counts >= min(REGULAR_MIN, len(dates))].index.astype(str))

    return (regulars - market_players) & table.pillars(team)


# ---------------------------------------------------------------------------
# Module-level cache
# ---------------------------------------------------------------------------
_cached_table: AbsenceTable | None = None
_cache_dirty: bool = True


def get_table(player_stats: pd.DataFrame) -> AbsenceTable | None:
    global _cached_table, _cache_dirty
    if _cache_dirty or _cached_table is None:
        _cached_table = build_table(player_stats)
        _cache_dirty = False
    return _cached_table


def invalidate_cache() -> None:
    global _cache_dirty
    _cache_dirty = True
