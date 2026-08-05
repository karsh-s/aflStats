"""Automatic live tracking + settlement for the multi tracker.

AFL Paradise-style pipeline using the AFL official (Champion Data) API:

  * During game windows: poll live per-player stats (~90s cadence) and write
    them to ``api/data/live_player_stats.json`` so the tracker page can show
    each pending leg's current disposals in real time.
  * When a match concludes: settle every pending bet on that game directly
    from the AFL API's final player stats — no manual AFL Tables refresh, no
    button pressing. The tracker updates itself.

Runs as a daemon thread started from api.main's startup hook.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from afl.data import afl_api
from afl.model.player_props import canonical_name

DATA_DIR = Path(__file__).parent / "data"
LIVE_STATS_FILE = DATA_DIR / "live_player_stats.json"
TRACKER_FILE = DATA_DIR / "multi_tracker.json"

TRACKER_LOCK = threading.Lock()

POLL_LIVE = 90        # seconds between polls while a tracked game is live
POLL_IDLE = 900       # seconds between checks otherwise
LOOKBACK_ROUNDS = 6   # rounds scanned for concluded games needing settlement

_stop = threading.Event()
_thread: threading.Thread | None = None


# ---------------------------------------------------------------------------
# Tracker file helpers (lock shared with api.main via TRACKER_LOCK)
# ---------------------------------------------------------------------------

def _load_tracker() -> dict:
    if not TRACKER_FILE.exists():
        return {"bets": []}
    with open(TRACKER_FILE) as f:
        return json.load(f)


def _save_tracker(data: dict) -> None:
    with open(TRACKER_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _pending_games(data: dict) -> dict[frozenset, list[dict]]:
    """Pending bets grouped by the {home, away} team pair."""
    out: dict[frozenset, list[dict]] = {}
    for b in data.get("bets", []):
        if b.get("status") != "pending":
            continue
        try:
            home, away = [s.strip() for s in b["game"].split(" v ")]
        except ValueError:
            continue
        out.setdefault(frozenset((home, away)), []).append(b)
    return out


# ---------------------------------------------------------------------------
# Settlement from AFL API final stats
# ---------------------------------------------------------------------------

def _stats_by_canonical(players: list[dict]) -> dict[str, dict]:
    return {canonical_name(p["name"]): p for p in players}


def settle_game_from_stats(bets: list[dict], players: list[dict]) -> int:
    """Resolve each pending bet's legs against AFL API FINAL player stats.

    Only called for CONCLUDED matches, so a leg whose player has no stats row
    did not play (late out / omitted) — the leg cannot win and resolves as a
    miss. (A bookmaker would void the leg and re-price the multi; for model
    tracking, picking a non-player is a failed pick.)
    Mutates the bet dicts in place; returns how many bets were settled.
    """
    lookup = _stats_by_canonical(players)
    settled = 0
    for bet in bets:
        all_resolved, all_hit = True, True
        for leg in bet.get("legs", []):
            if leg.get("result") is not None:
                if not leg["result"]:
                    all_hit = False
                continue
            key = canonical_name(leg.get("player_scraped") or leg.get("player", ""))
            row = lookup.get(key)
            stat = leg.get("stat")
            val = row.get(stat) if row else None
            if val is None:
                # Final stats, player absent (or stat missing): leg misses.
                leg["result"] = False
                leg["actual_value"] = None
                all_hit = False
                continue
            hit = float(val) > float(leg.get("line", 0))
            leg["result"] = bool(hit)
            leg["actual_value"] = float(val)
            if not hit:
                all_hit = False
        if all_resolved:
            bet["status"] = "won" if all_hit else "lost"
            stake = float(bet.get("stake", 5.0))
            bet["pnl"] = (round(stake * float(bet["combined_odds"]) - stake, 2)
                          if all_hit else -stake)
            bet["result_checked_at"] = datetime.utcnow().isoformat()
            settled += 1
    return settled


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def _within_window(utc_start: str, hours_after: float = 3.5) -> bool:
    try:
        start = datetime.fromisoformat(utc_start.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return False
    now = datetime.now(timezone.utc)
    return start - timedelta(minutes=15) <= now <= start + timedelta(hours=hours_after)


def _cycle() -> bool:
    """One poll cycle. Returns True if any tracked game is currently live."""
    data = _load_tracker()
    pending = _pending_games(data)
    if not pending:
        return False

    season = afl_api.current_season()
    if not season:
        return False
    # Scan the current round plus several prior ones. Pending bets can be more
    # than one round old if the poller was down when those games concluded —
    # without the wider window those bets would hang unsettled forever.
    cur = int(season.get("currentRoundNumber") or 1)
    matches = []
    for rnd in range(cur, max(0, cur - LOOKBACK_ROUNDS), -1):
        matches += afl_api.round_matches(season["id"], rnd)

    any_live = False
    live_out: dict = {}
    dirty = False

    for m in matches:
        pair = frozenset((m["home"], m["away"]))
        if pair not in pending:
            continue
        status = str(m.get("status", ""))
        is_live = status in afl_api.LIVE_STATUSES or (
            status not in afl_api.DONE_STATUSES and _within_window(m["utc_start"]))
        is_done = status in afl_api.DONE_STATUSES

        if not (is_live or is_done):
            continue
        stats = afl_api.match_player_stats(m["provider_id"])
        if not stats:
            continue

        if is_live and not is_done:
            any_live = True
            live_out[m["provider_id"]] = {
                "home": m["home"], "away": m["away"], "status": status,
                "updated": datetime.utcnow().isoformat(),
                "players": {canonical_name(p["name"]): {
                    k: p.get(k) for k in ("disposals", "goals", "marks",
                                          "tackles", "hitouts")}
                    for p in stats["players"]},
            }
        if is_done:
            with TRACKER_LOCK:
                fresh = _load_tracker()
                bets = [b for b in fresh["bets"]
                        if b.get("status") == "pending"
                        and frozenset(s.strip() for s in b["game"].split(" v ")) == pair]
                n = settle_game_from_stats(bets, stats["players"])
                if n:
                    _save_tracker(fresh)
                    print(f"[afl-live] auto-settled {n} bets for "
                          f"{m['home']} v {m['away']}")
                    dirty = True

    # Persist live snapshot (merge: keep other games' last snapshot this cycle)
    try:
        existing = (json.loads(LIVE_STATS_FILE.read_text())
                    if LIVE_STATS_FILE.exists() else {})
    except Exception:
        existing = {}
    existing.update(live_out)
    # Drop entries for games no longer pending
    still = {pid: v for pid, v in existing.items()
             if frozenset((v.get("home"), v.get("away"))) in pending or pid in live_out}
    LIVE_STATS_FILE.write_text(json.dumps(still, indent=1))
    return any_live


def _loop() -> None:
    while not _stop.is_set():
        try:
            live = _cycle()
        except Exception as e:
            print(f"[afl-live] cycle error: {e}")
            live = False
        _stop.wait(POLL_LIVE if live else POLL_IDLE)


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _thread = threading.Thread(target=_loop, daemon=True, name="afl-live")
    _thread.start()
    print("[afl-live] started (AFL API live tracking + auto-settlement)")


def run_once() -> dict:
    """Manual trigger: one cycle now (also used by the API endpoint)."""
    live = _cycle()
    return {"live": live}
