#!/usr/bin/env python3
"""Download and cache AFL data.

Examples:
    python scripts/fetch_data.py --start 2015 --end 2025
    python scripts/fetch_data.py --start 2022 --end 2025 --players
"""
from __future__ import annotations

import argparse

import _common  # noqa: F401  (path bootstrap)

from afl import config, pipeline


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", type=int, default=config.DEFAULT_START_SEASON)
    ap.add_argument("--end", type=int, default=2025)
    ap.add_argument("--players", action="store_true",
                    help="also scrape per-player box scores from AFL Tables (slow)")
    ap.add_argument("--refresh", action="store_true", help="ignore cached data")
    args = ap.parse_args()

    print(f"Fetching games {args.start}-{args.end} from Squiggle...")
    games = pipeline.load_games(args.start, args.end, refresh=args.refresh)
    print(f"  {len(games)} games "
          f"({int((games['complete'] == 100).sum())} completed)")

    if args.players:
        print(f"Scraping player box scores {args.start}-{args.end} from AFL Tables...")
        ps = pipeline.load_player_stats(args.start, args.end, refresh=args.refresh)
        print(f"  {len(ps)} player-game rows for "
              f"{ps['player'].nunique() if not ps.empty else 0} players")
        print("Enriching box scores with per-game weather (one call per venue)...")
        enr = pipeline.enrich_player_stats(refresh=args.refresh)
        cov = enr["rain_mm"].notna().mean() * 100 if "rain_mm" in enr else 0
        print(f"  weather attached to {cov:.0f}% of rows "
              f"(rest roofed/unknown -> neutral)")

    print(f"Cached under {config.DATA_DIR}")


if __name__ == "__main__":
    main()
