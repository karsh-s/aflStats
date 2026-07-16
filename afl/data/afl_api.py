"""AFL official (Champion Data) API client — live match player stats.

The same upstream AFL Paradise uses: afl.com.au's public web APIs.

  1. POST api.afl.com.au/cfs/afl/WMCTok               -> short-lived media token
  2. GET  aflapi.afl.com.au/afl/v2/...                -> seasons / matches
  3. GET  api.afl.com.au/cfs/afl/playerStats/match/…  -> per-player stats,
          live during games and final after (disposals, goals, marks, …)

Notes: these are the endpoints every afl.com.au visitor's browser calls; the
token response carries a Telstra copyright disclaimer — data is used here for
personal tracking only, not republication. Requests are polite (cached token,
modest polling intervals set by the caller).
"""
from __future__ import annotations

import time
from typing import Any

import requests

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_HEADERS = {"User-Agent": _UA, "Accept": "application/json"}

TOKEN_URL = "https://api.afl.com.au/cfs/afl/WMCTok"
MATCHES_URL = "https://aflapi.afl.com.au/afl/v2/matches"
COMPSEASONS_URL = "https://aflapi.afl.com.au/afl/v2/competitions/1/compseasons"
PLAYER_STATS_URL = "https://api.afl.com.au/cfs/afl/playerStats/match/{pid}"

# AFL API team names -> our squiggle/afltables names
TEAM_NORM = {
    "Geelong Cats": "Geelong",
    "GWS GIANTS": "GWS",
    "Gold Coast SUNS": "Gold Coast",
    "Sydney Swans": "Sydney",
    "West Coast Eagles": "West Coast",
    "Adelaide Crows": "Adelaide",
    "Narrm": "Melbourne",           # Indigenous-round names
    "Euro-Yroke": "St Kilda",
    "Kuwarna": "Adelaide",
    "Waalitj Marawar": "West Coast",
    "Yartapuulti": "Port Adelaide",
    "Walyalup": "Fremantle",
}

_token_cache: dict = {"token": None, "ts": 0.0}
_season_cache: dict = {}


def _norm_team(name: str) -> str:
    return TEAM_NORM.get(str(name), str(name))


def _token(max_retries: int = 4) -> str | None:
    """Fetch (and cache for 10 min) the public media token."""
    now = time.time()
    if _token_cache["token"] and now - _token_cache["ts"] < 600:
        return _token_cache["token"]
    for i in range(max_retries):
        try:
            r = requests.post(
                TOKEN_URL, timeout=15,
                headers={**_HEADERS, "Origin": "https://www.afl.com.au",
                         "Referer": "https://www.afl.com.au/"})
            if r.ok and "json" in r.headers.get("content-type", ""):
                _token_cache.update(token=r.json().get("token"), ts=now)
                return _token_cache["token"]
        except requests.RequestException:
            pass
        time.sleep(1.5 * (i + 1))
    return None


def _get_json(url: str, *, params: dict | None = None,
              extra_headers: dict | None = None,
              max_retries: int = 3) -> Any | None:
    headers = {**_HEADERS, **(extra_headers or {})}
    for i in range(max_retries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=20)
            if r.ok and "json" in r.headers.get("content-type", ""):
                return r.json()
        except requests.RequestException:
            pass
        time.sleep(1.0 * (i + 1))
    return None


def current_season() -> dict | None:
    """{'id': 85, 'currentRoundNumber': 19, ...} for the current premiership."""
    if _season_cache.get("season") and time.time() - _season_cache.get("ts", 0) < 6 * 3600:
        return _season_cache["season"]
    d = _get_json(COMPSEASONS_URL, params={"pageSize": 3})
    if not d:
        return None
    seasons = d.get("compSeasons", [])
    if not seasons:
        return None
    _season_cache.update(season=seasons[0], ts=time.time())
    return seasons[0]


def round_matches(comp_season_id: int, round_number: int | None = None) -> list[dict]:
    """Matches with providerId, status, normalised team names, start time."""
    params: dict = {"compSeasonId": comp_season_id, "pageSize": 20}
    if round_number is not None:
        params["roundNumber"] = round_number
    d = _get_json(MATCHES_URL, params=params)
    if not d:
        return []
    out = []
    for m in d.get("matches", []):
        out.append({
            "provider_id": m.get("providerId"),
            "status": m.get("status"),
            "utc_start": m.get("utcStartTime"),
            "home": _norm_team(m.get("home", {}).get("team", {}).get("name")),
            "away": _norm_team(m.get("away", {}).get("team", {}).get("name")),
            "round": (m.get("round") or {}).get("roundNumber"),
        })
    return out


# Match statuses that mean "in progress" / "finished"
LIVE_STATUSES = {"LIVE", "INPROGRESS", "IN_PROGRESS", "HALFTIME", "QUARTERTIME"}
DONE_STATUSES = {"CONCLUDED", "COMPLETED", "POSTGAME", "FULLTIME", "MATCH_ENDED"}

STAT_KEYS = ["disposals", "goals", "marks", "tackles", "hitouts", "kicks",
             "handballs", "clearances", "behinds"]


def match_player_stats(provider_id: str) -> dict | None:
    """Per-player stats for a match (live during play, final after).

    Returns {"players": [{"name": "First Last", "team": str,
                          "disposals": float, "goals": float, ...}, ...]}
    or None when unavailable.
    """
    tok = _token()
    if not tok:
        return None
    d = _get_json(PLAYER_STATS_URL.format(pid=provider_id),
                  extra_headers={"x-media-mis-token": tok})
    if not d:
        return None
    players = []
    for side in ("homeTeamPlayerStats", "awayTeamPlayerStats"):
        for entry in d.get(side, []) or []:
            try:
                pname = entry["player"]["player"]["player"]["playerName"]
                name = f"{pname.get('givenName', '')} {pname.get('surname', '')}".strip()
                stats = entry.get("playerStats", {}).get("stats", {}) or {}
                row = {"name": name, "side": "home" if side.startswith("home") else "away"}
                for k in STAT_KEYS:
                    v = stats.get(k)
                    if isinstance(v, dict):   # e.g. clearances -> totalClearances
                        v = v.get(f"total{k[0].upper()}{k[1:]}")
                    try:
                        row[k] = float(v) if v is not None else None
                    except (TypeError, ValueError):
                        row[k] = None
                players.append(row)
            except (KeyError, TypeError):
                continue
    return {"players": players} if players else None
