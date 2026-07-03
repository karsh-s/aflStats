"""
Scheduled AFL live-score fetcher — api-sports.io v1.

Budget: 100 requests / day (free plan).

Schedule (local time — adjust to your timezone):
  Sat/Sun  1pm–11pm  → every 6 min  (~100 calls over the window)
  Thu/Fri  7pm–11pm  → every 2 min  (~120 calls; budget guard kicks in)
  Thu/Fri  other hrs → every 20 min
  Mon–Wed  all day   → every 20 min

Each cycle costs 2 requests (today + tomorrow).
A budget guard stops fetching at MAX_DAY - RESERVE remaining.
The last successful payload is always served from cache when the limit is hit.
"""
from __future__ import annotations

import json
import threading
import time
import datetime
import requests
from pathlib import Path

API_KEY  = "53f2833b800214f2262e91c8a47a4bd4"
BASE_URL = "https://v1.afl.api-sports.io"
HEADERS  = {"x-apisports-key": API_KEY}
MAX_DAY  = 100
RESERVE  = 3   # always keep this many in reserve

CACHE_FILE = Path(__file__).parent / "data" / "live_cache.json"

# Optional callback invoked (in a daemon thread) when games transition to FT.
# Signature: cb(newly_finished: list[dict]) -> None
_on_ft_cb: "Callable | None" = None

def set_on_games_finished(cb: "Callable") -> None:
    """Register a callback to fire when live games transition to FT status."""
    global _on_ft_cb
    _on_ft_cb = cb


# ── Team name normalisation ──────────────────────────────────────────────────

_TEAM_MAP: dict[str, str] = {
    "Adelaide Crows":                "Adelaide",
    "Brisbane Lions":                "Brisbane Lions",
    "Carlton Blues":                 "Carlton",
    "Collingwood Magpies":           "Collingwood",
    "Essendon Bombers":              "Essendon",
    "Fremantle Dockers":             "Fremantle",
    "Geelong Cats":                  "Geelong Cats",
    "Gold Coast Suns":               "Gold Coast",
    "Greater Western Sydney Giants": "Greater Western Sydney",
    "Hawthorn Hawks":                "Hawthorn",
    "Melbourne Demons":              "Melbourne",
    "North Melbourne Kangaroos":     "North Melbourne",
    "Port Adelaide Power":           "Port Adelaide",
    "Richmond Tigers":               "Richmond",
    "St Kilda Saints":               "St Kilda",
    "Sydney Swans":                  "Sydney",
    "West Coast Eagles":             "West Coast",
    "Western Bulldogs":              "Western Bulldogs",
}


def _norm(name: str) -> str:
    return _TEAM_MAP.get(name, name)


# ── Cache I/O ────────────────────────────────────────────────────────────────

