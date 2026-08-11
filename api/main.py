"""AFL Predictor — FastAPI JSON backend.

Exposes the existing model/data layer as REST endpoints consumed by the
React frontend. Run with:
    .venv/bin/uvicorn api.main:app --reload --port 8001
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))   # so _shared can import afl.*

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# Reuse the shared helpers from the Streamlit app – they already cache.
# We need to replace st.cache_* with plain functions, so we monkey-patch
# Streamlit's cache decorators before importing _shared.
import types, functools

class _FakeStreamlit:
    """Minimal stub that lets _shared.py import without a real Streamlit session."""
    def cache_resource(self, *a, **kw):
        def decorator(fn): return fn
        return decorator if not a else decorator(a[0])
    def cache_data(self, *a, **kw):
        def decorator(fn):
            return functools.lru_cache(maxsize=None)(fn)
        return decorator if not a else decorator(a[0])
    def cache_resource(self, *a, show_spinner=None, **kw):
        def decorator(fn): return fn
        return decorator if not a else decorator(a[0])
    def cache_data(self, *a, ttl=None, show_spinner=None, **kw):
        def decorator(fn):
            return functools.lru_cache(maxsize=256)(fn)
        return decorator if not a else decorator(a[0])

sys.modules["streamlit"] = _FakeStreamlit()  # type: ignore
import streamlit as _st_alias
# patch instance methods so @st.cache_resource works
_st_inst = _FakeStreamlit()
sys.modules["streamlit"] = _st_inst  # type: ignore

import threading, time as _time
import _shared as sh
from api import live_fetcher as _live
import api.analysis as _analysis
from afl.odds import value as val_mod
from afl.model.player_props import canonical_name
from afl.model import position_adjustment as _pos_adj

# Analysis results cached at startup (expensive compute, rarely changes)
_analysis_cache: dict = {}

app = FastAPI(title="AFL Predictor API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Module-level result cache so repeated browser refreshes are instant.
_value_cache: dict = {"data": None, "expires": 0.0}
_VALUE_TTL = 600   # 10 minutes

def _prewarm() -> None:
    """Pre-warm all lru_cache'd functions so the first browser request is fast.

    Runs in a background thread at startup. Warms:
      - round_predictions (team win model)
      - game_key_players  (top disposal/goal getter projections)
      - game_prop_ladders (full player × milestone prop ladder)
    All three are lru_cache'd so subsequent calls cost ~0ms.
    """
    try:
        year = 2026
        ev = sh.upcoming_events()
        if ev.empty:
            return
        venues = sh.fixture_venues(2026)
        nr = sh.next_round(year)
        if nr:
            sh.round_predictions(year, int(nr))   # warms team win model
        for _, erow in ev.iterrows():
            home, away = erow["home_team"], erow["away_team"]
            venue, when = venues.get((home, away), ("", None))
            try:
                sh.game_key_players(home, away, venue, when)
            except Exception:
                pass
            try:
                sh.game_prop_ladders(str(erow["id"]), home, away, venue, when)
            except Exception:
                pass
        print("[api] Cache pre-warm complete.")
    except Exception as e:
        print(f"[api] Pre-warm error: {e}")

def _on_live_games_finished(games: list[dict]) -> None:
    """Triggered by live_fetcher when any game transitions to FT status."""
    names = ", ".join(f"{g['home']} v {g['away']}" for g in games)
    print(f"[auto-check] Games finished: {names}")
    try:
        result = _run_check_results()
        print(f"[auto-check] Updated {result['updated']} bet(s)")
    except Exception as e:
        print(f"[auto-check] Error: {e}")


def _auto_check_loop() -> None:
    """Background loop: re-check pending bets every 30 min after game windows.

    Catches cases where stats are scraped hours after games end (common on game day).
    Runs indefinitely — the result-checker is a no-op when no pending bets exist.
    """
    while True:
        _time.sleep(30 * 60)
        try:
            data = _load_tracker()
            has_pending = any(b.get("status") == "pending" for b in data.get("bets", []))
            if has_pending:
                result = _run_check_results()
                if result["updated"]:
                    print(f"[auto-check-loop] Resolved {result['updated']} bet(s)")
        except Exception as e:
            print(f"[auto-check-loop] Error: {e}")


@app.on_event("startup")
def startup_event():
    threading.Thread(target=_prewarm, daemon=True).start()
    _live.set_on_games_finished(_on_live_games_finished)
    _live.start()
    threading.Thread(target=_auto_check_loop, daemon=True, name="auto-check").start()
    # AFL official API: live per-leg disposal tracking + automatic settlement
    from api import afl_live as _afl_live
    _afl_live.start()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe(v: Any) -> Any:
    """Convert NaN / Inf / numpy scalar → plain Python type safe for JSON."""
    if v is None:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        v = float(v)
    if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
        return None
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    return v


def _row(d: dict) -> dict:
    return {k: _safe(v) for k, v in d.items()}


# Short names used by upcoming_events → full names used by round_predictions
_TEAM_NORM: dict[str, str] = {
    "GWS": "Greater Western Sydney",
    "Brisbane": "Brisbane Lions",
    "North Melb.": "North Melbourne",
}

def _norm(name: str) -> str:
    return _TEAM_NORM.get(name, name)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@app.get("/api/events")
def list_events():
    """Upcoming AFL games with win probabilities, venue and weather."""
    ev = sh.upcoming_events()
    if ev.empty:
        return []

    year = 2026
    try:
        nr = sh.next_round(year)
    except Exception:
        nr = None

    venues = sh.fixture_venues(year)

    results = []
    for _, row in ev.iterrows():
        home = row["home_team"]
        away = row["away_team"]
        commence = pd.to_datetime(row["commence_time"])
        venue, when = venues.get((home, away), ("", None))

        # Win prediction
        try:
            preds = sh.round_predictions(year, int(nr) if nr else 1)
            match = preds[(preds["home"] == _norm(home)) & (preds["away"] == _norm(away))]
            if not match.empty:
                p_home = float(match.iloc[0]["p_home"])
                rain_mm = _safe(match.iloc[0].get("rain_mm"))
                wind_kmh = _safe(match.iloc[0].get("wind_kmh"))
                h2h = match.iloc[0].get("h2h", "—")
            else:
                p_home = 0.5
                rain_mm = None
                wind_kmh = None
                h2h = "—"
        except Exception:
            p_home = 0.5
            rain_mm = None
            wind_kmh = None
            h2h = "—"

        # Key players
        try:
            kp = sh.game_key_players(home, away, venue, when)
            top_disposals = [[n, t, round(v, 1)] for n, t, v in kp["top_disposals"]]
            top_goals = [[n, t, round(v, 2)] for n, t, v in kp["top_goals"]]
        except Exception:
            top_disposals = []
            top_goals = []

        results.append({
            "id": str(row["id"]),
            "home": home,
            "away": away,
            "venue": venue or "TBC",
            "commence_time": commence.isoformat(),
            "slot": commence.strftime("%a %d %b, %I:%M %p"),
            "p_home": round(p_home, 3),
            "p_away": round(1 - p_home, 3),
            "pick": home if p_home >= 0.5 else away,
            "rain_mm": rain_mm,
            "wind_kmh": wind_kmh,
            "h2h": h2h,
            "top_disposals": top_disposals,
            "top_goals": top_goals,
        })

    return results


# ---------------------------------------------------------------------------
# Round predictions (standalone, no odds feed needed)
# ---------------------------------------------------------------------------

@app.get("/api/round/{year}/{rnd}")
def round_predictions(year: int, rnd: int):
    try:
        preds = sh.round_predictions(year, rnd)
    except Exception as e:
        raise HTTPException(500, str(e))
    if preds.empty:
        return []
    return [_row(r) for r in preds.to_dict("records")]


# ---------------------------------------------------------------------------
# Game props — every player × every milestone
# ---------------------------------------------------------------------------

@app.get("/api/game/{event_id}/props")
def game_props(event_id: str):
    """Full prop ladder for every player in the event."""
    ev = sh.upcoming_events()
    if ev.empty:
        raise HTTPException(404, "No upcoming events")
    row = ev[ev["id"] == event_id]
    if row.empty:
        raise HTTPException(404, f"Event {event_id} not found")
    row = row.iloc[0]
    home, away = row["home_team"], row["away_team"]
    venue, when = sh.fixture_venues(2026).get((home, away), ("", None))

    try:
        ladders = sh.game_prop_ladders(event_id, home, away, venue, when)
    except Exception as e:
        raise HTTPException(500, str(e))

    if ladders.empty:
        return []

    # Add value metrics where we have SB odds
    rows = []
    for _, r in ladders.iterrows():
        rec = _row(r.to_dict())
        if rec.get("sb_odds") and rec["sb_odds"] > 1:
            try:
                vm = val_mod.evaluate_market(float(rec["model_p"]), float(rec["sb_odds"]))
                rec["edge"] = _safe(vm.get("edge"))
                rec["ev"] = _safe(vm.get("ev_per_unit"))
                rec["kelly"] = _safe(vm.get("kelly_stake"))
                rec["implied_p"] = _safe(vm.get("book_implied"))
            except Exception:
                rec["edge"] = None
                rec["ev"] = None
                rec["kelly"] = None
                rec["implied_p"] = None
        else:
            rec["edge"] = None
            rec["ev"] = None
            rec["kelly"] = None
            rec["implied_p"] = None
        rows.append(rec)

    return rows


# ---------------------------------------------------------------------------
# SGM legs — priced legs for multi builder
# ---------------------------------------------------------------------------

@app.get("/api/game/{event_id}/sgm")
def game_sgm_legs(event_id: str):
    ev = sh.upcoming_events()
    if ev.empty:
        raise HTTPException(404, "No upcoming events")
    row = ev[ev["id"] == event_id]
    if row.empty:
        raise HTTPException(404, f"Event {event_id} not found")
    row = row.iloc[0]
    home, away = row["home_team"], row["away_team"]
    venue, when = sh.fixture_venues(2026).get((home, away), ("", None))

    try:
        legs = sh.priced_legs(event_id, home, away, venue, when)
    except Exception as e:
        raise HTTPException(500, str(e))

    if legs.empty:
        return []

    return [_row(r) for r in legs.to_dict("records")]


def _multi_reasons(legs: list[dict], home: str, away: str,
                   exp_margin: float | None, ps, team_of: dict) -> list[str]:
    """Human-readable tactical reasoning for why these legs were targeted."""
    from afl.model import game_roles, pace_pressure
    reasons: list[str] = []

    try:
        if "role_leaks" not in _analysis_cache:
            _analysis_cache["role_leaks"] = _analysis.role_leaks()
        rl = _analysis_cache["role_leaks"]
    except Exception:
        rl = None
    leak_by_team: dict = {}
    if rl and rl.get("available"):
        for t in rl["teams"]:
            leak_by_team[t["team"]] = {r["role"]: r["vs_league"] for r in t["roles"]}

    role_tbl = game_roles.get_table(ps)
    pace_tbl = pace_pressure.get_table(ps)

    if exp_margin is not None and abs(exp_margin) >= 12:
        fav = home if exp_margin > 0 else away
        reasons.append(
            f"Game script: model projects {fav} by ~{abs(exp_margin):.0f} pts — "
            f"a side in control accumulates more uncontested ball")

    seen_opp: set = set()
    seen_leak: set = set()
    for leg in legs:
        p = leg.get("player_scraped") or leg.get("player")
        team = team_of.get(p)
        if team is None:
            continue
        opp = away if team == home else home

        # Opponent style (once per opposing team)
        if pace_tbl is not None and opp not in seen_opp:
            zp = pace_tbl.z_pace.get(opp, 0.0)
            zt = pace_tbl.z_press.get(opp, 0.0)
            if zp >= 0.6:
                reasons.append(
                    f"{opp} concede well above league-average disposals over "
                    f"their last 10 — lifts every {team} ball-winner")
            if zt <= -0.8:
                reasons.append(
                    f"{opp} apply the least tackle pressure in the league — "
                    f"uncontested accumulators run free")
            seen_opp.add(opp)

        # Role leak (once per opponent x role)
        role = role_tbl.current_role.get(p) if role_tbl else None
        if role:
            leak = leak_by_team.get(opp, {}).get(role)
            if leak is not None and leak >= 0.8 and (opp, role) not in seen_leak:
                names = ", ".join(
                    str(l.get("player")) for l in legs
                    if role_tbl.current_role.get(
                        l.get("player_scraped") or l.get("player")) == role
                    and team_of.get(l.get("player_scraped") or l.get("player")) == team)
                reasons.append(
                    f"{opp} leak +{leak:.1f} disposals/game to {role}s "
                    f"(worst-{'1' if leak >= 2 else 'few'} in the league) — {names}")
                seen_leak.add((opp, role))

        # Model-vs-market gap on the specific line
        prob, odds = leg.get("prob"), leg.get("odds")
        if prob and odds and prob - 1.0 / odds >= 0.10:
            reasons.append(
                f"{leg.get('player')} {leg.get('milestone')}: model {prob:.0%} "
                f"vs market {1/odds:.0%} — his recent output clears this line "
                f"more often than it is priced")

    # Dedupe, keep order, cap
    out, seen = [], set()
    for r in reasons:
        if r not in seen:
            out.append(r)
            seen.add(r)
    out = out[:5]
    out.append("Hit P estimated from 10,000 correlated game simulations "
               "(measured within-game correlation, exact player distributions)")
    return out


@app.get("/api/game/{event_id}/multis")
def game_target_multis(event_id: str,
                       targets: str = "1.5,2,2.5,3,4,5,7.5,10,15,20",
                       floor: float = 0.60):
    """Safest multi per target multiplier — exact DP, unlimited legs, all
    stat lines. Maximises joint probability (per-leg risk-discounted) subject
    to combined odds >= target; with odds pinned at the target this is also
    the greatest-edge combination.

    ``floor``: minimum model probability per leg. Raising it (e.g. 0.70)
    forces high-edge players onto their SAFER lines and fills the multiplier
    with more legs — spreads model risk at a small joint-probability cost."""
    from afl.odds import sgm as _sgm
    ev = sh.upcoming_events()
    if ev.empty:
        raise HTTPException(404, "No upcoming events")
    row = ev[ev["id"] == event_id]
    if row.empty:
        raise HTTPException(404, f"Event {event_id} not found")
    row = row.iloc[0]
    home, away = row["home_team"], row["away_team"]
    venue, when = sh.fixture_venues(2026).get((home, away), ("", None))

    try:
        legs = sh.priced_legs(event_id, home, away, venue, when)
    except Exception as e:
        raise HTTPException(500, str(e))
    if legs.empty:
        return []

    ps = sh.player_stats()
    team_of = ps.sort_values("date").groupby("player")["team"].last().to_dict()
    exp_margin = sh._expected_margin(home, away, venue, when)

    out = []
    for t in targets.split(","):
        try:
            target = float(t)
        except ValueError:
            continue
        # Long-shot targets need a lower floor and more legs to be reachable.
        f = floor if target <= 5 else (floor - 0.05 if target <= 10 else floor - 0.12)
        cap = MAX_TARGET_LEGS if target <= 5 else (7 if target <= 10 else 8)
        res = _sgm.safest_multi(legs, target, prob_floor=max(0.40, f),
                                max_legs=cap, max_per_stat=MAX_PER_STAT)
        if res is None:
            out.append({"target": target, "result": None})
            continue
        out.append({
            "target": target,
            "result": {
                "legs": [_row(l) for l in res["legs"]],
                "combined_odds": round(res["combined_odds"], 3),
                "joint_prob": round(res["joint_prob"], 4),
                "joint_prob_indep": round(res.get("joint_prob_indep",
                                                  res["joint_prob"]), 4),
                "implied_prob": round(res["implied_prob"], 4),
                "edge": round(res["edge"], 4),
                "n_legs": res["n_legs"],
                "reasons": _multi_reasons(res["legs"], home, away,
                                          exp_margin, ps, team_of),
            },
        })
    return out


# ---------------------------------------------------------------------------
# Consistency helpers
# ---------------------------------------------------------------------------

def _parse_line(milestone: str) -> float | None:
    """'31+' -> 31.0, '2+' -> 2.0, None if unparseable."""
    try:
        return float(str(milestone).rstrip("+").strip())
    except (ValueError, TypeError):
        return None


def _build_canon_index(ps: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Pre-group player_stats by canonical name for O(1) lookup.

    Built once per request and passed to _consistency() so we never call
    canonical_name() across all 44k rows per player.
    """
    groups: dict[str, pd.DataFrame] = {}
    for afl_name, grp in ps.groupby("player", sort=False):
        key = canonical_name(str(afl_name))
        groups[key] = grp.sort_values("date").reset_index(drop=True)
    return groups


