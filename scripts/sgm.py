#!/usr/bin/env python3
"""Build the *safest* SportsBet Same Game Multi for 2x / 3x / 5x / 10x targets.

Uses every integer "X+" milestone SportsBet posts (16+, 17+, ... disposals, plus
goal/tackle milestones and anytime goal), prices the multi as the product of the
legs, and picks the combination most likely to land (per our calibrated model)
while clearing each target multiplier.

Needs ODDS_API_KEY and the enriched box scores
(python scripts/fetch_data.py --start 2022 --end 2026 --players).

Examples:
    python scripts/sgm.py                       # every upcoming game
    python scripts/sgm.py --team Brisbane       # just games involving a team
    python scripts/sgm.py --targets 2 3 5 10 20 # custom multipliers
"""
from __future__ import annotations

import argparse

import _common
from _common import table

import pandas as pd

from afl import config, pipeline
from afl.data import squiggle, weather
from afl.features import elo as elo_mod
from afl.model import margin_model as margin_mod, player_elo
from afl.odds import sgm, theoddsapi


def _fixture_venues(year: int) -> dict:
    try:
        fx = squiggle.games(year)
    except Exception:
        return {}
    return {(g["hteam"], g["ateam"]): (g.get("venue", ""), g["date"])
            for _, g in fx.iterrows()}


def _print_multi(target, res) -> None:
    if res is None:
        print(f"\n  {target}x target: no safe combination found from available lines.")
        return
    rows = [{
        "leg": f"{leg['player']}  {leg['milestone']}",
        "odds": round(leg["odds"], 2),
        "model P": f"{leg['prob']*100:.0f}%",
    } for leg in res["legs"]]
    print(f"\n  ── Safest ~{target}x ({res['n_legs']} legs) "
          f"── combined {res['combined_odds']:.2f}x ──")
    print(table(pd.DataFrame(rows)))
    # Independence-based joint probability (optimistic — see caveats).
    print(f"  model joint P(all land) ~ {res['joint_prob']*100:.1f}%  "
          f"(book-implied {res['implied_prob']*100:.1f}%, breakeven hit-rate)")
    stats = {leg["stat"] for leg in res["legs"]}
    if len(stats) == 1:
        print(f"  ⚠ all {res['n_legs']} legs are {stats.pop()} — they move together "
              f"(a slow game sinks them all), so the real hit-rate is lower than shown.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--team", help="only games involving this team (partial name ok)")
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--targets", type=float, nargs="+", default=[2, 3, 5, 10])
    ap.add_argument("--min-games", type=int, default=8)
    ap.add_argument("--max-legs", type=int, default=7)
    ap.add_argument("--max-per-stat", type=int, default=None,
                    help="cap legs sharing a stat (e.g. 2) to diversify and cut "
                         "in-game correlation")
    args = ap.parse_args()

    ps = pipeline.load_player_stats_enriched()
    print("Fitting player Elo ratings...")
    elos = player_elo.fit_all(ps)
    venues = _fixture_venues(args.year)

    # Game-level inputs for the tactical game-script signal.
    games_hist = pipeline.load_games(config.DEFAULT_START_SEASON, args.year)
    _, team_elo = elo_mod.run(games_hist)
    try:
        m_model = margin_mod.MarginModel.load()
    except FileNotFoundError:
        m_model = None

    events = theoddsapi.list_events()
    if events.empty:
        print("No upcoming AFL events from the odds feed.")
        return
    if args.team:
        t = args.team.lower()
        events = events[events.apply(
            lambda e: t in str(e["home_team"]).lower() or t in str(e["away_team"]).lower(),
            axis=1)]
    if events.empty:
        print("No upcoming games match that team.")
        return

    for _, ev in events.iterrows():
        home, away = ev["home_team"], ev["away_team"]
        legs = theoddsapi.milestone_legs(ev["id"])
        if legs.empty:
            continue
        venue, mdate = venues.get((home, away), ("", ev["commence_time"]))
        forecast = weather.weather_for(venue, pd.to_datetime(mdate)) if venue else None
        exp_margin = margin_mod.expected_margin(
            m_model, team_elo, games_hist, home, away, venue, pd.to_datetime(mdate))
        priced = sgm.attach_model_probs(legs, ps, elos, venue=venue, forecast=forecast,
                                        home=home, away=away, min_games=args.min_games,
                                        exp_margin=exp_margin)
        if priced.empty:
            continue
        print(f"\n{'='*64}\n{home} v {away}"
              f"{('  @ ' + venue) if venue else ''}   "
              f"({legs['player'].nunique()} players, {len(legs)} milestone lines)")
        multis = sgm.build_for_targets(priced, targets=tuple(args.targets),
                                       max_legs=args.max_legs,
                                       max_per_stat=args.max_per_stat)
        for t in args.targets:
            _print_multi(t, multis[t])

    print("\nNotes:")
    print(" - 'Safest' = the leg combo most likely (per our calibrated model) to")
    print("   all land while clearing the target multiplier, using every integer")
    print("   milestone SportsBet posts.")
    print(" - Combined odds = product of legs. SportsBet's real SGM price applies")
    print("   correlation adjustments and will be SHORTER, so true value is lower")
    print("   than the gap to book-implied suggests.")
    print(" - The model's edge is largest on heavily-juiced favourite milestones,")
    print("   which is exactly where it's most likely overconfident. Treat the")
    print("   joint probability as an optimistic ceiling, not a guarantee.")
    print(" - Gambling involves risk. Bet within your means.")


if __name__ == "__main__":
    main()
