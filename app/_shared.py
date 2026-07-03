"""Shared, cached data-access and projection helpers for the Streamlit app.

All heavy objects (box scores, Elo ratings, the win model) are loaded once via
``st.cache_resource``; per-round/per-game computations are memoised with
``st.cache_data`` so the UI stays snappy across reruns. The pages stay thin and
import everything from here.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make ``import afl`` work when Streamlit runs pages from the app directory.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from afl import config, pipeline
from afl.data import squiggle, weather
from afl.features import build as build_mod
from afl.features import elo as elo_mod
from afl.features import h2h as h2h_mod
from afl.model import adjustments, player_elo, player_props, position_adjustment as pos_adj
from afl.model import margin_model as margin_mod, tactical as tactical_mod
from afl.odds import sgm, theoddsapi

START = config.DEFAULT_START_SEASON
RATED = player_elo.RATED_STATS


# ---------------------------------------------------------------------------
# Cached singletons
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner="Loading player box scores…")
def player_stats() -> pd.DataFrame:
    return pipeline.load_player_stats_enriched()


@st.cache_resource(show_spinner="Fitting player ratings…")
def elos() -> dict:
    return player_elo.fit_all(player_stats())


@st.cache_resource(show_spinner="Loading match history…")
def history(year: int) -> pd.DataFrame:
    return pipeline.load_games(START, year)


@st.cache_resource(show_spinner="Rating teams…")
def team_elo(year: int) -> elo_mod.TeamElo:
    _, elo = elo_mod.run(history(year))
    return elo


@st.cache_resource
def win_model():
    try:
        return pipeline.load_model()
    except FileNotFoundError:
        return None


@st.cache_resource
def margin_model():
    """Trained margin model, or None (expected_margin falls back to linear Elo)."""
    try:
        return margin_mod.MarginModel.load()
    except FileNotFoundError:
        return None


def _expected_margin(home: str, away: str, venue: str, when: str | None) -> float:
    """Predicted home margin for a fixture (game-script input)."""
    try:
        return margin_mod.expected_margin(
            margin_model(), team_elo(2026), history(2026), home, away, venue,
            pd.to_datetime(when) if when else pd.Timestamp.now())
    except Exception:
        return 0.0


@st.cache_data(ttl=3600)
def fixture_venues(year: int) -> dict:
    try:
        fx = squiggle.games(year)
    except Exception:
        return {}
    return {(g["hteam"], g["ateam"]): (g.get("venue", ""),
            g["date"].isoformat() if pd.notna(g["date"]) else "")
            for _, g in fx.iterrows()}


@st.cache_data(ttl=3600)
def next_round(year: int) -> int | None:
    """First round of the season that still has an unplayed game."""
    fx = squiggle.games(year)
    if fx.empty:
        return None
    incomplete = fx[fx["complete"] != 100]
    if incomplete.empty:
        return int(fx["round"].max())
    return int(incomplete["round"].min())


# ---------------------------------------------------------------------------
# Lineups & forecasts
# ---------------------------------------------------------------------------
def _forecast(venue: str, when: str | None):
    if not venue or not when:
        return None
    return weather.weather_for(venue, pd.to_datetime(when))


@st.cache_data(ttl=3600)
def last_lineup(team: str) -> list[str]:
    """Players who appeared in a team's most recent game (lineup proxy)."""
    ps = player_stats()
    tg = ps[ps["team"] == team]
    if tg.empty:
        return []
    last = tg["date"].max()
    return sorted(tg[tg["date"] == last]["player"].unique().tolist())


