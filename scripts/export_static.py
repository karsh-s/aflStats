#!/usr/bin/env python3
"""Snapshot the API into static JSON for the GitHub Pages build.

GitHub Pages serves files, not Python — so the site can't call FastAPI. This
walks every endpoint the frontend requests and writes the responses under
``afl-index/public/data/``. The deployed site then reads those files instead
of localhost:8001 (see ``staticUrl`` in src/lib/api.ts, which builds the same
slugs).

Usage (API must be running on :8001):
    .venv/bin/python scripts/export_static.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "afl-index" / "public" / "data"
API = "http://localhost:8001"
TIMEOUT = 600


def slug(path: str) -> str:
    """/api/game/ID/multis?floor=0.6 -> game_ID_multis__floor_0.6.json

    Must stay in lockstep with ``staticUrl()`` in src/lib/api.ts.
    """
    p = path[len("/api/"):] if path.startswith("/api/") else path.lstrip("/")
    if "?" in p:
        p, q = p.split("?", 1)
        q = q.replace("=", "_").replace("&", "_")
        return f"{p.replace('/', '_')}__{q}.json"
    return f"{p.replace('/', '_')}.json"


def fetch(path: str) -> object | None:
    try:
        r = requests.get(f"{API}{path}", timeout=TIMEOUT)
        if not r.ok:
            print(f"  ! {path} -> HTTP {r.status_code}")
            return None
        return r.json()
    except Exception as e:
        print(f"  ! {path} -> {e}")
        return None


def write(path: str, data: object) -> None:
    f = OUT / slug(path)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, separators=(",", ":")))
    size = f.stat().st_size / 1024
    print(f"  {path}  ->  {f.name}  ({size:.0f} KB)")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        requests.get(f"{API}/api/health", timeout=20).raise_for_status()
    except Exception:
        sys.exit("API is not running on :8001 — start it before exporting.")

    # --- season-wide endpoints ------------------------------------------
    simple = [
        "/api/events",
        "/api/ladder?year=2026",
        "/api/stats/teams?year=2026",
        "/api/stats/players?min_games=1",
        "/api/season/current-round",
        "/api/analysis/team-styles",
        "/api/analysis/style-matchups",
        "/api/analysis/position-concession",
        "/api/analysis/role-leaks",
        "/api/live/games",
        "/api/live/status",
        "/api/historical/rounds",
        "/api/value?min_edge=0.04",
        "/api/value?min_edge=0.03",
    ]
    print("Season endpoints:")
    events = None
    failed: list[str] = []
    for path in simple:
        data = fetch(path)
        if data is None:
            failed.append(path)
            continue
        write(path, data)
        if path == "/api/events":
            events = data

    # /api/events failing means every per-fixture file below is skipped and the
    # previous (stale) odds stay deployed. That used to pass silently — a bad
    # ODDS_API_KEY would quietly ship week-old multis — so it is fatal now.
    if not events:
        sys.exit("FATAL: /api/events returned nothing — odds data could not be "
                 "refreshed (check ODDS_API_KEY). Refusing to deploy a snapshot "
                 "with stale fixtures/odds.")

    # --- per-fixture endpoints ------------------------------------------
    if events:
        print(f"\nPer-game endpoints ({len(events)} fixtures):")
        for ev in events:
            eid = ev.get("id")
            if not eid:
                continue
            print(f" {ev.get('home')} v {ev.get('away')}")
            for path in (f"/api/game/{eid}/sgm",
                         f"/api/game/{eid}/props",
                         f"/api/game/{eid}/best-lines",
                         f"/api/game/{eid}/multis?floor=0.6",
                         f"/api/game/{eid}/multis?floor=0.8"):
                data = fetch(path)
                if data is not None:
                    write(path, data)

    # --- historical rounds for the current season ------------------------
    rounds = fetch("/api/historical/rounds")
    if rounds:
        cur = [r for r in rounds if r.get("season") == 2026]
        print(f"\nHistorical rounds (2026): {len(cur)}")
        for r in cur:
            path = (f"/api/historical/round?season={r['season']}"
                    f"&rnd={requests.utils.quote(str(r['round']))}")
            data = fetch(path)
            if data is not None:
                write(path, data)

    if failed:
        print(f"\nWARNING: {len(failed)} endpoint(s) failed: {failed}")

    manifest = {"generated": __import__("datetime").datetime.utcnow().isoformat(),
                "files": sorted(p.name for p in OUT.glob("*.json"))}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1))
    total = sum(p.stat().st_size for p in OUT.glob("*.json")) / 1024 / 1024
    print(f"\nWrote {len(manifest['files'])} files ({total:.1f} MB) -> {OUT}")


if __name__ == "__main__":
    main()
