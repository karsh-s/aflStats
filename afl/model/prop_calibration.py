"""Backtest and calibrate the player-prop projections.

The live scan kept flagging huge "Under" edges, which is the classic symptom of
a projection that is biased low and/or over-confident. This module measures that
directly and searches for projection knobs that remove it.

Method (leak-free):
  * Fit player Elo only on games *before* a cutoff date.
  * For every player-game on/after the cutoff, project the stat from that
    player's own prior games (a strict expanding window) using the shared
    ``player_props.projection_stats`` maths.
  * Score the projection against what actually happened.

Metrics:
  * bias  = mean(actual - projection)      -> should be ~0 (negative => too low)
  * MAE / RMSE                              -> projection sharpness
  * ECE   = expected calibration error of P(over) across synthetic lines
            (does "70%" actually hit ~70%?)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import player_elo, player_props
from ._dist import nbinom_sf, poisson_sf


def _fit_elo(stats: pd.DataFrame, stat: str, cutoff) -> player_elo.PlayerEloModel:
    train = stats[stats["date"] < pd.Timestamp(cutoff)]
    return player_elo.fit(train, stat)


def projection_records(stats: pd.DataFrame, stat: str, *, cutoff,
                       elo_model: player_elo.PlayerEloModel | None,
                       elo_weight: float, recent_n: int,
                       dispersion_scale: float, min_history: int = 4,
                       use_splits: bool = False, split_weight: float | None = None,
                       split_shrink: float | None = None,
                       use_role_drift: bool = False,
                       tactical_tables: dict | None = None,
                       margins: dict | None = None,
                       outs_lookup: dict | None = None,
                       collect_flags: bool = False):
    """Return [(projected_mean, projected_sd, actual)] for the test window.

    When ``use_splits`` is True the opponent/venue/weather adjustments are
    applied exactly as in the live model (leak-free: each projection uses only a
    player's prior games), so their effect can be measured.

    Tactical replay (all optional, require use_splits=True):
      * ``use_role_drift``   -- enable role-change reweighting
      * ``tactical_tables``  -- {"pace","tagging","game_script","absence"} tables
                                built from pre-cutoff data
      * ``margins``          -- {(date_norm, hteam, ateam): predicted home margin}
      * ``outs_lookup``      -- {(team, date_norm): set of absent pillars} for
                                validating absence deltas against real absences
      * ``collect_flags``    -- append a per-record flags dict for subset scoring
    """
    cutoff = pd.Timestamp(cutoff)
    recs: list = []
    use_elo = elo_model is not None
    stats = stats.sort_values("date")
    has_weather = {"wet", "windy"} <= set(stats.columns)
    has_team = "team" in stats.columns
    decay = player_props.DECAY_BY_STAT.get(stat, player_props.DEFAULT_DECAY)
    tact = tactical_tables or {}
    if tact:
        from . import tactical as tact_mod

    for player, g in stats.groupby("player", sort=False):
        g = g.reset_index(drop=True)
        vals = g[stat].to_numpy(dtype=float)
        dates = g["date"].to_numpy()
        opps = g["opponent"].tolist()
        homes = g["home"].tolist()
        for i in range(min_history, len(vals)):
            if dates[i] < np.datetime64(cutoff):
                continue
            if i < min_history:
                continue
            elo_exp = (elo_model.expected(player, opps[i], bool(homes[i]))
                       if use_elo else None)
            flags: dict = {}
            if not use_splits:
                prior = vals[max(0, i - recent_n):i]
                if len(prior) < min_history:
                    continue
                mean, sd = player_props.projection_stats(
                    prior, is_home=bool(homes[i]), stat=stat, elo_exp=elo_exp,
                    elo_weight=elo_weight, dispersion_scale=dispersion_scale,
                    decay=decay)
            else:
                prior = g.iloc[:i]
                if len(prior) < min_history:
                    continue
                row = g.iloc[i]
                forecast = ({"rain_mm": row.get("rain_mm", 0.0),
                             "wind_kmh": row.get("wind_kmh", 0.0)}
                            if has_weather else None)
                mean, sd, _, comp = player_props.project_from_history(
                    prior, stat, opponent=opps[i],
                    venue_norm=row.get("venue_norm"), is_home=bool(homes[i]),
                    forecast=forecast, elo_exp=elo_exp, recent_n=recent_n,
                    elo_weight=elo_weight, dispersion_scale=dispersion_scale,
                    use_splits=True, opp_weight=split_weight,
                    venue_weight=split_weight, weather_weight=split_weight,
                    split_shrink=split_shrink, decay=decay,
                    use_role_drift=use_role_drift)
                flags["role_flag"] = (comp.get("role_drift", 0.0)
                                      >= _role_threshold())

                if tact and has_team:
                    team = str(row["team"])
                    d_norm = pd.Timestamp(dates[i]).normalize()
                    em = None
                    if margins is not None:
                        if bool(homes[i]):
                            em = margins.get((d_norm, team, str(opps[i])))
                        else:
                            m = margins.get((d_norm, str(opps[i]), team))
                            em = -m if m is not None else None
                    outs = (outs_lookup or {}).get((team, d_norm), set())
                    ctx = tact_mod.TacticalContext(
                        pace=tact.get("pace"), tagging=tact.get("tagging"),
                        game_script=tact.get("game_script") if em is not None else None,
                        absence=tact.get("absence"),
                        exp_margin=em if em is not None else None,
                        home_team=team,   # em already team-relative
                        probable_outs={team: outs})
                    mean = tact_mod.apply_tactical(
                        mean, comp, player=player, stat=stat,
                        opponent=str(opps[i]), team=team, tactical=ctx)
                    tag_tbl = tact.get("tagging")
                    flags["star_flag"] = bool(
                        tag_tbl is not None and tag_tbl.is_star(player))
                    flags["absence_flag"] = bool(outs)
                    flags["blowout_flag"] = bool(em is not None and abs(em) > 24)
            if collect_flags:
                recs.append((mean, sd, vals[i], flags))
            else:
                recs.append((mean, sd, vals[i]))
    return recs


def _role_threshold() -> float:
    from . import role_change
    return role_change.DRIFT_THRESHOLD


def _prob_over(dist: str, line: float, mean: float, sd: float) -> float:
    k = int(np.floor(line))               # P(X > line) for half-integer line
    return poisson_sf(k, mean) if dist == "poisson" else nbinom_sf(k, mean, sd)


def score(recs: list[tuple[float, float, float]], stat: str,
          *, bins: int = 10) -> dict:
    if not recs:
        return {"n": 0}
    arr = np.array(recs)
    mean, sd, actual = arr[:, 0], arr[:, 1], arr[:, 2]
    bias = float(np.mean(actual - mean))
    mae = float(np.mean(np.abs(actual - mean)))
    rmse = float(np.sqrt(np.mean((actual - mean) ** 2)))

    dist = "poisson" if stat == "goals" else "nbinom"
    preds, outs = [], []
    for m, s, a in recs:
        lo = int(max(0, np.floor(m - 8)))
        hi = int(np.ceil(m + 8))
        for line in np.arange(lo + 0.5, hi + 0.5, 1.0):
            preds.append(_prob_over(dist, line, m, s))
            outs.append(1.0 if a > line else 0.0)
    preds, outs = np.array(preds), np.array(outs)

    edges = np.linspace(0, 1, bins + 1)
    ece = 0.0
    reliability = []
    for b in range(bins):
        m = (preds >= edges[b]) & (preds < edges[b + 1] if b < bins - 1
                                   else preds <= edges[b + 1])
        if not m.any():
            continue
        conf, freq, w = preds[m].mean(), outs[m].mean(), m.mean()
        ece += w * abs(conf - freq)
        reliability.append((round(conf, 3), round(freq, 3), int(m.sum())))
    return {"n": len(recs), "bias": round(bias, 3), "mae": round(mae, 3),
            "rmse": round(rmse, 3), "ece": round(float(ece), 4),
            "reliability": reliability}


def grid_search(stats: pd.DataFrame, stat: str, *, cutoff,
                elo_weights=(0.0, 0.15, 0.3), recent_ns=(8, 12, 16),
                dispersion_scales=(1.0, 1.25, 1.5), use_elo: bool = True
                ) -> pd.DataFrame:
    """Search projection knobs; rank by |bias| then ECE."""
    elo_model = _fit_elo(stats, stat, cutoff) if use_elo else None
    rows = []
    for ew in elo_weights:
        for rn in recent_ns:
            for ds in dispersion_scales:
                recs = projection_records(
                    stats, stat, cutoff=cutoff, elo_model=elo_model,
                    elo_weight=ew, recent_n=rn, dispersion_scale=ds)
                s = score(recs, stat)
                rows.append({"elo_weight": ew, "recent_n": rn,
                             "dispersion_scale": ds, **{k: v for k, v in s.items()
                                                        if k != "reliability"}})
    df = pd.DataFrame(rows)
    df["abs_bias"] = df["bias"].abs()
    return df.sort_values(["abs_bias", "ece"]).reset_index(drop=True)
