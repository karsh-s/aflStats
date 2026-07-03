#!/usr/bin/env python3
"""Build the feature matrix, backtest, and train the match-winner model.

Examples:
    python scripts/train.py --start 2015 --end 2025
    python scripts/train.py --no-weather          # skip weather API calls (faster)
"""
from __future__ import annotations

import argparse

import _common
from _common import table

from afl import config, pipeline
from afl.model import margin_model, win_model


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", type=int, default=config.DEFAULT_START_SEASON)
    ap.add_argument("--end", type=int, default=2025)
    ap.add_argument("--no-weather", action="store_true",
                    help="skip per-game weather lookups")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    print(f"Building features {args.start}-{args.end} "
          f"(weather={'off' if args.no_weather else 'on'})...")
    feats, elo = pipeline.build_features(
        args.start, args.end,
        with_weather=not args.no_weather, refresh=args.refresh)
    completed = int(feats["home_win"].notna().sum())
    print(f"  {len(feats)} games, {completed} completed for training\n")

    print("Walk-forward backtest (model vs raw Elo baseline):")
    metrics = win_model.time_series_backtest(feats)
    for k, v in metrics.items():
        print(f"  {k:<16} {v}")
    print()

    print("Training final model on all completed games...")
    model = win_model.train(feats)
    path = model.save()
    print(f"  saved -> {path}\n")

    print("Margin model walk-forward backtest (model vs linear-Elo baseline):")
    m_metrics = margin_model.time_series_backtest(feats)
    for k, v in m_metrics.items():
        print(f"  {k:<16} {v}")
    if (m_metrics.get("model_mae") is not None
            and m_metrics["model_mae"] < m_metrics.get("elo_mae", float("inf"))):
        m_model = margin_model.train(feats)
        m_path = m_model.save()
        print(f"  GBM beats linear Elo -> saved {m_path}\n")
    else:
        print("  GBM does not beat linear Elo -> live path uses "
              f"margin = {margin_model.MARGIN_PER_ELO} x elo_diff (no pickle)\n")

    print("Current top-10 team Elo ratings:")
    import pandas as pd
    ladder = (pd.DataFrame(
        [{"team": t, "elo": round(r, 1)} for t, r in elo.ratings.items()])
        .sort_values("elo", ascending=False).head(10))
    print(table(ladder))


if __name__ == "__main__":
    main()
