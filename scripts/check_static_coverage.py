#!/usr/bin/env python3
"""Fail the build when the frontend asks for a snapshot that was never exported.

The static site can only serve files that scripts/export_static.py wrote. If a
component changes a query parameter — useValueBets(0.03) when only 0.04 was
snapshotted, or a multis floor of 0.7 when only 0.6/0.8 exist — the fetch 404s
and that section renders empty with no error anywhere. That has now bitten
twice (the target-odds tab and the Best Lines table), so this check makes the
drift loud instead of silent.

It scans the TSX for the parameterised hooks and asserts the matching file
exists in afl-index/public/data.

    python scripts/check_static_coverage.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "afl-index" / "src"
DATA = ROOT / "afl-index" / "public" / "data"


def _num(s: str) -> str:
    """Match how JS stringifies numbers into the URL (0.60 -> 0.6)."""
    f = float(s)
    return str(int(f)) if f == int(f) else str(f)


def main() -> None:
    if not DATA.exists():
        sys.exit(f"No snapshot directory at {DATA} — run export_static.py first.")
    have = {p.name for p in DATA.glob("*.json")}
    tsx = "\n".join(p.read_text() for p in SRC.rglob("*.tsx"))

    expected: set[str] = set()

    # useValueBets(0.04) -> value__min_edge_0.04.json
    for m in re.findall(r"useValueBets\(\s*([\d.]+)\s*\)", tsx):
        expected.add(f"value__min_edge_{_num(m)}.json")

    # usePlayerStats(1) -> stats_players__min_games_1.json
    for m in re.findall(r"usePlayerStats\(\s*([\d.]+)\s*\)", tsx):
        expected.add(f"stats_players__min_games_{_num(m)}.json")

    # useGameTargetMultis(id, safeMode ? 0.8 : 0.6) -> one file per floor,
    # for every fixture in the exported events list.
    floors = set()
    for call in re.finditer(r"useGameTargetMultis\(", tsx):
        # Look ahead past any comments to the ternary that picks the floor.
        window = tsx[call.end(): call.end() + 400]
        window = re.sub(r"//[^\n]*", "", window)          # strip line comments
        tern = re.search(r"\?\s*([\d.]+)\s*:\s*([\d.]+)", window)
        if tern:
            floors.update(_num(x) for x in tern.groups())
    if floors:
        import json
        ev_file = DATA / "events.json"
        if ev_file.exists():
            for ev in json.loads(ev_file.read_text()):
                for f in floors:
                    expected.add(f"game_{ev['id']}_multis__floor_{f}.json")

    missing = sorted(e for e in expected if e not in have)
    if missing:
        print(f"MISSING {len(missing)} snapshot file(s) the frontend requests:")
        for m in missing[:12]:
            print(f"  - {m}")
        if len(missing) > 12:
            print(f"  ... and {len(missing) - 12} more")
        sys.exit("Frontend/export parameter drift — sections would render empty.")

    print(f"OK — all {len(expected)} parameterised requests have snapshots.")


if __name__ == "__main__":
    main()
