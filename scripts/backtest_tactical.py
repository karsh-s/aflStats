#!/usr/bin/env python3
"""Leak-free backtest of the tactical-analysis signals.

Builds every tactical table from PRE-CUTOFF data only, replays all player-games
on/after the cutoff through the exact live code path (project_from_history +
apply_tactical), and scores bias / MAE / ECE per stat for each signal in
isolation and all together.

Subset scoring matters: these signals fire rarely, so a signal is judged on the
games where it actually fired (drift-flagged games, star-vs-tagger games, real
pillar-absence games, projected blowouts) as well as overall.

Examples:
    python scripts/backtest_tactical.py
    python scripts/backtest_tactical.py --cutoff 2026-05-01 --stats disposals
"""
from __future__ import annotations

import argparse

import _common
from _common import table

import numpy as np
import pandas as pd

from afl import pipeline
from afl.model import (absence, game_script, margin_model, pace_pressure,
                       player_elo, player_props, prop_calibration as pc,
                       role_change, tagging)

STATS_DEFAULT = ["disposals", "marks", "tackles", "goals"]


def _outs_lookup(ps: pd.DataFrame, abs_table) -> dict:
    """{(team, date_norm): set of absent pillars} from actual box scores."""
    out: dict = {}
    if abs_table is None:
        return out
    ps = ps.copy()
    ps["date"] = pd.to_datetime(ps["date"])
    for team in {t for (t, _p) in abs_table._pillars}:
        pillars = abs_table.pillars(team)
        tg = ps[ps["team"] == team]
        for d, grp in tg.groupby(tg["date"].dt.normalize()):
            present = set(grp["player"].astype(str))
            absent = {p for p in pillars if p not in present}
            # Only count absences after the pillar's first appearance.
            absent = {p for p in absent
                      if not tg[tg["player"] == p].empty
                      and tg.loc[tg["player"] == p, "date"].min() < d}
            if absent:
                out[(str(team), d)] = absent
    return out


def _margins_for_tests(ps: pd.DataFrame) -> dict:
    """Predicted home margins for the player-data games (model trained on
    seasons before the player data -> leak-free for 2026 outcomes)."""
    return game_script._predicted_margins_for(ps)


def _score_row(recs_flagged, stat, subset=None):
    if subset:
        recs = [(m, s, a) for m, s, a, f in recs_flagged if f.get(subset)]
    else:
        recs = [(m, s, a) for m, s, a, _f in recs_flagged]
    sc = pc.score(recs, stat)
    sc.pop("reliability", None)
    return sc


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cutoff", default="2026-06-01")
    ap.add_argument("--stats", nargs="+", default=STATS_DEFAULT)
    args = ap.parse_args()
    cutoff = pd.Timestamp(args.cutoff)

    ps = pipeline.load_player_stats_enriched()
    ps["date"] = pd.to_datetime(ps["date"])
    pre = ps[ps["date"] < cutoff]
    n_test = int((ps["date"] >= cutoff).sum())
    print(f"Cutoff {cutoff.date()}: {len(pre)} train rows, {n_test} test rows\n")

    print("Building tactical tables from pre-cutoff data...")
    tables = {
        "pace": pace_pressure.build_table(pre),
        "tagging": tagging.build_table(pre),
        "game_script": game_script.build_table(pre),
        "absence": absence.build_table(pre),
    }
    for k, v in tables.items():
        print(f"  {k:12s} {'OK' if v is not None else 'None'}")
    margins = _margins_for_tests(ps)
    outs = _outs_lookup(ps, tables["absence"])
    print(f"  margins for {len(margins)} games, "
          f"{len(outs)} team-games with a pillar absent\n")

    variants = [
        ("baseline", dict()),
        ("+role", dict(use_role_drift=True)),
        ("+pace", dict(tactical_tables={"pace": tables["pace"]})),
        ("+script", dict(tactical_tables={"game_script": tables["game_script"]},
                         margins=margins)),
        ("+tagging", dict(tactical_tables={"tagging": tables["tagging"]})),
        ("+absence", dict(tactical_tables={"absence": tables["absence"]},
                          outs_lookup=outs)),
        ("all", dict(use_role_drift=True, tactical_tables=tables,
                     margins=margins, outs_lookup=outs)),
    ]
    subset_of = {"+role": "role_flag", "+tagging": "star_flag",
                 "+absence": "absence_flag", "+script": "blowout_flag"}

    for stat in args.stats:
        print(f"\n{'=' * 70}\n{stat.upper()}\n{'=' * 70}")
        elo_model = player_elo.fit(pre, stat)
        recent_n = player_props.RECENT_N_BY_STAT.get(
            stat, player_props.DEFAULT_RECENT_N)
        elo_w = player_props.ELO_WEIGHT_BY_STAT.get(
            stat, player_props.DEFAULT_ELO_WEIGHT)
        split_w = player_props.SPLIT_WEIGHT_BY_STAT.get(
            stat, player_props.DEFAULT_SPLIT_WEIGHT)

        rows = []
        baseline_recs = None
        for name, extra in variants:
            kwargs = dict(cutoff=cutoff, elo_model=elo_model,
                          elo_weight=elo_w, recent_n=recent_n,
                          dispersion_scale=1.0, use_splits=True,
                          split_weight=split_w, use_role_drift=False,
                          collect_flags=True)
            kwargs.update(extra)
            recs = pc.projection_records(ps, stat, **kwargs)
            if name == "baseline":
                baseline_recs = recs
            overall = _score_row(recs, stat)
            row = {"variant": name, **overall}
            sub = subset_of.get(name)
            if sub and baseline_recs is not None and len(recs) == len(baseline_recs):
                # Same record order across variants -> align baseline on the
                # variant's flagged subset for a fair comparison.
                sub_var = [(m, s, a) for m, s, a, f in recs if f.get(sub)]
                sub_base = [b[:3] for b, v in zip(baseline_recs, recs)
                            if v[3].get(sub)]
                sv, sb = pc.score(sub_var, stat), pc.score(sub_base, stat)
                row.update({"sub_n": sv.get("n", 0),
                            "sub_bias": sv.get("bias"),
                            "sub_bias_base": sb.get("bias"),
                            "sub_mae": sv.get("mae"),
                            "sub_mae_base": sb.get("mae")})
            rows.append(row)
        print(table(pd.DataFrame(rows)))


if __name__ == "__main__":
    main()