def _consistency(canon_index: dict[str, pd.DataFrame], display_name: str,
                 stat: str, line_val: float, opponent: str,
                 n: int = 5) -> dict:
    """Return hit rates for last 5, last 10, and last n games vs opponent."""
    key = canonical_name(display_name)
    h = canon_index.get(key)
    if h is None or stat not in h.columns:
        return {"hit_last_5": None, "hit_last_10": None, "hit_vs_opp": None, "opp_n": 0}

    vals = h[stat].astype(float)

    last5 = vals.tail(5)
    hit_last5 = float((last5 >= line_val).sum()) / len(last5) if len(last5) else None

    last10 = vals.tail(10)
    hit_last10 = float((last10 >= line_val).sum()) / len(last10) if len(last10) else None

    vs = h[h["opponent"] == opponent][stat].astype(float).tail(n)
    hit_vs = float((vs >= line_val).sum()) / len(vs) if len(vs) else None

    return {"hit_last_5": hit_last5, "hit_last_10": hit_last10, "hit_vs_opp": hit_vs, "opp_n": int(len(vs))}


def _tier(hit_last_5, hit_vs_opp, opp_n) -> str:
    """Classify a bet into lock / strong / value."""
    l5 = hit_last_5 or 0
    vo = hit_vs_opp or 0
    # Lock: perfect in both windows (requires ≥3 opponent meetings for OPP signal to be meaningful)
    if l5 == 1.0 and vo == 1.0 and opp_n >= 3:
        return "lock"
    # Strong: hit 4+/5 recently, OR perfect vs opponent WITH at least 3/5 recent form
    if l5 >= 0.8 or (l5 >= 0.6 and vo == 1.0 and opp_n >= 3):
        return "strong"
    return "value"


