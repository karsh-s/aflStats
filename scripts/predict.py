#!/usr/bin/env python3
"""Predict win probabilities for a round's fixtures.

Combines the trained model with current Elo, form, H2H and the match-day weather
forecast. Falls back to the Elo probability if no trained model is found.

Examples:
    python scripts/predict.py --year 2025 --round 15
    python scripts/predict.py --year 2025 --round 15 --no-weather
"""
from __future__ import annotations

import argparse

import _common
from _common import table

import pandas as pd

from afl import config, pipeline
from afl.features import build as build_mod
from afl.features import h2h as h2h_mod
from afl.data import squiggle


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--start", type=int, default=config.DEFAULT_START_SEASON)
    ap.add_argument("--no-weather", action="store_true")
    args = ap.parse_args()

    history = pipeline.load_games(args.start, args.year)
    _, elo = build_mod.elo_mod.run(history)

    # Apply the walk-forward's learned home-ground edge + win-prob calibration.
    from afl.model.adjustments import current as _adj
    adj = _adj()
    if adj is not None:
        elo.hga = adj.home_ground_edge
        print(f"(applying learned adjustments: HGA={adj.hga:.1f}, "
              f"calibration a={adj.cal_a:.2f} b={adj.cal_b:.2f})\n")

    try:
        model = pipeline.load_model()
    except FileNotFoundError:
        model = None
        print("(no trained model found - falling back to Elo probabilities)\n")

    fixtures = squiggle.upcoming(args.year, args.round)
    if fixtures.empty:
        print("No fixtures found for that round.")
        return

    rows = []
    for _, g in fixtures.iterrows():
        home, away, venue = g["hteam"], g["ateam"], g.get("venue", "")
        feat = build_mod.feature_row_for_fixture(
            elo, history, home, away, venue, g["date"],
            with_weather=not args.no_weather)
        if model is not None:
            p_home = float(model.predict_proba(pd.DataFrame([feat]))[0])
        else:
            p_home = feat["elo_exp_home"]
        if adj is not None:
            p_home = adj.calibrate(p_home)
        h2h = h2h_mod.summary(history, home, away, last=10)
        rows.append({
            "date": g["date"].strftime("%a %d-%b"),
            "home": home, "away": away,
            "venue": venue,
            "P(home win)": f"{p_home*100:.0f}%",
            "P(away win)": f"{(1-p_home)*100:.0f}%",
            "pick": home if p_home >= 0.5 else away,
            "elo_diff": round(feat["elo_diff"], 0),
            "H2H(last10)": f"{h2h.get(home+'_wins', 0)}-{h2h.get(away+'_wins', 0)}"
                           if h2h.get("meetings") else "n/a",
            "rain_mm": round(feat["rain_mm"], 1),
        })

    print(f"\nPredictions - {args.year} Round {args.round}\n")
    print(table(pd.DataFrame(rows)))


if __name__ == "__main__":
    main()
