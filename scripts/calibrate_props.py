#!/usr/bin/env python3
"""Backtest and calibrate the player-prop projection knobs.

Fits Elo only on pre-cutoff games, projects each player-game in the test window
from that player's prior games only (leak-free), and scores the result:

    bias  = mean(actual - projection)   (~0 is good; negative => projects low)
    MAE   = average absolute error
    ECE   = expected calibration error of P(over)  (does "70%" hit ~70%?)

Use it to re-tune after new data, then copy the winning row's knobs into the
DEFAULT_*/*_BY_STAT constants in afl/model/player_props.py.

Examples:
    python scripts/calibrate_props.py --stat disposals --cutoff 2026-01-01
    python scripts/calibrate_props.py --all --reliability
"""
from __future__ import annotations

import argparse

import _common
from _common import table

import pandas as pd

from afl import pipeline
from afl.model import player_elo, player_props
from afl.model import prop_calibration as pc


def _load_stats() -> pd.DataFrame:
    try:
        # Enriched stats carry weather + venue_norm needed for the split test.
        return pipeline.load_player_stats_enriched()
    except FileNotFoundError:
        raise SystemExit("No player stats cached. Run:\n"
                         "  python scripts/fetch_data.py --start 2022 --end 2026 --players")


def calibrate_stat(ps, stat, cutoff, show_reliability):
    print(f"\n===== {stat} =====")
    grid = pc.grid_search(ps, stat, cutoff=cutoff)
    print("Grid search (ranked by |bias| then ECE):")
    print(table(grid.head(8).drop(columns=["abs_bias"])))

    # Score the *current production* defaults for comparison.
    ew = player_props.ELO_WEIGHT_BY_STAT.get(stat, player_props.DEFAULT_ELO_WEIGHT)
    rn = player_props.RECENT_N_BY_STAT.get(stat, player_props.DEFAULT_RECENT_N)
    ds = player_props.DISPERSION_SCALE_BY_STAT.get(stat, player_props.DEFAULT_DISPERSION_SCALE)
    elo = pc._fit_elo(ps, stat, cutoff) if ew > 0 else None
    recs = pc.projection_records(ps, stat, cutoff=cutoff, elo_model=elo,
                                 elo_weight=ew, recent_n=rn, dispersion_scale=ds)
    s = pc.score(recs, stat)
    print(f"\nCurrent defaults (elo_w={ew}, n={rn}, disp={ds}): "
          f"n={s['n']} bias={s['bias']:+.3f} mae={s['mae']} ece={s['ece']}")

    # Effect of the opponent/venue/weather splits (needs enriched stats).
    if {"wet", "windy", "venue_norm"} <= set(ps.columns):
        sw = player_props.SPLIT_WEIGHT_BY_STAT.get(stat, player_props.DEFAULT_SPLIT_WEIGHT)
        recs_split = pc.projection_records(
            ps, stat, cutoff=cutoff, elo_model=elo, elo_weight=ew, recent_n=rn,
            dispersion_scale=ds, use_splits=True, split_weight=sw,
            split_shrink=player_props.SPLIT_SHRINK)
        ss = pc.score(recs_split, stat)
        print(f"+ splits (weight={sw}, shrink={player_props.SPLIT_SHRINK}): "
              f"n={ss['n']} bias={ss['bias']:+.3f} mae={ss['mae']} ece={ss['ece']}")
    if show_reliability:
        rel = pd.DataFrame(s["reliability"], columns=["pred_prob", "actual_freq", "n"])
        print("Reliability (predicted P(over) vs realised frequency):")
        print(table(rel))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stat", default="disposals", choices=player_elo.RATED_STATS)
    ap.add_argument("--all", action="store_true", help="calibrate every rated stat")
    ap.add_argument("--cutoff", default="2026-01-01",
                    help="test window start; Elo/history use games before this")
    ap.add_argument("--reliability", action="store_true",
                    help="print the reliability table for current defaults")
    args = ap.parse_args()

    ps = _load_stats()
    stats = player_elo.RATED_STATS if args.all else [args.stat]
    for stat in stats:
        if stat not in ps:
            continue
        calibrate_stat(ps, stat, args.cutoff, args.reliability)


if __name__ == "__main__":
    main()