# ---------------------------------------------------------------------------
# Value bets — one best line per player, with consistency signals
# ---------------------------------------------------------------------------

@app.get("/api/value")
def value_bets(min_edge: float = 0.04):
    """Best value line per player across all upcoming events."""
    # Return cached result if still fresh
    now = _time.monotonic()
    cached = _value_cache.get("data")
    if cached is not None and now < _value_cache["expires"]:
        return [r for r in cached if r["edge"] >= min_edge]

    ev = sh.upcoming_events()
    if ev.empty:
        return []

    venues = sh.fixture_venues(2026)
    ps = sh.player_stats()
    canon_index = _build_canon_index(ps)      # built once; O(1) lookup per player

    # Collect ALL value lines first (before dedup)
    raw_rows: list[dict] = []

    for _, erow in ev.iterrows():
        event_id = str(erow["id"])
        home, away = erow["home_team"], erow["away_team"]
        venue, when = venues.get((home, away), ("", None))
        game_label = f"{home} v {away}"

        try:
            ladders = sh.game_prop_ladders(event_id, home, away, venue, when)
        except Exception:
            continue
        if ladders.empty:
            continue

        for _, r in ladders.iterrows():
            sb = _safe(r.get("sb_odds"))
            if not sb or sb <= 1:
                continue
            mp = _safe(r["model_p"])
            if mp is None:
                continue
            odds = float(sb)
            try:
                vm = val_mod.evaluate_market(float(mp), odds)
            except Exception:
                continue
            edge_val = _safe(vm.get("edge"))
            if edge_val is None or edge_val < min_edge:
                continue

            player = str(r["player"])
            team = str(r["team"])
            stat = str(r["stat"])
            milestone = str(r["milestone"])
            # Which side of the matchup is the opponent?
            opponent = away if team in (home, team) else home
            # Resolve opponent from team membership
            try:
                h_hist = _player_history(ps, player)
                if not h_hist.empty:
                    last_team = h_hist.iloc[-1].get("team", "")
                    opponent = away if last_team == home or team == home else home
                else:
                    opponent = away if team == home else home
            except Exception:
                opponent = away if team == home else home

            raw_rows.append({
                "game": game_label,
                "event_id": event_id,
                "player": player,
                "team": team,
                "opponent": opponent,
                "stat": stat,
                "milestone": milestone,
                "model_p": float(mp),
                "sb_odds": float(odds),
                "implied_p": _safe(vm.get("book_implied")),
                "edge": float(edge_val),
                "ev": _safe(vm.get("ev_per_unit")),
                "kelly": _safe(vm.get("kelly_stake")),
                "proj": _safe(r.get("proj")),
            })

    # ---- Deduplicate: one best line per (event_id, player, stat) ----------
    from collections import defaultdict
    buckets: dict[tuple, list] = defaultdict(list)
    for row in raw_rows:
        key = (row["event_id"], row["player"], row["stat"])
        buckets[key].append(row)

    deduped: list[dict] = []
    for rows in buckets.values():
        # Prefer lines with model_p >= 0.50 (safer), then by highest edge
        safe = [r for r in rows if r["model_p"] >= 0.50]
        pool = safe if safe else rows
        best = max(pool, key=lambda r: r["edge"])
        deduped.append(best)

    # ---- Add consistency signals ------------------------------------------
    result: list[dict] = []
    for row in deduped:
        line_val = _parse_line(row["milestone"])
        if line_val is not None:
            cons = _consistency(canon_index, row["player"], row["stat"],
                                line_val, row["opponent"])
        else:
            cons = {"hit_last_5": None, "hit_last_10": None, "hit_vs_opp": None, "opp_n": 0}

        tier = _tier(cons["hit_last_5"], cons["hit_vs_opp"], cons["opp_n"])
        result.append({
            **{k: v for k, v in row.items() if k != "opponent"},
            "hit_last_5": cons["hit_last_5"],
            "hit_vs_opp": cons["hit_vs_opp"],
            "opp_n": cons["opp_n"],
            "tier": tier,
        })

    # ---- Sort: locks first, then strong, then value; within tier by edge ---
    tier_order = {"lock": 0, "strong": 1, "value": 2}
    result.sort(key=lambda r: (tier_order[r["tier"]], -r["edge"]))
    result = result[:80]

    # Store in module-level cache (min_edge=0 so any filter can be applied later)
    _value_cache["data"] = result
    _value_cache["expires"] = _time.monotonic() + _VALUE_TTL
    return [r for r in result if r["edge"] >= min_edge]


