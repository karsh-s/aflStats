"""Client for The Odds API (https://the-odds-api.com/).

Why this and not Sportsbet directly: Sportsbet has no public API and scraping
it breaks their ToS and your IP. The Odds API is a licensed aggregator that
*includes* Australian books (Sportsbet, TAB, Pointsbet, Neds...) under the
``au`` region, so you still see Sportsbet's lines where they publish them.

Free tier ~500 requests/month, so every call is cached (see ``afl.http``).
Set ``ODDS_API_KEY`` in your environment / ``.env``.

Markets:
  * h2h, totals          -> the per-sport ``/odds`` endpoint
  * player props         -> per-event ``/events/{id}/odds`` endpoint
"""
from __future__ import annotations

import pandas as pd
import requests

from .. import config, http
from ..data.teams import normalise_team

BASE = "https://api.the-odds-api.com/v4"
SPORT = "aussierules_afl"

# Player-prop market keys supported by The Odds API for AFL.
# NB: "player_marks" is INVALID, but "player_marks_over" IS valid and gives
# the marks milestone ladder (see OVER_MARKETS below).
PLAYER_MARKETS = [
    "player_disposals",
    "player_goals",
    "player_goal_scorer_anytime",
    "player_tackles",
    "player_fantasy_points",
]
# Map an Odds-API market key onto our internal stat name.
MARKET_TO_STAT = {
    "player_disposals": "disposals",
    "player_goals": "goals",
    "player_goal_scorer_anytime": "goals",
    "player_tackles": "tackles",
}

# "X+" milestone ladders used for Same Game Multis. ``player_disposals_over``
# gives every integer disposal line (16+, 17+, ...); the *_alternate markets give
# goal/tackle milestones where SportsBet posts them.
# Verified against the live API (Aug 2026): *_over markets carry the full
# milestone ladders for disposals, MARKS and TACKLES. The older
# *_alternate keys return zero outcomes and are kept only so goal
# milestones are picked up if/when SportsBet posts them (goal markets
# usually appear closer to bounce).
OVER_MARKETS = [
    "player_disposals_over",
    "player_marks_over",
    "player_tackles_over",
    "player_goals_alternate",
    "player_goal_scorer_anytime",
]
OVER_MARKET_TO_STAT = {
    "player_disposals_over": "disposals",
    "player_marks_over": "marks",
    "player_tackles_over": "tackles",
    "player_goals_alternate": "goals",
    "player_goal_scorer_anytime": "goals",
}
_STAT_ABBR = {"disposals": "disp", "goals": "goals", "tackles": "tack",
              "marks": "marks"}


class OddsAPIError(RuntimeError):
    pass


def _require_key() -> str:
    if not config.ODDS_API_KEY:
        raise OddsAPIError(
            "ODDS_API_KEY is not set. Get a free key at https://the-odds-api.com/ "
            "and add it to your .env (ODDS_API_KEY=...).")
    return config.ODDS_API_KEY


def _get(path: str, params: dict, *, ttl: int | None = None):
    params = {"apiKey": _require_key(), **params}
    # 10-min cache for player markets so dropped players clear quickly before game time.
    return http.get_json(f"{BASE}{path}", params=params,
                         ttl=10 * 60 if ttl is None else ttl)


def list_events() -> pd.DataFrame:
    """Upcoming AFL fixtures known to the odds feed (id, teams, commence time)."""
    data = _get(f"/sports/{SPORT}/events", {})
    df = pd.DataFrame(data)
    if not df.empty:
        df["commence_time"] = pd.to_datetime(df["commence_time"])
        df["home_team"] = df["home_team"].map(normalise_team)
        df["away_team"] = df["away_team"].map(normalise_team)
    return df


def event_h2h(event_id: str, *, bookmaker: str = "sportsbet") -> dict:
    """Head-to-head prices for one fixture: {team_name: decimal_odds}."""
    data = _event_odds(event_id, ["h2h"])
    out: dict[str, float] = {}
    for bk in data.get("bookmakers", []):
        if bookmaker and bk.get("key") != bookmaker:
            continue
        for mk in bk.get("markets", []):
            if mk.get("key") != "h2h":
                continue
            for oc in mk.get("outcomes", []):
                out[normalise_team(oc["name"])] = float(oc["price"])
    return out