def load_cache() -> dict:
    try:
        if CACHE_FILE.exists():
            with open(CACHE_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {
        "games": [],
        "daily_used": 0,
        "reset_date": "",
        "last_updated": None,
        "last_fetch_ok": None,
    }


def save_cache(cache: dict) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def _refresh_daily(cache: dict) -> dict:
    today = datetime.date.today().isoformat()
    if cache.get("reset_date") != today:
        cache["daily_used"] = 0
        cache["reset_date"] = today
    return cache


def remaining(cache: dict) -> int:
    return max(0, MAX_DAY - cache.get("daily_used", 0))


# ── Schedule ─────────────────────────────────────────────────────────────────

def fetch_interval() -> int | None:
    """Seconds between fetches right now, or None if outside active window."""
    now = datetime.datetime.now()
    wd  = now.weekday()   # 0=Mon … 5=Sat, 6=Sun
    h   = now.hour

    if wd in (5, 6):          # Sat / Sun
        return (6 * 60) if (13 <= h < 23) else None
    if wd in (3, 4):          # Thu / Fri
        return (2 * 60) if (19 <= h < 23) else (20 * 60)
    return 20 * 60            # Mon – Wed, all day


# ── API call ─────────────────────────────────────────────────────────────────

def _api_get(path: str, params: dict) -> list | None:
    try:
        r = requests.get(
            f"{BASE_URL}/{path}",
            headers=HEADERS,
            params=params,
            timeout=12,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("errors"):
            print(f"[live] API error for {path}?{params}: {data['errors']}")
            return None
        return data.get("response")
    except Exception as e:
        print(f"[live] Request failed ({path}): {e}")
        return None


def _norm_game(g: dict) -> dict:
    home = g["teams"]["home"]["name"]
    away = g["teams"]["away"]["name"]
    sh   = g["scores"]["home"]
    sa   = g["scores"]["away"]
    return {
        "id":           g["game"]["id"],
        "date":         g["date"][:10],
        "time_utc":     g["date"],
        "venue":        g.get("venue", ""),
        "week":         g.get("week"),
        "status":       g["status"]["short"],   # NS / Q1 / Q2 / HT / Q3 / Q4 / OT / FT
        "status_long":  g["status"]["long"],
        "home":         _norm(home),
        "away":         _norm(away),
        "home_score":   sh["score"],
        "away_score":   sa["score"],
        "home_goals":   sh["goals"],
        "home_behinds": sh["behinds"],
        "away_goals":   sa["goals"],
        "away_behinds": sa["behinds"],
    }


# ── Fetch ────────────────────────────────────────────────────────────────────

def fetch_now() -> bool:
    """
    Fetch today + tomorrow from the API and merge into cache.
    Returns True on success, False if budget exhausted or API error.
    """
    cache = load_cache()
    _refresh_daily(cache)

    if remaining(cache) <= RESERVE:
        print(f"[live] Budget guard: {cache['daily_used']}/{MAX_DAY} used — serving cache")
        return False

    today    = datetime.date.today().isoformat()
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()

    new_games: list[dict] = []
    used = 0

    # Always fetch today
    resp = _api_get("games", {"date": today})
    used += 1
    if resp is not None:
        new_games.extend(_norm_game(g) for g in resp)

    # Fetch tomorrow if budget allows
    if remaining(cache) - used > RESERVE:
        resp2 = _api_get("games", {"date": tomorrow})
        used += 1
        if resp2 is not None:
            new_games.extend(_norm_game(g) for g in resp2)

    # Detect FT transitions before overwriting cache
    old_statuses = {g["id"]: g["status"] for g in cache.get("games", [])}

    # Merge: keep older cached dates, replace today/tomorrow
    fetched_dates = {today, tomorrow}
    old = [g for g in cache.get("games", []) if g["date"] not in fetched_dates]
    cache["games"] = old + new_games

    cache["daily_used"] += used
    now_iso = datetime.datetime.utcnow().isoformat()
    cache["last_updated"] = now_iso
    if resp is not None:
        cache["last_fetch_ok"] = now_iso

    save_cache(cache)
    print(f"[live] OK — {len(new_games)} games, +{used} req, total {cache['daily_used']}/{MAX_DAY}")

    # Fire callback for any game that just went to FT
    if _on_ft_cb is not None:
        live_statuses = {"Q1", "Q2", "HT", "Q3", "Q4", "OT", "BT"}
        newly_ft = [
            g for g in new_games
            if g["status"] == "FT" and old_statuses.get(g["id"]) in live_statuses
        ]
        if newly_ft:
            print(f"[live] {len(newly_ft)} game(s) just reached FT — triggering result check")
            threading.Thread(target=_on_ft_cb, args=(newly_ft,), daemon=True).start()

    return True


# ── Background scheduler ─────────────────────────────────────────────────────

def _scheduler_loop() -> None:
    last_fetch = 0.0
    while True:
        try:
            interval = fetch_interval()
            if interval is not None:
                elapsed = time.monotonic() - last_fetch
                if elapsed >= interval:
                    fetch_now()
                    last_fetch = time.monotonic()
        except Exception as e:
            print(f"[live] Scheduler error: {e}")
        time.sleep(30)   # wake every 30 s to check schedule


def start() -> None:
    """Start the background fetcher thread (call once at app startup)."""
    # Do an immediate fetch on startup so cache is warm
    threading.Thread(target=fetch_now, daemon=True).start()
    # Then start the scheduler loop
    threading.Thread(target=_scheduler_loop, daemon=True, name="live-fetcher").start()
    print("[live] Fetcher started")