# ---------------------------------------------------------------------------
# Best lines per game — one line per player per stat, consistency-sorted
# ---------------------------------------------------------------------------

@app.get("/api/game/{event_id}/best-lines")
def game_best_lines(event_id: str):
    """One best line per (player, stat) sorted by hit consistency, then edge."""
    ev = sh.upcoming_events()
    if ev.empty:
        raise HTTPException(404, "No upcoming events")
    row = ev[ev["id"] == event_id]
    if row.empty:
        raise HTTPException(404, f"Event {event_id} not found")
    row = row.iloc[0]
    home, away = row["home_team"], row["away_team"]
    venue, when = sh.fixture_venues(2026).get((home, away), ("", None))

    try:
        ladders = sh.game_prop_ladders(event_id, home, away, venue, when)
    except Exception as e:
        raise HTTPException(500, str(e))

    if ladders.empty:
        return []

    ps = sh.player_stats()
    canon_index = _build_canon_index(ps)

    candidates: list[dict] = []
    for _, r in ladders.iterrows():
        # Must have SportsBet odds
        sb = _safe(r.get("sb_odds"))
        if not sb or float(sb) <= 1:
            continue

        mp = _safe(r.get("model_p"))
        if mp is None:
            continue

        player = str(r["player"])
        team = str(r["team"])
        stat = str(r["stat"])
        milestone = str(r["milestone"])
        line_val = _parse_line(milestone)
        proj = _safe(r.get("proj"))

        opponent = away if team == home else home

        # Compute value metrics
        try:
            vm = val_mod.evaluate_market(float(mp), float(sb))
            edge_val = _safe(vm.get("edge"))
            ev_val = _safe(vm.get("ev_per_unit"))
            kelly_val = _safe(vm.get("kelly_stake"))
            implied_p = _safe(vm.get("book_implied"))
        except Exception:
            edge_val = ev_val = kelly_val = implied_p = None

        # Compute consistency
        if line_val is not None:
            cons = _consistency(canon_index, player, stat, line_val, opponent)
        else:
            cons = {"hit_last_5": None, "hit_last_10": None, "hit_vs_opp": None, "opp_n": 0}

        l5 = cons["hit_last_5"]
        l10 = cons["hit_last_10"]
        vo = cons["hit_vs_opp"]

        # Inclusion filter: strong consistency AND meaningful edge
        # Consistency: 5/5 last 5  OR  8+/10 last 10  OR  5/5 vs opponent (≥3 meetings)
        # Edge: must have positive edge ≥ 2% (filters out 1.03-1.05 near-certainties with no value)
        consistent = (
            (l5 is not None and l5 == 1.0) or
            (l10 is not None and l10 >= 0.80) or
            (vo is not None and vo == 1.0 and cons["opp_n"] >= 3)
        )
        has_edge = edge_val is not None and edge_val >= 0.02
        if not (consistent and has_edge):
            continue

        tier = _tier(l5, vo, cons["opp_n"])

        candidates.append({
            "player": player,
            "team": team,
            "stat": stat,
            "milestone": milestone,
            "model_p": float(mp),
            "sb_odds": float(sb),
            "implied_p": implied_p,
            "edge": edge_val,
            "ev": ev_val,
            "kelly": kelly_val,
            "proj": proj,
            "hit_last_5": l5,
            "hit_last_10": l10,
            "hit_vs_opp": vo,
            "opp_n": cons["opp_n"],
            "tier": tier,
        })

    # Dedup: one line per (player, stat) — all candidates already pass consistency,
    # so pick the one with the best edge (most betting value)
    from collections import defaultdict
    buckets: dict[tuple, list] = defaultdict(list)
    for c in candidates:
        key = (c["player"], c["stat"])
        buckets[key].append(c)

    deduped: list[dict] = []
    for rows in buckets.values():
        best = max(rows, key=lambda r: r["edge"] if r["edge"] is not None else -1)
        deduped.append(best)

    # Sort: edge DESC (best value first), consistency as tiebreaker
    def _sort_key(r):
        return (
            -(r["edge"] if r["edge"] is not None else -1),
            -(r["hit_last_5"] if r["hit_last_5"] is not None else -1),
            -(r["hit_vs_opp"] if r["hit_vs_opp"] is not None else -1),
        )

    deduped.sort(key=_sort_key)

    # Take top 15 per stat so every stat category is represented, then re-sort
    STAT_LIMIT = 15
    per_stat: dict[str, list] = {}
    for r in deduped:
        stat = r["stat"]
        if stat not in per_stat:
            per_stat[stat] = []
        if len(per_stat[stat]) < STAT_LIMIT:
            per_stat[stat].append(r)

    capped: list[dict] = [r for rows in per_stat.values() for r in rows]
    capped.sort(key=_sort_key)  # re-apply edge-first sort after cross-stat merge

    return [_row(r) for r in capped]


