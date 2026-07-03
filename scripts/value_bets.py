#!/usr/bin/env python3
"""Compare the model's win probabilities against bookmaker head-to-head odds
(via The Odds API) and surface positive-value bets.

Requires ODDS_API_KEY in your environment/.env.

Example:
    python scripts/value_bets.py --year 2025 --min-edge 0.03
"""
from __future__ import annotations

import argparse

import _common
from _common import table

import pandas as pd

from afl import config, pipeline
from afl.features import build as build_mod
from afl.odds import theoddsapi, value


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--start", type=int, default=config.DEFAULT_START_SEASON)
    ap.add_argument("--min-edge", type=float, default=0.02,
                    help="minimum model-vs-fair edge to flag (default 0.02 = 2%%)")
    ap.add_argument("--kelly", type=float, default=0.25, help="Kelly fraction")
    args = ap.parse_args()

    history = pipeline.load_games(args.start, args.year)
    _, elo = build_mod.elo_mod.run(history)
    from afl.model.adjustments import current as _adj
    adj = _adj()
    if adj is not None:
        elo.hga = adj.home_ground_edge
    try:
        model = pipeline.load_model()
    except FileNotFoundError:
        model = None

    odds = theoddsapi.h2h_odds(markets="h2h")
    if odds.empty:
        print("No odds returned (check ODDS_API_KEY / that AFL is in season).")
        return
    odds = odds[odds["market"] == "h2h"]
    best = value.best_lines(odds, group_cols=["event_id", "outcome"])

    rows = []
    for event_id, ev in best.groupby("event_id"):
        home_team = ev["home_team"].iloc[0]
        away_team = ev["away_team"].iloc[0]
        try:
            price = {r["outcome"]: r["price"] for _, r in ev.iterrows()}
            home_price = price.get(home_team)
            away_price = price.get(away_team)
            if not home_price or not away_price:
                continue
        except Exception:
            continue

        feat = build_mod.feature_row_for_fixture(
            elo, history, home_team, away_team, "", ev["commence_time"].iloc[0])
        p_home = (float(model.predict_proba(pd.DataFrame([feat]))[0])
                  if model is not None else feat["elo_exp_home"])
        if adj is not None:
            p_home = adj.calibrate(p_home)

        for team, price_, pair, p in [
            (home_team, home_price, away_price, p_home),
            (away_team, away_price, home_price, 1 - p_home),
        ]:
            v = value.evaluate_market(p, price_, pair, kelly=args.kelly)
            if v["edge"] >= args.min_edge:
                rows.append({
                    "match": f"{home_team} v {away_team}",
                    "bet": team,
                    "price": price_,
                    "model": f"{p*100:.0f}%",
                    "fair": f"{v['book_fair']*100:.0f}%",
                    "edge": f"{v['edge']*100:+.1f}%",
                    "EV/unit": v["ev_per_unit"],
                    "kelly": v["kelly_stake"],
                })

    if not rows:
        print("No value bets above the edge threshold right now.")
        return
    out = pd.DataFrame(rows).sort_values("EV/unit", ascending=False)
    print(f"\nValue bets (edge >= {args.min_edge*100:.0f}%):\n")
    print(table(out))
    print("\nStakes are fractional-Kelly fractions of bankroll. Bet responsibly.")


if __name__ == "__main__":
    main()
