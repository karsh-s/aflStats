"""AFL tactical analysis — team styles, style matchups, position concession rates.

All functions are designed to be called once and cached; results are plain
Python dicts/lists so they JSON-serialize trivially.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PLAYER_STATS  = ROOT / "data" / "raw" / "player_stats.pkl"
GAMES_PKL     = ROOT / "data" / "raw" / "games.pkl"
POSITIONS_CSV = ROOT / "data" / "raw" / "player_positions.csv"

# Analysis window: last N seasons (more recent = more relevant)
SEASONS = [2023, 2024, 2025, 2026]

# ── Position group order for display ─────────────────────────────────────────
POS_ORDER = ["Key Defender", "Midfielder", "Ruck", "Forward"]


# ── Style classification ──────────────────────────────────────────────────────

def _style_label(contested_ratio: float, kick_ratio: float) -> str:
    """4-quadrant game style label."""
    high_c = contested_ratio >= 0.375
    high_k = kick_ratio >= 0.590
    if high_c and high_k:
        return "Power"
    if high_c and not high_k:
        return "Handball Chain"
    if not high_c and high_k:
        return "Kick-Mark"
    return "Running / Spread"


# ── Team-level per-game aggregates ───────────────────────────────────────────

def _team_games(ps: pd.DataFrame) -> pd.DataFrame:
    ps = ps[ps["season"].isin(SEASONS)].copy()
    tg = ps.groupby(["season", "round", "date", "team", "opponent", "home"]).agg(
        disp     =("disposals",     "sum"),
        clears   =("clearances",   "sum"),
        contested=("contested_poss","sum"),
        uncontested=("uncontested_poss","sum"),
        marks    =("marks",        "sum"),
        tackles  =("tackles",      "sum"),
        rebounds =("rebounds",     "sum"),
        inside50 =("inside50s",    "sum"),
        kicks    =("kicks",        "sum"),
        handballs=("handballs",    "sum"),
        goals    =("goals",        "sum"),
        clangers =("clangers",     "sum"),
        cont_marks=("contested_marks","sum"),
        i50_marks =("marks_inside50","sum"),
    ).reset_index()
    tg["contested_ratio"] = tg["contested"] / (tg["contested"] + tg["uncontested"])
    tg["kick_ratio"]      = tg["kicks"] / (tg["kicks"] + tg["handballs"])
    return tg


# ── 1. Team style profiles ────────────────────────────────────────────────────

def team_style_profiles() -> list[dict]:
    ps  = pd.read_pickle(PLAYER_STATS)
    tg  = _team_games(ps)
    agg = tg.groupby("team").agg(
        games             =("date",             "count"),
        avg_contested_ratio=("contested_ratio", "mean"),
        avg_kick_ratio    =("kick_ratio",       "mean"),
        avg_clearances    =("clears",           "mean"),
        avg_tackles       =("tackles",          "mean"),
        avg_inside50      =("inside50",         "mean"),
        avg_rebounds      =("rebounds",         "mean"),
        avg_goals         =("goals",            "mean"),
        avg_clangers      =("clangers",         "mean"),
        avg_cont_marks    =("cont_marks",       "mean"),
        avg_i50_marks     =("i50_marks",        "mean"),
    ).round(3).reset_index()

    rows = []
    for _, r in agg.iterrows():
        rows.append({
            "team":                  r["team"],
            "games":                 int(r["games"]),
            "style":                 _style_label(r["avg_contested_ratio"], r["avg_kick_ratio"]),
            "contested_ratio":       round(float(r["avg_contested_ratio"]), 3),
            "kick_ratio":            round(float(r["avg_kick_ratio"]), 3),
            "avg_clearances":        round(float(r["avg_clearances"]), 1),
            "avg_tackles":           round(float(r["avg_tackles"]), 1),
            "avg_inside50":          round(float(r["avg_inside50"]), 1),
            "avg_rebounds":          round(float(r["avg_rebounds"]), 1),
            "avg_goals":             round(float(r["avg_goals"]), 1),
            "avg_clangers":          round(float(r["avg_clangers"]), 1),
            "avg_cont_marks":        round(float(r["avg_cont_marks"]), 1),
            "avg_i50_marks":         round(float(r["avg_i50_marks"]), 1),
        })
    return sorted(rows, key=lambda x: x["contested_ratio"], reverse=True)


# ── 2. Style vs style matchup win rates ──────────────────────────────────────

def style_matchups() -> dict[str, Any]:
    ps  = pd.read_pickle(PLAYER_STATS)
    tg  = _team_games(ps)

    # Compute each team's rolling style (based on all games in dataset)
    team_style = {}
    ts = tg.groupby("team")[["contested_ratio", "kick_ratio"]].mean()
    for team, row in ts.iterrows():
        team_style[str(team)] = _style_label(row["contested_ratio"], row["kick_ratio"])

    # Load games for results
    games = pd.read_pickle(GAMES_PKL)
    games = games[games["year"].isin(SEASONS) & (games["complete"] == 100)].copy()

    # Build matchup win-rate matrix
    from collections import defaultdict
    wins:  dict[tuple, int] = defaultdict(int)
    total: dict[tuple, int] = defaultdict(int)

    for _, g in games.iterrows():
        hs = team_style.get(str(g["hteam"]))
        as_ = team_style.get(str(g["ateam"]))
        if hs is None or as_ is None:
            continue
        total[(hs, as_)] += 1
        total[(as_, hs)] += 1
        if g["winner"] == g["hteam"]:
            wins[(hs, as_)] += 1
        else:
            wins[(as_, hs)] += 1

    styles = ["Power", "Handball Chain", "Kick-Mark", "Running / Spread"]
    matrix = []
    for s1 in styles:
        row_data = []
        for s2 in styles:
            n = total.get((s1, s2), 0)
            w = wins.get((s1, s2), 0)
            row_data.append({
                "win_rate": round(w / n, 3) if n else None,
                "n":        n,
            })
        matrix.append({"style": s1, "results": row_data})

    # Compute per-style offensive/defensive fingerprints
    fingerprints = {}
    for team, style in team_style.items():
        if style not in fingerprints:
            fingerprints[style] = []
        fingerprints[style].append(team)

    return {
        "styles":       styles,
        "matrix":       matrix,
        "style_teams":  fingerprints,
        "team_styles":  team_style,
    }


# ── 3. Position concession rates ─────────────────────────────────────────────

def position_concession() -> dict[str, Any]:
    if not POSITIONS_CSV.exists():
        return {"available": False, "reason": "Position data not yet scraped"}

    ps  = pd.read_pickle(PLAYER_STATS)
    pos = pd.read_csv(POSITIONS_CSV)

    ps = ps[ps["season"].isin(SEASONS)].copy()

    # Merge positions onto player stats
    merged = ps.merge(
        pos[["player", "position_group"]],
        on="player",
        how="left",
    )
    merged = merged.dropna(subset=["position_group"])
    merged["position_group"] = pd.Categorical(
        merged["position_group"], categories=POS_ORDER, ordered=True
    )

    # Per-player per-game, grouped by opponent × position
    # We want: avg disposals / avg goals CONCEDED by each team
    # i.e., stats of OPPOSITION players against that team
    opp_pos = (
        merged.groupby(["opponent", "position_group"])
        .agg(
            avg_disposals=("disposals", "mean"),
            avg_goals    =("goals",     "mean"),
            avg_clearances=("clearances","mean"),
            avg_rebounds =("rebounds",  "mean"),
            avg_inside50 =("inside50s", "mean"),
            n_games      =("disposals", "count"),
        )
        .round(2)
        .reset_index()
    )

    # Compute league average per position (for z-score / relative comparison)
    league_avg = (
        merged.groupby("position_group")
        .agg(
            avg_disposals=("disposals", "mean"),
            avg_goals    =("goals",     "mean"),
        )
        .round(2)
    )

    # Build response: list of teams with their concession profile per position
    teams_out = []
    for team in sorted(opp_pos["opponent"].unique()):
        team_rows = opp_pos[opp_pos["opponent"] == team].set_index("position_group")
        positions_out = []
        for pg in POS_ORDER:
            if pg not in team_rows.index:
                continue
            row = team_rows.loc[pg]
            la  = league_avg.loc[pg] if pg in league_avg.index else None
            disp_delta = round(float(row["avg_disposals"]) - float(la["avg_disposals"]), 2) if la is not None else 0.0
            goal_delta = round(float(row["avg_goals"])     - float(la["avg_goals"]),     2) if la is not None else 0.0
            positions_out.append({
                "position":     pg,
                "avg_disposals": round(float(row["avg_disposals"]), 1),
                "avg_goals":     round(float(row["avg_goals"]), 2),
                "avg_clearances":round(float(row["avg_clearances"]), 1),
                "avg_rebounds":  round(float(row["avg_rebounds"]), 1),
                "disp_vs_avg":   disp_delta,   # positive = more than league avg
                "goal_vs_avg":   goal_delta,
                "n_games":       int(row["n_games"]),
            })
        teams_out.append({"team": team, "positions": positions_out})

    # League averages by position
    league_out = []
    for pg in POS_ORDER:
        if pg in league_avg.index:
            league_out.append({
                "position":      pg,
                "avg_disposals": round(float(league_avg.loc[pg, "avg_disposals"]), 1),
                "avg_goals":     round(float(league_avg.loc[pg, "avg_goals"]), 2),
            })

    # Notable findings: positions where a team is >1 disp above/below average
    notable: list[dict] = []
    for t in teams_out:
        for p in t["positions"]:
            if abs(p["disp_vs_avg"]) >= 0.8:
                notable.append({
                    "team":     t["team"],
                    "position": p["position"],
                    "disp_vs_avg": p["disp_vs_avg"],
                    "avg_disposals": p["avg_disposals"],
                    "direction": "concedes more" if p["disp_vs_avg"] > 0 else "concedes fewer",
                })
    notable.sort(key=lambda x: abs(x["disp_vs_avg"]), reverse=True)

    return {
        "available":    True,
        "teams":        teams_out,
        "league_avg":   league_out,
        "notable":      notable[:30],
        "positions":    POS_ORDER,
    }


# ── Role leaks: per-game classified roles vs disposals conceded ───────────────

def role_leaks() -> dict[str, Any]:
    """Which teams leak disposals to which ON-FIELD roles the most.

    Uses per-game role classification from box-score signatures (see
    afl.model.game_roles) rather than static position labels, so a midfielder
    playing half-back counts as a Defender for THAT game. 2026 season only
    (the per-game signature stats are 2026-only).
    """
    import sys
    sys.path.insert(0, str(ROOT))
    from afl.model import game_roles

    ps = pd.read_pickle(ROOT / "data" / "raw" / "player_stats_enriched.pkl")
    g = game_roles.classify_games(ps)

    league = g.groupby("game_role")["disposals"].mean()

    teams_out = []
    for team in sorted(g["opponent"].dropna().unique()):
        conceded = g[g["opponent"] == team]
        roles_out = []
        for role in game_roles.ROLES:
            sub = conceded[conceded["game_role"] == role]
            if len(sub) < 10:
                continue
            avg = float(sub["disposals"].mean())
            delta = avg - float(league[role])
            roles_out.append({
                "role": role,
                "avg_disposals": round(avg, 1),
                "vs_league": round(delta, 2),
                "n_player_games": int(len(sub)),
            })
        teams_out.append({"team": str(team), "roles": roles_out})

    # Notable leaks, sorted by magnitude
    notable = []
    for t in teams_out:
        for r in t["roles"]:
            if abs(r["vs_league"]) >= 0.8:
                notable.append({
                    "team": t["team"], "role": r["role"],
                    "vs_league": r["vs_league"],
                    "avg_disposals": r["avg_disposals"],
                    "direction": "leaks more" if r["vs_league"] > 0 else "concedes fewer",
                })
    notable.sort(key=lambda x: -x["vs_league"])

    # Player exploits: biggest single-game overperformances conceded — a
    # player beating his own season average by the most against that team.
    g2 = g.copy()
    g2["season_avg"] = g2.groupby("player")["disposals"].transform("mean")
    g2["over"] = g2["disposals"] - g2["season_avg"]
    counts = g2.groupby("player")["date"].transform("nunique")
    exploits = (g2[counts >= 6].nlargest(15, "over")
                [["player", "opponent", "game_role", "disposals",
                  "season_avg", "over", "date"]])
    exploits_out = [{
        "player": str(r["player"]),
        "vs_team": str(r["opponent"]),
        "role": str(r["game_role"]),
        "disposals": int(r["disposals"]),
        "season_avg": round(float(r["season_avg"]), 1),
        "over": round(float(r["over"]), 1),
        "date": str(r["date"])[:10],
    } for _, r in exploits.iterrows()]

    return {
        "available": True,
        "teams": teams_out,
        "league_avg": {role: round(float(league[role]), 1)
                       for role in game_roles.ROLES if role in league.index},
        "notable": notable[:30],
        "exploits": exploits_out,
        "roles": game_roles.ROLES,
    }