# ---------------------------------------------------------------------------
# Multi Tracker — persistent $5-per-multi bet tracker
# ---------------------------------------------------------------------------

import json as _json
import uuid as _uuid
from datetime import datetime as _dt

TRACKER_FILE = ROOT / "api" / "data" / "multi_tracker.json"


def _load_tracker() -> dict:
    if not TRACKER_FILE.exists():
        return {"bets": []}
    with open(TRACKER_FILE) as f:
        return _json.load(f)


def _save_tracker(data: dict) -> None:
    TRACKER_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TRACKER_FILE, "w") as f:
        _json.dump(data, f, indent=2)


def _enrich_with_hit_rates(legs: list[dict], canon_index: dict,
                           home: str, away: str) -> list[dict]:
    """Attach empirical hit_last_5 / hit_last_10 to each leg dict.

    Uses player_scraped (the AFL-website-resolved name) for the index lookup
    so nickname variants like 'Zachary'/'Zach' match correctly.
    """
    enriched = []
    for leg in legs:
        opp = away if leg.get("team") == home else home
        # player_scraped is already resolved against the stats index; fall back
        # to the display name only if scraped name is absent.
        lookup = leg.get("player_scraped") or leg["player"]
        cons = _consistency(canon_index, lookup, leg["stat"],
                            float(leg.get("line", 0)), opp)
        enriched.append({**leg,
                         "hit_last_5":  cons["hit_last_5"],
                         "hit_last_10": cons["hit_last_10"]})
    return enriched


def _build_multi_py(legs: list[dict], target: float, max_legs: int = 8,
                    min_odds_floor: float | None = None,
                    min_hit5: float = 0.0) -> dict | None:
    """Build the safest multi reaching `target` odds from the leg pool.

    min_hit5: exclude legs where empirical last-5 hit rate < this value.
              Legs with no hit-rate data (None) are treated as 0.
    """
    if min_hit5 > 0:
        legs = [l for l in legs if (l.get("hit_last_5") or 0.0) >= min_hit5]
    min_odds = min_odds_floor if min_odds_floor else max(1.05, target ** (1 / max_legs))
    player_best: dict[str, dict] = {}
    for leg in legs:
        if leg["odds"] < min_odds:
            continue
        p = leg["player"]
        if p not in player_best or leg["prob"] > player_best[p]["prob"]:
            player_best[p] = leg
    pool = sorted(player_best.values(), key=lambda x: -x["prob"])
    if len(pool) < 2:
        return None
    picked: list[dict] = []
    combined_odds = 1.0
    for leg in pool:
        if len(picked) >= max_legs:
            break
        new_odds = combined_odds * leg["odds"]
        max_o = target * 1.7 if combined_odds >= target * 0.6 else target * 1.4
        if new_odds > max_o:
            continue
        picked.append(leg)
        combined_odds = new_odds
        if combined_odds >= target:
            break
    if len(picked) < 2:
        return None
    joint_prob = 1.0
    for l in picked:
        joint_prob *= l["prob"]
    return {"legs": picked, "combined_odds": round(combined_odds, 3),
            "joint_prob": round(joint_prob, 4)}


def _build_by_risk_py(legs: list[dict], min_prob: float, target: float,
                      min_odds: float, max_legs: int = 8,
                      min_hit5: float = 0.0) -> dict | None:
    filtered = [l for l in legs if l["prob"] >= min_prob]
    return _build_multi_py(filtered, target, max_legs, min_odds, min_hit5)


# Leg-count caps. Post-mortem R19: with calibrated (honest) leg probabilities
# the optimiser will happily stack 13 near-certainties to reach 10x, but every
# extra leg is another player who can be a late out, get tagged, or have a
# quiet day — risks the independence maths never sees.
MAX_TARGET_LEGS = 6
MAX_SAFE_LEGS = 5


# Cap on legs sharing one stat. Multis made entirely of disposal lines all
# move with the same thing (game tempo), so a slow game sinks every leg at
# once; mixing disposals/marks/tackles/goals/team spreads that risk.
MAX_PER_STAT = 3


