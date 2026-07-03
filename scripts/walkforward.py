#!/usr/bin/env python3
"""Walk-forward online training: freeze the model at a cutoff (default Round 5,
2026), then step through every later game — predict the result and all player
stat lines, observe what happened, measure the error, and adjust — to present day.

Reports how the error evolves and compares the self-adjusting ("online") model
against a static snapshot frozen at the cutoff, so you can see the learning pay
off. The learned adjustments (home-ground edge, calibration, per-stat bias) are
saved to data/models/online_state.json.

    python scripts/walkforward.py
    python scripts/walkforward.py --cutoff-round 5 --year 2026
"""
from __future__ import annotations

import argparse
import json

import _common
from _common import table

import numpy as np
import pandas as pd

from afl import config, pipeline
from afl.data import squiggle, stadiums, weather
from afl.features import elo as elo_mod
from afl.model import online, player_elo


def _logloss(y, p):
    y = np.asarray(y, dtype=float)
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def _brier(y, p):
    return float(np.mean((np.asarray(p, dtype=float) - np.asarray(y, dtype=float)) ** 2))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--cutoff-round", type=int, default=5)
    ap.add_argument("--start", type=int, default=config.DEFAULT_START_SEASON)
    args = ap.parse_args()

    # ---- data --------------------------------------------------------------
    games = pipeline.load_games(args.start, args.year)
    season = games[(games["year"] == args.year) & (games["complete"] == 100)].copy()
    season = season.sort_values("date")
    walk = season[season["round"] > args.cutoff_round]
    if walk.empty:
        raise SystemExit(f"No completed games after round {args.cutoff_round} in {args.year}.")
    cutoff_date = season[season["round"] <= args.cutoff_round]["date"].max()
    hist_before = games[games["date"] <= cutoff_date]
    print(f"Cutoff: end of Round {args.cutoff_round} {args.year} ({cutoff_date.date()})")
    print(f"Walking {len(walk)} games (rounds {int(walk['round'].min())}–"
          f"{int(walk['round'].max())}) to present.\n")

    ps = pipeline.load_player_stats_enriched()
    ps_before = ps[ps["date"] <= cutoff_date]

    # ---- build three game learners sharing nothing -------------------------
    def fresh_elo():
        _, e = elo_mod.run(hist_before)
        return e

    learners = {
        "frozen":  online.OnlineGameLearner(fresh_elo(), adapt_ratings=False, adapt_params=False),
        "elo-only": online.OnlineGameLearner(fresh_elo(), adapt_ratings=True, adapt_params=False),
        "online":  online.OnlineGameLearner(fresh_elo(), adapt_ratings=True, adapt_params=True),
    }
    init_hga = learners["online"].hga
    preds = {k: [] for k in learners}
    ys = []

    # ---- player learners (frozen vs online) --------------------------------
    def fresh_player_state():
        elos = player_elo.fit_all(ps_before)
        hist = {p: g.sort_values("date").to_dict("records")
                for p, g in ps_before.groupby("player")}
        return elos, hist

    pl_online = online.OnlinePlayerLearner(fresh_player_state()[0], adapt=True)
    pl_frozen_elos, _ = fresh_player_state()
    pl_frozen = online.OnlinePlayerLearner(pl_frozen_elos, adapt=False)
    # shared, growing per-player history (both learners see the same games)
    _, player_hist = fresh_player_state()
    pcols = ["date", "opponent", "venue_norm", "wet", "windy"] + online.PLAYER_STATS
    perr = {m: {s: [] for s in online.PLAYER_STATS} for m in ("frozen", "online")}

    round_rows = []
    sample_lines = []

    for rnd, gp in walk.groupby("round"):
        for _, g in gp.iterrows():
            home, away, venue = g["hteam"], g["ateam"], g.get("venue", "")
            ys.append(1.0 if g["hscore"] > g["ascore"] else 0.0)
            for name, L in learners.items():
                p, _ = L.observe(home, away, g["hscore"], g["ascore"], venue, int(g["year"]))
                preds[name].append(p)

            # ---- player stats for this game -------------------------------
            day = g["date"].normalize()
            rows = ps[(ps["date"].dt.normalize() == day)
                      & (ps["team"].isin([home, away]))]
            forecast = weather.weather_for(venue, g["date"]) if venue else None
            for _, r in rows.iterrows():
                player = r["player"]
                is_home = r["team"] == home
                opp = away if is_home else home
                vnorm = stadiums.normalise_venue(venue)
                prior_list = player_hist.get(player, [])
                if len(prior_list) >= 3:
                    prior = pd.DataFrame(prior_list)
                    for stat in online.PLAYER_STATS:
                        actual = float(r[stat])
                        pp_on = pl_online.predict(prior, player, stat, opp, vnorm, is_home, forecast)
                        pp_fr = pl_frozen.predict(prior, player, stat, opp, vnorm, is_home, forecast)
                        perr["online"][stat].append(abs(pp_on - actual))
                        perr["frozen"][stat].append(abs(pp_fr - actual))
                        pl_online.observe(player, stat, pp_on, actual, opp, is_home)
                        pl_frozen.observe(player, stat, pp_fr, actual, opp, is_home)
                        if stat == "disposals" and len(sample_lines) < 6 and len(prior_list) > 8:
                            sample_lines.append({
                                "round": int(rnd), "player": player,
                                "pred": round(pp_on, 1), "actual": int(actual),
                                "err": round(pp_on - actual, 1)})
                # append this game's actuals to the player's running history
                player_hist.setdefault(player, []).append({c: r[c] for c in pcols})

        # per-round snapshot of cumulative error
        round_rows.append({
            "round": int(rnd), "games": int((walk["round"] == rnd).sum()),
            "online_logloss": round(_logloss(ys, preds["online"]), 3),
            "frozen_logloss": round(_logloss(ys, preds["frozen"]), 3),
            "online_acc": round(float(np.mean((np.array(preds["online"]) > 0.5)
                                               == np.array(ys))), 3),
            "hga": round(learners["online"].hga, 1),
        })

    # ======================= report ========================================
    y = np.array(ys)
    print("Game-outcome model — cumulative error over the walk:")
    print(table(pd.DataFrame(round_rows)))
    print("\nFinal game metrics (lower log-loss / Brier = better):")
    summ = pd.DataFrame([{
        "model": k,
        "logloss": round(_logloss(y, preds[k]), 4),
        "brier": round(_brier(y, preds[k]), 4),
        "accuracy": round(float(np.mean((np.array(preds[k]) > 0.5) == y)), 4),
    } for k in learners])
    print(table(summ))

    L = learners["online"]
    print(f"\nWhat the game model learned:")
    print(f"  home-ground edge : {init_hga:.0f} -> {L.hga:.1f} Elo pts")
    print(f"  calibration      : a={L.a:.3f}, b={L.b:.3f} (1.0/0.0 = no change)")

    print("\nPlayer stats — mean absolute error (online vs frozen-at-cutoff):")
    prows = []
    for stat in online.PLAYER_STATS:
        on = float(np.mean(perr["online"][stat])) if perr["online"][stat] else float("nan")
        fr = float(np.mean(perr["frozen"][stat])) if perr["frozen"][stat] else float("nan")
        prows.append({"stat": stat, "n": len(perr["online"][stat]),
                      "frozen_MAE": round(fr, 3), "online_MAE": round(on, 3),
                      "learned_bias": round(pl_online.bias[stat], 2)})
    print(table(pd.DataFrame(prows)))

    print("\nSample of learned-from predictions (disposals):")
    print(table(pd.DataFrame(sample_lines)))

    # ---- persist learned adjustments --------------------------------------
    state = {
        "cutoff_round": args.cutoff_round, "year": args.year,
        "hga": L.hga, "cal_a": L.a, "cal_b": L.b,
        "player_bias": pl_online.bias,
    }
    out = config.MODEL_DIR / "online_state.json"
    out.write_text(json.dumps(state, indent=2))
    print(f"\nSaved learned adjustments -> {out}")
    print("Note: walk-forward is leak-free (each prediction uses only prior games).")


if __name__ == "__main__":
    main()
