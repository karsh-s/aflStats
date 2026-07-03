#!/usr/bin/env python3
"""Project player props and estimate the probability each line cashes, then
(optionally) compare against The Odds API player-prop markets for value.

Needs player box-score data first:
    python scripts/fetch_data.py --start 2022 --end 2025 --players

Examples:
    # Project a single line by hand:
    python scripts/player_props.py --player "Bontempelli, Marcus" \
        --stat disposals --opponent "Geelong" --home --line 27.5

    # Pull live prop odds for upcoming games and find value:
    python scripts/player_props.py --odds --min-edge 0.04
"""
from __future__ import annotations

import argparse

import _common
from _common import table

import pandas as pd

from afl import config, pipeline
from afl.data import squiggle, weather
from afl.model import player_elo, player_props
from afl.odds import theoddsapi, value


def _load_stats() -> pd.DataFrame:
    try:
        # Enriched (weather + normalised venue) if available; raw otherwise.
        return pipeline.load_player_stats_enriched()
    except FileNotFoundError:
        raise SystemExit(
            "No player stats cached. Run:\n"
            "  python scripts/fetch_data.py --start 2022 --end 2026 --players")


def _fixture_venues(year: int) -> dict:
    """Map (home, away) canonical team names -> (venue, date) for a season,
    so live odds events can be matched to a ground for the weather/venue split."""
    try:
        fx = squiggle.games(year)
    except Exception:
        return {}
    out = {}
    for _, g in fx.iterrows():
        out[(g["hteam"], g["ateam"])] = (g.get("venue", ""), g["date"])
    return out


def single_line(args, ps, elos) -> None:
    elo = elos.get(args.stat)
    forecast = None
    if args.venue and args.date:
        forecast = weather.weather_for(args.venue, pd.to_datetime(args.date))
    res = player_props.project_line(
        ps, args.player, args.stat, args.opponent, args.home, args.line, elo=elo,
        venue=args.venue, forecast=forecast)
    c = res["components"]
    print(f"\n{args.player} - {args.stat} vs {args.opponent} "
          f"({'home' if args.home else 'away'}"
          f"{', ' + args.venue if args.venue else ''})\n")
    print(f"  projection : {res['projection']}  (sd {res['sd']}, "
          f"{res['n_games']} games, {res['dist']})")
    print(f"  breakdown  : base {c.get('base', 0)}"
          f"  | vs opp {c.get('opponent', 0):+}"
          f"  | at venue {c.get('venue', 0):+}"
          f"  | weather {c.get('weather', 0):+}")
    if forecast:
        print(f"  forecast   : {forecast['rain_mm']}mm rain, "
              f"{forecast['wind_kmh']}km/h wind")
    print(f"  line       : {args.line}")
    print(f"  P(over)    : {res['prob_over']*100:.1f}%")
    print(f"  P(under)   : {res['prob_under']*100:.1f}%")

    if args.explain:
        brk = player_props.explain_split(ps, args.player, args.stat,
                                         opponent=args.opponent)
        if not brk.empty:
            print(f"\n  Each meeting vs {args.opponent} vs his form at the time "
                  f"(±{player_props.LOCAL_WINDOW} games):")
            print(table(brk))
            print(f"  -> form-adjusted opponent effect feeds the 'vs opp' "
                  f"component above (shrunk for sample size).")


def odds_scan(args, ps, elos) -> None:
    events = theoddsapi.list_events()
    if events.empty:
        print("No upcoming AFL events from the odds feed.")
        return
    index = player_props.build_player_index(ps)
    venues = _fixture_venues(args.year)
    rows = []
    unmatched = set()
    for _, ev in events.iterrows():
        props = theoddsapi.player_prop_odds(ev["id"])
        if props.empty:
            continue
        home, away = ev["home_team"], ev["away_team"]
        # Match to a Squiggle fixture for the venue, then get its weather.
        venue, match_date = venues.get((home, away), ("", ev["commence_time"]))
        forecast = weather.weather_for(venue, pd.to_datetime(match_date)) if venue else None
        for _, o in props.iterrows():
            stat = o["stat"]
            if stat not in player_elo.RATED_STATS:
                continue

            # Anytime goalscorer has no line; it's just P(1+ goals) = P(>0.5).
            is_anytime = o["market"] == "player_goal_scorer_anytime"
            if not is_anytime and o["line"] is None:
                continue

            # Reconcile the bookmaker's "First Last" to a scraped player.
            scraped = player_props.resolve_player(o["player"], index)
            if scraped is None:
                unmatched.add(o["player"])
                continue

            phist = ps[ps["player"] == scraped]
            # Small samples produce unreliable projections (and most of the
            # spurious "value"); require a minimum game history.
            if len(phist) < args.min_games:
                continue
            last_team = phist.sort_values("date")["team"].iloc[-1]
            is_home = last_team == home
            opponent = away if is_home else home

            elo = elos.get(stat)
            proj = player_props.project(ps, scraped, stat, opponent, is_home,
                                        elo=elo, venue=venue, forecast=forecast)

            if is_anytime:
                p = proj.prob_over(0.5)        # P(kicks at least one goal)
                bet_label = "Anytime goal"
            else:
                side = str(o["side"]).lower()
                p = (proj.prob_over(o["line"]) if side == "over"
                     else proj.prob_under(o["line"]))
                bet_label = f"{o['side']} {o['line']}"

            v = value.evaluate_market(p, o["price"])
            if v["edge"] >= args.min_edge:
                rows.append({
                    "match": f"{home} v {away}",
                    "player": o["player"], "stat": stat,
                    "bet": bet_label,
                    "book": o["bookmaker"], "price": o["price"],
                    "proj": round(proj.mean, 1),
                    "model": f"{p*100:.0f}%",
                    "edge": f"{v['edge']*100:+.1f}%",
                    "EV/unit": v["ev_per_unit"],
                })
    if unmatched:
        print(f"({len(unmatched)} players in odds feed had no scraped history "
              f"and were skipped)")
    if not rows:
        print("No player-prop value found above the edge threshold.")
        return
    out = pd.DataFrame(rows).sort_values("EV/unit", ascending=False)
    print("\nPlayer-prop value bets:\n")
    print(table(out))
    print("\nProjections rely on scraped box scores; treat as a screen, not gospel.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--player")
    ap.add_argument("--stat", default="disposals",
                    choices=player_elo.RATED_STATS)
    ap.add_argument("--opponent")
    ap.add_argument("--home", action="store_true")
    ap.add_argument("--line", type=float)
    ap.add_argument("--venue", help="venue (enables the venue split; e.g. 'M.C.G.')")
    ap.add_argument("--date", help="match date YYYY-MM-DD (with --venue, enables "
                                   "the weather split)")
    ap.add_argument("--odds", action="store_true",
                    help="scan live player-prop odds for value instead")
    ap.add_argument("--year", type=int, default=2026,
                    help="season to match fixtures/venues for the --odds scan")
    ap.add_argument("--min-edge", type=float, default=0.04)
    ap.add_argument("--min-games", type=int, default=8,
                    help="skip players with fewer than this many scraped games")
    ap.add_argument("--explain", action="store_true",
                    help="(single line) show the per-meeting form-adjusted breakdown")
    args = ap.parse_args()

    ps = _load_stats()
    print("Fitting player Elo ratings...")
    elos = player_elo.fit_all(ps)

    if args.odds:
        odds_scan(args, ps, elos)
    elif args.player and args.opponent and args.line is not None:
        single_line(args, ps, elos)
    else:
        ap.error("provide --player/--opponent/--line, or use --odds")


if __name__ == "__main__":
    main()