def _safest_multi_py(legs: list[dict], target: float,
                     min_hit5: float = 0.0,
                     prob_floor: float = 0.30,
                     max_legs: int | None = None,
                     max_per_stat: int | None = MAX_PER_STAT) -> dict | None:
    """Exact safest multi for a target multiplier (no leg cap).

    Wraps sgm.safest_multi: maximise joint probability (with the per-leg risk
    discount deciding whether extra legs pay for themselves) subject to
    combined odds >= target, over ALL priced stat lines.
    ``prob_floor=0.70`` is SAFE mode: high-edge players on their safer lines,
    more legs to build the multiplier.
    """
    from afl.odds import sgm as _sgm
    if min_hit5 > 0:
        legs = [l for l in legs if (l.get("hit_last_5") or 0.0) >= min_hit5]
    if len(legs) < 2:
        return None
    df = pd.DataFrame(legs)
    if "player_scraped" not in df.columns:
        df["player_scraped"] = df["player"]
    res = _sgm.safest_multi(df, float(target), prob_floor=prob_floor,
                            max_legs=max_legs, max_per_stat=max_per_stat)
    if res is None:
        return None
    return {"legs": res["legs"],
            "combined_odds": round(res["combined_odds"], 3),
            "joint_prob": round(res["joint_prob"], 4),
            "edge": round(res["edge"], 4)}


# Thresholds per tier:
#   risk_low:  model prob ≥ 0.68 AND last-5 hit rate ≥ 60%  (3/5 recent games)
#   risk_med:  model prob ≥ 0.53 AND last-5 hit rate ≥ 40%  (2/5 recent games)
#   risk_high: model prob ≥ 0.30 AND last-5 hit rate ≥ 20%  (1/5 recent games)
#   targets:   exact DP (safest possible combo, unlimited legs, all stat lines);
#              last-5 hit rate ≥ 40% for ×2–×5; ≥ 20% for ×10
_MULTI_SPECS = [
    ("risk_low",  "LOW Risk ~2.5×",  lambda legs: _build_by_risk_py(legs, 0.68, 2.5,  1.15, 5,  0.60)),
    ("risk_med",  "MED Risk ~5×",    lambda legs: _build_by_risk_py(legs, 0.53, 5.0,  1.25, 7,  0.40)),
    ("risk_high", "HIGH Risk ~12×",  lambda legs: _build_by_risk_py(legs, 0.30, 12.0, 1.50, 10, 0.20)),
    # R18 post-mortem: legs priced 40-69% hit only 35-38% while legs >= 70%
    # tracked their claimed rates — so ALL target multis now require every leg
    # >= 70% model probability. SAFE variants additionally demand an
    # empirical streak (line hit in >= 3 of the player's last 5 games),
    # the bets.com.au-style anchor-leg rule.
    ("target_2",  "Target ~2×",      lambda legs: _safest_multi_py(legs, 2,  min_hit5=0.40, prob_floor=0.60, max_legs=MAX_TARGET_LEGS)),
    ("target_3",  "Target ~3×",      lambda legs: _safest_multi_py(legs, 3,  min_hit5=0.40, prob_floor=0.60, max_legs=MAX_TARGET_LEGS)),
    ("target_5",  "Target ~5×",      lambda legs: _safest_multi_py(legs, 5,  min_hit5=0.40, prob_floor=0.60, max_legs=MAX_TARGET_LEGS)),
    # 10x is inherently a long shot: no combination of >=60% legs reaches it
    # within the leg cap, so this tier keeps a lower floor by design.
    ("target_10", "Target ~10×",     lambda legs: _safest_multi_py(legs, 10, min_hit5=0.40, prob_floor=0.50, max_legs=7)),
    ("target_2_safe",  "Target ~2× SAFE",  lambda legs: _safest_multi_py(legs, 2,  min_hit5=0.60, prob_floor=0.68, max_legs=MAX_SAFE_LEGS)),
    ("target_3_safe",  "Target ~3× SAFE",  lambda legs: _safest_multi_py(legs, 3,  min_hit5=0.60, prob_floor=0.68, max_legs=MAX_SAFE_LEGS)),
    ("target_5_safe",  "Target ~5× SAFE",  lambda legs: _safest_multi_py(legs, 5,  min_hit5=0.60, prob_floor=0.68, max_legs=MAX_SAFE_LEGS)),
    ("target_10_safe", "Target ~10× SAFE", lambda legs: _safest_multi_py(legs, 10, min_hit5=0.60, prob_floor=0.58, max_legs=6)),
]


@app.get("/api/tracker")
def get_tracker():
    return _load_tracker()


@app.get("/api/tracker/current-multis")
def get_current_multis():
    """Generate all multis for all upcoming games (does not save anything)."""
    ev = sh.upcoming_events()
    if ev.empty:
        return []
    venues = sh.fixture_venues(2026)
    ps = sh.player_stats()
    canon_index = _build_canon_index(ps)   # built once, shared across all games
    results = []
    for _, erow in ev.iterrows():
        event_id = str(erow["id"])
        home, away = erow["home_team"], erow["away_team"]
        venue, when = venues.get((home, away), ("", None))
        game_label = f"{home} v {away}"
        game_date = str(erow.get("commence_time", ""))
        try:
            raw_legs = sh.priced_legs(event_id, home, away, venue, when)
        except Exception:
            continue
        if raw_legs.empty:
            continue
        legs_raw = [_row(r) for r in raw_legs.to_dict("records")]
        legs = _enrich_with_hit_rates(legs_raw, canon_index, home, away)
        multis = []
        for mtype, mlabel, builder in _MULTI_SPECS:
            result = builder(legs)
            if result:
                multis.append({
                    "multi_type": mtype,
                    "multi_label": mlabel,
                    "legs": result["legs"],
                    "combined_odds": result["combined_odds"],
                    "joint_prob": result["joint_prob"],
                })
        if multis:
            results.append({
                "event_id": event_id,
                "game": game_label,
                "home": home,
                "away": away,
                "game_date": game_date,
                "multis": multis,
            })
    return results