# ---------------------------------------------------------------------------
# Round predictions + key stats
# ---------------------------------------------------------------------------
@st.cache_data(ttl=1800)
def round_predictions(year: int, rnd: int) -> pd.DataFrame:
    fixtures = squiggle.upcoming(year, rnd)
    if fixtures.empty:
        return fixtures
    model = win_model()
    elo = team_elo(year)
    hist = history(year)
    adj = adjustments.current()
    if adj is not None:
        elo.hga = adj.home_ground_edge
    rows = []
    for _, g in fixtures.iterrows():
        home, away, venue = g["hteam"], g["ateam"], g.get("venue", "")
        feat = build_mod.feature_row_for_fixture(
            elo, hist, home, away, venue, g["date"], with_weather=True)
        p = (float(model.predict_proba(pd.DataFrame([feat]))[0])
             if model is not None else feat["elo_exp_home"])
        if adj is not None:
            p = adj.calibrate(p)
        h2h = h2h_mod.summary(hist, home, away, last=10)
        rows.append({
            "event": f"{home} v {away}",
            "home": home, "away": away, "venue": venue,
            "date": g["date"],
            "p_home": p, "p_away": 1 - p,
            "pick": home if p >= 0.5 else away,
            "elo_diff": feat["elo_diff"],
            "rain_mm": feat["rain_mm"], "wind_kmh": feat.get("wind_kmh", 0.0),
            "h2h": (f"{h2h.get(home + '_wins', 0)}-{h2h.get(away + '_wins', 0)}"
                    if h2h.get("meetings") else "—"),
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=1800)
def game_key_players(home: str, away: str, venue: str, when: str | None,
                     min_games: int = 5) -> dict:
    """Expected leading disposal-getter and goal-kicker for a fixture."""
    ps = player_stats()
    el = elos()
    forecast = _forecast(venue, when)
    pos_table = pos_adj.get_table(ps)
    # No legs here -> no absence inference; margin still drives game script.
    tact_ctx = tactical_mod.build_context(
        ps, home=home, away=away,
        exp_margin=_expected_margin(home, away, venue, when))
    disp, goals = [], []
    for team in (home, away):
        is_home = team == home
        opp = away if is_home else home
        for player in last_lineup(team):
            ph = ps[ps["player"] == player]
            if len(ph) < min_games:
                continue
            dp = player_props.project(ps, player, "disposals", opp, is_home,
                                      elo=el.get("disposals"), venue=venue,
                                      forecast=forecast, position_table=pos_table,
                                      tactical=tact_ctx)
            gp = player_props.project(ps, player, "goals", opp, is_home,
                                      elo=el.get("goals"), venue=venue,
                                      forecast=forecast, position_table=pos_table,
                                      tactical=tact_ctx)
            disp.append((player, team, dp.mean))
            goals.append((player, team, gp.mean))
    disp.sort(key=lambda x: -x[2])
    goals.sort(key=lambda x: -x[2])
    return {
        "top_disposals": disp[:3],
        "top_goals": goals[:3],
    }


# ---------------------------------------------------------------------------
# Per-game prop ladders (every integer milestone)
# ---------------------------------------------------------------------------
def _ladder_range(stat: str) -> range:
    return {"disposals": range(5, 41), "goals": range(1, 7),
            "tackles": range(1, 13)}.get(stat, range(1, 30))


@st.cache_data(ttl=1800, show_spinner="Projecting all player lines…")
def game_prop_ladders(event_id: str, home: str, away: str,
                      venue: str, when: str | None) -> pd.DataFrame:
    """Every integer "X+" line for every player with a SportsBet market, with the
    model's probability of hitting and SportsBet's odds where available."""
    ps = player_stats()
    el = elos()
    index = player_props.build_player_index(ps)
    forecast = _forecast(venue, when)
    pos_table = pos_adj.get_table(ps)

    legs = theoddsapi.milestone_legs(event_id)        # players & disposal odds
    tact_ctx = tactical_mod.build_context(
        ps, home=home, away=away, legs=legs if not legs.empty else None,
        exp_margin=_expected_margin(home, away, venue, when))
    # SportsBet odds keyed by (player_norm, stat, milestone-int) for merge.
    odds_lookup = {}
    players = set()
    for _, o in legs.iterrows():
        players.add(o["player"])
        odds_lookup[(player_props.canonical_name(o["player"]), o["stat"],
                     int(o["line"] + 0.5))] = o["price"]

    rows = []
    for disp_name in sorted(players):
        scraped = player_props.resolve_player(disp_name, index)
        if scraped is None:
            continue
        ph = ps[ps["player"] == scraped]
        if ph.empty:
            continue
        is_home = ph.sort_values("date")["team"].iloc[-1] == home
        opp = away if is_home else home
        canon = player_props.canonical_name(disp_name)
        for stat in RATED:
            proj = player_props.project(ps, scraped, stat, opp, is_home,
                                        elo=el.get(stat), venue=venue,
                                        forecast=forecast, position_table=pos_table,
                                        tactical=tact_ctx)
            for x in _ladder_range(stat):
                p = proj.prob_over(x - 0.5)
                if p < 0.02:
                    break
                rows.append({
                    "player": disp_name, "team": home if is_home else away,
                    "stat": stat, "milestone": f"{x}+",
                    "model_p": p,
                    "sb_odds": odds_lookup.get((canon, stat, x)),
                    "proj": round(proj.mean, 1),
                    "position_group": proj.components.get("position_group"),
                    "position_adj": proj.components.get("position_adj", 0.0),
                    "pace_adj": proj.components.get("pace_adj", 0.0),
                    "tagging_adj": proj.components.get("tagging_adj", 0.0),
                    "game_script": proj.components.get("game_script", 0.0),
                    "absence_adj": proj.components.get("absence_adj", 0.0),
                    "role_drift": proj.components.get("role_drift", 0.0),
                })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# SGM
# ---------------------------------------------------------------------------
@st.cache_data(ttl=1800, show_spinner="Pricing milestone legs…")
def priced_legs(event_id: str, home: str, away: str, venue: str,
                when: str | None, min_games: int = 8) -> pd.DataFrame:
    ps = player_stats()
    el = elos()
    forecast = _forecast(venue, when)
    legs = theoddsapi.milestone_legs(event_id)
    if legs.empty:
        return legs
    exp_margin = _expected_margin(home, away, venue, when)
    return sgm.attach_model_probs(legs, ps, el, venue=venue, forecast=forecast,
                                  home=home, away=away, min_games=min_games,
                                  exp_margin=exp_margin)


@st.cache_data(ttl=1800)
def upcoming_events() -> pd.DataFrame:
    ev = theoddsapi.list_events()
    if not ev.empty:
        ev = ev.sort_values("commence_time").reset_index(drop=True)
    return ev