def h2h_odds(markets: str = "h2h,totals") -> pd.DataFrame:
    """Head-to-head (and totals) odds across AU books, one row per outcome."""
    data = _get(f"/sports/{SPORT}/odds", {
        "regions": config.ODDS_API_REGION,
        "markets": markets,
        "oddsFormat": "decimal",
    })
    rows = []
    for ev in data:
        for bk in ev.get("bookmakers", []):
            for mk in bk.get("markets", []):
                for oc in mk.get("outcomes", []):
                    # For h2h the outcome name is a club; normalise it too so
                    # it matches the (normalised) home/away team names.
                    outcome = oc["name"]
                    if mk["key"] == "h2h":
                        outcome = normalise_team(outcome)
                    rows.append({
                        "event_id": ev["id"],
                        "commence_time": ev["commence_time"],
                        "home_team": normalise_team(ev.get("home_team")),
                        "away_team": normalise_team(ev.get("away_team")),
                        "bookmaker": bk["title"],
                        "market": mk["key"],
                        "outcome": outcome,
                        "point": oc.get("point"),
                        "price": oc["price"],
                    })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["commence_time"] = pd.to_datetime(df["commence_time"])
    return df


def _event_odds(event_id: str, markets: list[str]) -> dict:
    """Fetch event odds; if a market is rejected (422) retry per-market and skip
    the offending one so one bad key never kills the whole request."""
    path = f"/sports/{SPORT}/events/{event_id}/odds"
    base = {"regions": config.ODDS_API_REGION, "oddsFormat": "decimal"}
    try:
        return _get(path, {**base, "markets": ",".join(markets)})
    except requests.HTTPError as exc:
        if getattr(exc.response, "status_code", None) != 422:
            raise
    merged: dict = {}
    for mk in markets:
        try:
            data = _get(path, {**base, "markets": mk})
        except requests.HTTPError:
            continue  # invalid/unavailable market for this sport
        if not merged:
            merged = {k: v for k, v in data.items() if k != "bookmakers"}
            merged["bookmakers"] = []
        merged["bookmakers"].extend(data.get("bookmakers", []))
    return merged


def player_prop_odds(event_id: str,
                     markets: list[str] | None = None) -> pd.DataFrame:
    """Player-prop odds for one fixture, one row per (player, line, book, side)."""
    markets = markets or PLAYER_MARKETS
    data = _event_odds(event_id, markets)
    rows = []
    for bk in data.get("bookmakers", []):
        for mk in bk.get("markets", []):
            for oc in mk.get("outcomes", []):
                rows.append({
                    "event_id": event_id,
                    "home_team": normalise_team(data.get("home_team")),
                    "away_team": normalise_team(data.get("away_team")),
                    "bookmaker": bk["title"],
                    "market": mk["key"],
                    "stat": MARKET_TO_STAT.get(mk["key"], mk["key"]),
                    "player": oc.get("description") or oc.get("name"),
                    "side": oc.get("name"),       # "Over" / "Under" / "Yes"
                    "line": oc.get("point"),
                    "price": oc["price"],
                })
    return pd.DataFrame(rows)


def milestone_legs(event_id: str, *, bookmaker: str = "sportsbet",
                   markets: list[str] | None = None) -> pd.DataFrame:
    """Every "X+" milestone leg for one fixture from a single book (for SGMs).

    Each row is a leg: hitting ``milestone`` (e.g. "24+ disp") at decimal
    ``price``. ``line`` is the over threshold (X-0.5) the model probability is
    read off. Defaults to SportsBet, since Same Game Multis are book-specific.
    """
    markets = markets or OVER_MARKETS
    data = _event_odds(event_id, markets)
    home = normalise_team(data.get("home_team"))
    away = normalise_team(data.get("away_team"))
    rows = []
    for bk in data.get("bookmakers", []):
        if bookmaker and bk.get("key") != bookmaker:
            continue
        for mk in bk.get("markets", []):
            stat = OVER_MARKET_TO_STAT.get(mk["key"])
            if stat is None:
                continue
            for oc in mk.get("outcomes", []):
                side = oc.get("name")
                if mk["key"] == "player_goal_scorer_anytime":
                    if side != "Yes":
                        continue
                    line, milestone = 0.5, "1+ goal"
                else:
                    if side != "Over" or oc.get("point") is None:
                        continue
                    line = oc["point"]
                    milestone = f"{int(line + 0.5)}+ {_STAT_ABBR.get(stat, stat)}"
                rows.append({
                    "event_id": event_id, "home": home, "away": away,
                    "bookmaker": bk["title"], "market": mk["key"], "stat": stat,
                    "player": oc.get("description") or oc.get("name"),
                    "line": float(line), "milestone": milestone,
                    "price": float(oc["price"]),
                })
    return pd.DataFrame(rows)