@app.post("/api/tracker/place")
def place_bets(payload: dict):
    """Store a list of bets. payload = {"bets": [...]}"""
    bets_in: list[dict] = payload.get("bets", [])
    data = _load_tracker()
    now = _dt.utcnow().isoformat()
    for bet in bets_in:
        bet["id"] = str(_uuid.uuid4())
        bet["placed_at"] = now
        bet["status"] = "pending"
        bet["result_checked_at"] = None
        bet["pnl"] = None
        bet["stake"] = 5.0
        bet["potential_return"] = round(5.0 * bet["combined_odds"], 2)
        for leg in bet.get("legs", []):
            leg.setdefault("result", None)
            leg.setdefault("actual_value", None)
        data["bets"].append(bet)
    _save_tracker(data)
    return {"placed": len(bets_in)}


@app.post("/api/tracker/auto-place")
def auto_place():
    """Place $5 on every multi for every upcoming game that hasn't been placed yet.
    Safe to call repeatedly — skips (game, bet-type) combos that already have a
    bet, so newly-added bet types get placed without re-placing existing ones."""
    current = get_current_multis()  # reuse existing logic
    data = _load_tracker()
    placed = {(b["event_id"], b["multi_type"]) for b in data["bets"]}
    now = _dt.utcnow().isoformat()
    new_bets: list[dict] = []

    for game in current:
        for multi in game["multis"]:
            if (game["event_id"], multi["multi_type"]) in placed:
                continue  # this bet type already placed for this game
            legs_with_opp = []
            for leg in multi["legs"]:
                opp = game["away"] if leg.get("team") == game["home"] else game["home"]
                legs_with_opp.append({**leg, "opponent": opp, "result": None, "actual_value": None})
            new_bets.append({
                "id": str(_uuid.uuid4()),
                "placed_at": now,
                "game": game["game"],
                "event_id": game["event_id"],
                "game_date": game["game_date"],
                "multi_type": multi["multi_type"],
                "multi_label": multi["multi_label"],
                "legs": legs_with_opp,
                "combined_odds": multi["combined_odds"],
                "stake": 5.0,
                "potential_return": round(5.0 * multi["combined_odds"], 2),
                "status": "pending",
                "result_checked_at": None,
                "pnl": None,
            })

    data["bets"].extend(new_bets)
    _save_tracker(data)
    return {"auto_placed": len(new_bets), "bets": data["bets"]}


def _run_check_results() -> dict:
    """Core result-checking logic — shared by the API endpoint and background tasks."""
    data = _load_tracker()
    ps = sh.player_stats()
    canon_index = _build_canon_index(ps)
    now = _dt.utcnow()
    updated = 0

    for bet in data["bets"]:
        if bet.get("status") != "pending":
            continue
        try:
            game_dt_str = bet.get("game_date", "")
            game_dt_str_clean = game_dt_str.replace("Z", "").split("+")[0]
            game_dt = _dt.fromisoformat(game_dt_str_clean)
        except Exception:
            continue
        if game_dt > now:
            continue  # game hasn't been played yet

        all_resolved = True
        all_hit = True

        for leg in bet.get("legs", []):
            if leg.get("result") is not None:
                if not leg["result"]:
                    all_hit = False
                continue  # already checked

            player = leg.get("player_scraped") or leg["player"]
            stat = leg["stat"]
            line_val = float(leg.get("line", leg.get("line_val", 0)))
            opponent = leg.get("opponent", "")

            key = canonical_name(player)
            hist = canon_index.get(key)
            if hist is None or stat not in hist.columns:
                all_resolved = False
                continue

            hist_sorted = hist.sort_values("date").reset_index(drop=True)
            game_date_str = game_dt.strftime("%Y-%m-%d")
            future = hist_sorted[
                pd.to_datetime(hist_sorted["date"]).dt.strftime("%Y-%m-%d") >= game_date_str
            ]
            if opponent:
                opp_match = future[future["opponent"] == opponent]
                if not opp_match.empty:
                    future = opp_match

            if future.empty:
                all_resolved = False
                continue

            actual = float(future.iloc[0][stat])
            hit = actual >= line_val
            leg["result"] = hit
            leg["actual_value"] = actual
            if not hit:
                all_hit = False

        if all_resolved:
            bet["status"] = "won" if all_hit else "lost"
            bet["pnl"] = round(5.0 * bet["combined_odds"] - 5.0, 2) if all_hit else -5.0
            bet["result_checked_at"] = now.isoformat()
            updated += 1

    _save_tracker(data)
    return {"updated": updated, "bets": data["bets"]}


@app.post("/api/tracker/check")
def check_results():
    """Check results for all pending bets where game_date < now."""
    return _run_check_results()


@app.get("/api/tracker/live-progress")
def tracker_live_progress():
    """Per-leg live values for pending bets in games currently being played.

    Sourced from the AFL official API poller (api.afl_live). Returns
    {bet_id: {"game": ..., "status": ..., "legs": [{player, stat, line,
    current, hit}], "legs_hit": n, "legs_total": m}}.
    """
    from api import afl_live as _afl_live
    import json as _json
    if not _afl_live.LIVE_STATS_FILE.exists():
        return {}
    try:
        live = _json.loads(_afl_live.LIVE_STATS_FILE.read_text())
    except Exception:
        return {}
    if not live:
        return {}
    by_pair = {frozenset((v["home"], v["away"])): v for v in live.values()}
    data = _load_tracker()
    out = {}
    for bet in data.get("bets", []):
        if bet.get("status") != "pending":
            continue
        try:
            pair = frozenset(s.strip() for s in bet["game"].split(" v "))
        except Exception:
            continue
        snap = by_pair.get(pair)
        if snap is None:
            continue
        legs_out, hit_n = [], 0
        for leg in bet.get("legs", []):
            key = canonical_name(leg.get("player_scraped") or leg.get("player", ""))
            cur = (snap["players"].get(key) or {}).get(leg.get("stat"))
            hit = cur is not None and float(cur) > float(leg.get("line", 0))
            hit_n += bool(hit)
            legs_out.append({"player": leg.get("player"), "stat": leg.get("stat"),
                             "milestone": leg.get("milestone"),
                             "line": leg.get("line"), "current": cur,
                             "hit": bool(hit)})
        out[bet["id"]] = {"game": bet["game"], "status": snap.get("status"),
                          "updated": snap.get("updated"), "legs": legs_out,
                          "legs_hit": hit_n, "legs_total": len(legs_out)}
    return out


@app.post("/api/tracker/afl-sync")
def tracker_afl_sync():
    """Manually trigger one AFL API poll/settlement cycle."""
    from api import afl_live as _afl_live
    return _afl_live.run_once()


# ---------------------------------------------------------------------------
# Historical rounds — browse past rounds across all seasons
# ---------------------------------------------------------------------------

def _display_name(afl_name: str) -> str:
    """'Bedford, Toby' → 'Toby Bedford'"""
    parts = str(afl_name).split(", ")
    return f"{parts[1]} {parts[0]}" if len(parts) == 2 else str(afl_name)


@app.get("/api/historical/rounds")
def list_historical_rounds():
    """All rounds available in player stats, ordered by season then date."""
    ps = sh.player_stats()
    tmp = ps[["season", "round", "date"]].copy()
    tmp["date"] = pd.to_datetime(tmp["date"])
    rounds = tmp.groupby(["season", "round"])["date"].min().reset_index()
    rounds = rounds.sort_values(["season", "date"])
    return [
        {"season": int(r["season"]), "round": str(r["round"]), "date": r["date"].strftime("%Y-%m-%d")}
        for _, r in rounds.iterrows()
    ]


@app.get("/api/historical/round")
def get_historical_round(season: int, rnd: str):
    """Game results for a specific past round."""
    ps = sh.player_stats()
    df = ps[(ps["season"] == season) & (ps["round"] == rnd)].copy()
    if df.empty:
        raise HTTPException(404, f"No data for {season} {rnd}")

    df["date"] = pd.to_datetime(df["date"])
    games: list[dict] = []
    seen: set = set()

    home_entries = df[df["home"] == True].drop_duplicates(subset=["team", "opponent"])
    for _, he in home_entries.iterrows():
        home_t, away_t = str(he["team"]), str(he["opponent"])
        pair = tuple(sorted([home_t, away_t]))
        if pair in seen:
            continue
        seen.add(pair)

        hr = df[(df["team"] == home_t) & (df["opponent"] == away_t)]
        ar = df[(df["team"] == away_t) & (df["opponent"] == home_t)]
        hg, hb = int(hr["goals"].sum()), int(hr["behinds"].sum())
        ag, ab = int(ar["goals"].sum()), int(ar["behinds"].sum())
        hs, as_ = hg * 6 + hb, ag * 6 + ab
        winner = home_t if hs > as_ else (away_t if as_ > hs else None)

        top = pd.concat([hr, ar]).nlargest(3, "disposals")[["player", "team", "disposals"]].values.tolist()
        games.append({
            "home": home_t, "away": away_t,
            "venue": str(he["venue"]),
            "date": he["date"].strftime("%Y-%m-%d"),
            "home_score": hs, "away_score": as_,
            "home_goals": hg, "home_behinds": hb,
            "away_goals": ag, "away_behinds": ab,
            "winner": winner,
            "top_disposals": [[_display_name(p), str(t), int(d)] for p, t, d in top],
        })

    return sorted(games, key=lambda g: g["date"])


# ---------------------------------------------------------------------------
# Live scores — api-sports.io cache
# ---------------------------------------------------------------------------

@app.get("/api/live/games")
def live_games():
    """Cached live/upcoming game scores (today + tomorrow) from api-sports.io."""
    from datetime import date as _date
    cache = _live.load_cache()
    today_str = _date.today().isoformat()
    live_quarters = {"Q1", "Q2", "HT", "Q3", "Q4", "OT", "BT"}
    games = []
    for g in cache.get("games", []):
        game_date = (g.get("date") or "")[:10]
        if game_date and game_date < today_str and g.get("status") in live_quarters:
            g = {**g, "status": "FT"}
        games.append(g)
    return {
        "games": games,
        "last_updated": cache.get("last_updated"),
        "last_fetch_ok": cache.get("last_fetch_ok"),
        "daily_used": cache.get("daily_used", 0),
        "daily_limit": _live.MAX_DAY,
        "daily_remaining": _live.remaining(cache),
    }


@app.post("/api/live/refresh")
def live_refresh():
    """Force an immediate fetch regardless of schedule (uses 2 requests)."""
    ok = _live.fetch_now()
    cache = _live.load_cache()
    return {
        "ok": ok,
        "games": cache.get("games", []),
        "daily_used": cache.get("daily_used", 0),
        "daily_remaining": _live.remaining(cache),
        "last_updated": cache.get("last_updated"),
    }


@app.get("/api/live/status")
def live_status():
    """API budget and schedule status."""
    cache = _live.load_cache()
    interval = _live.fetch_interval()
    return {
        "daily_used": cache.get("daily_used", 0),
        "daily_limit": _live.MAX_DAY,
        "daily_remaining": _live.remaining(cache),
        "last_updated": cache.get("last_updated"),
        "last_fetch_ok": cache.get("last_fetch_ok"),
        "active_window": interval is not None,
        "fetch_interval_sec": interval,
        "reset_date": cache.get("reset_date"),
    }


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Analysis endpoints — team styles, matchup win rates, position concession
# ---------------------------------------------------------------------------

@app.get("/api/analysis/team-styles")
def analysis_team_styles():
    if "team_styles" not in _analysis_cache:
        _analysis_cache["team_styles"] = _analysis.team_style_profiles()
    return _analysis_cache["team_styles"]


@app.get("/api/analysis/style-matchups")
def analysis_style_matchups():
    if "style_matchups" not in _analysis_cache:
        _analysis_cache["style_matchups"] = _analysis.style_matchups()
    return _analysis_cache["style_matchups"]


@app.get("/api/analysis/role-leaks")
def analysis_role_leaks():
    """Disposals conceded per ON-FIELD role (per-game classified), by team."""
    if "role_leaks" not in _analysis_cache:
        _analysis_cache["role_leaks"] = _analysis.role_leaks()
    return _analysis_cache["role_leaks"]


@app.get("/api/analysis/position-concession")
def analysis_position_concession():
    # Always recompute so new position CSV is picked up without restart
    return _analysis.position_concession()


@app.post("/api/analysis/refresh")
def analysis_refresh():
    """Bust analysis cache (call after re-scraping positions or new stats)."""
    _analysis_cache.clear()
    _pos_adj.invalidate_cache()
    from afl.model import tactical as _tactical
    _tactical.invalidate_all_caches()
    return {"ok": True}


@app.get("/api/players/volatility")
def player_volatility():
    """Player disposal volatility scores — used to flag risky parlay picks."""
    import json as _json
    vol_path = Path(__file__).parent / "data" / "player_volatility.json"
    if not vol_path.exists():
        return {}
    return _json.loads(vol_path.read_text())
