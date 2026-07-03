"""Player-prop projections and the probability a given line cashes.

For a player + stat (e.g. disposals, goals), we:
  1. Project an expected value from recent games, blended with the player's
     Elo skill rating and adjusted for the opponent's defence and home/away.
  2. Wrap that expectation in a count distribution:
       * goals      -> Poisson (rare, low-count events)
       * everything -> Negative Binomial (over-dispersed counts like disposals)
     with dispersion estimated from the player's own game-to-game variance.
  3. Read off P(over the line) and P(under), which can then be compared with a
     bookmaker's implied probability to flag value (see ``afl.odds.value``).
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from ._dist import nbinom_sf, poisson_sf
from . import player_elo, role_change


# ---------------------------------------------------------------------------
# Player-name reconciliation
# AFL Tables spells names "Neale, Lachie"; The Odds API uses "Lachie Neale".
# We canonicalise both to "firstname lastname" (accent- and case-folded) so a
# bookmaker's prop can be matched to the scraped statline.
# ---------------------------------------------------------------------------
def canonical_name(name: str) -> str:
    # Keep hyphens so "Byrne-Jones" stays one surname token and does not
    # collapse onto an unrelated "Jones".
    n = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    n = n.lower().replace(".", " ")
    if "," in n:                      # "last, first [middle]"
        last, _, first = n.partition(",")
        first_tokens = first.split()
        first_name = first_tokens[0] if first_tokens else ""
        surname = "-".join(t for t in last.replace("-", " ").split())
        parts = [first_name, surname]
    else:                             # "first [middle] last"
        tokens = n.split()
        if len(tokens) < 2:
            return n.strip()
        first_name = tokens[0]
        surname = "-".join(tokens[-1].replace("-", " ").split())
        parts = [first_name, surname]
    parts = [p for p in parts if p]
    return " ".join(parts)            # "first surname", middle names dropped


def build_player_index(stats: pd.DataFrame) -> dict[str, str]:
    """Map canonical name -> the exact AFL Tables player string."""
    return {canonical_name(p): p for p in stats["player"].dropna().unique()}


def resolve_player(name: str, index: dict[str, str]) -> str | None:
    """Best-effort match of an external player name to a scraped player."""
    c = canonical_name(name)
    if c in index:
        return index[c]
    parts = c.split()
    if len(parts) >= 2:               # fallback: first-initial + surname
        first_i, last = parts[0][0], parts[-1]
        for key, val in index.items():
            kp = key.split()
            if kp and kp[-1] == last and kp[0][0] == first_i:
                return val
    return None


@dataclass
class PropProjection:
    player: str
    stat: str
    opponent: str
    is_home: bool
    mean: float
    sd: float
    n_games: int
    dist: str
    # Per-factor breakdown of how the mean was built (base + situational deltas).
    components: dict = field(default_factory=dict)

    def prob_over(self, line: float) -> float:
        """P(stat strictly exceeds the books' line).

        Half-point lines (e.g. 19.5) have no push; for integer lines the bet is
        usually "X or more", so we treat ``line`` as needing ``> line`` and let
        the caller pass 19.5 for a 20+ market.
        """
        # need ceil(line+epsilon) or more -> P(X >= k)
        k = int(np.floor(line)) + 1
        if self.dist == "poisson":
            return float(poisson_sf(k - 1, self.mean))
        return float(nbinom_sf(k - 1, self.mean, self.sd))

    def prob_under(self, line: float) -> float:
        return 1.0 - self.prob_over(line)

    def as_dict(self) -> dict:
        return {
            "player": self.player, "stat": self.stat, "opponent": self.opponent,
            "home": self.is_home, "projection": round(self.mean, 2),
            "sd": round(self.sd, 2), "n_games": self.n_games, "dist": self.dist,
            "components": {k: round(v, 2) for k, v in self.components.items()},
        }


# Default projection knobs, chosen by the calibration backtest
# (see afl.model.prop_calibration / scripts/calibrate_props.py). Ranked by
# |bias| then ECE (does "70%" actually hit ~70%?). Over full-season test
# windows (cutoffs 2024/2025/2026) the model is well-calibrated:
#   disposals: elo_w=0.0,  n=10  -> bias +0.03..+0.44, ECE 0.015..0.031
#   goals:     elo_w=0.30, n=14  -> bias ~0.00,        ECE ~0.005
#   tackles:   elo_w=0.0,  n=10  -> bias ~-0.07,       ECE ~0.006
# Notes from calibration:
#  * Widening the distribution (dispersion>1.0) only worsened ECE -> stays 1.0.
#  * The Elo blend helps goals but adds bias to disposals/tackles -> off there.
#  * No additive bias correction: the larger disposal bias seen on the small
#    2026-only window does NOT persist over full seasons, so "correcting" it
#    would overfit.
DEFAULT_ELO_WEIGHT = 0.0
DEFAULT_RECENT_N = 10
DEFAULT_DISPERSION_SCALE = 1.0
ELO_WEIGHT_BY_STAT: dict[str, float] = {"goals": 0.30}
RECENT_N_BY_STAT: dict[str, int] = {"goals": 14, "disposals": 14, "marks": 12}  # R16 2026: 14 > 12 consistently
DISPERSION_SCALE_BY_STAT: dict[str, float] = {}

# Recency weighting of the base window. ``None`` -> flat-ish linear weights
# (best for stable, noisy stats like goals/tackles). A float in (0,1] applies
# exponential decay where the newest game has weight 1 and each older game is
# multiplied by ``decay`` -- lower = more responsive to recent form / role
# changes. Calibrated (cutoff 2025): for disposals, exp decay 0.78 over a 12-game
# window beats the linear window on BOTH MAE and ECE while reacting faster to a
# player who has just stepped into a bigger role.
DEFAULT_DECAY = None
DECAY_BY_STAT: dict[str, float] = {"disposals": 0.78, "marks": 0.82}

# Flat 10-game anchor blended with the decay-weighted projection.
# With decay=0.78 over 12 games the last 5 games carry ~75% of total weight,
# so a short hot/cold streak can inflate the projection. The anchor is the
# plain mean of the last ANCHOR_N games (no decay, no Elo) multiplied by the
# same home/away factor; blending it in pulls inflated streaks back toward the
# player's true baseline without losing all responsiveness to role changes.
# Weight 0.0 disables the anchor for that stat (calibrated stats stay as-is).
ANCHOR_N = 10
ANCHOR_BLEND_BY_STAT: dict[str, float] = {
    "disposals": 0.35,   # R16 2026: lighter anchor with wider 14-game window
    "marks":     0.45,   # same (decay=0.82)
    "goals":     0.25,   # already 14-game flat window; lighter touch
    "tackles":   0.30,
    "kicks":     0.35,
    "handballs": 0.35,
}
DEFAULT_ANCHOR_BLEND = 0.30

# --- Situational split knobs (opponent / venue / weather) ------------------
# Each split is a *form-adjusted, shrunk additive delta* on the base projection.
#
# Form-adjusted effect (the important bit): rather than comparing a player's
# games-vs-opponent to their career mean -- which conflates "this team suppresses
# me" with "I was in poorer form that season" -- we compare each such game to the
# player's LOCAL form: the LOCAL_WINDOW games either side of it that are NOT
# themselves in the split. The residual is how much the opponent/venue/weather
# moved the player *relative to who they were at the time*. The effect is the
# (recency-weighted) mean residual, then shrunk by n/(n + SPLIT_SHRINK).
#
# Calibrated finding (scripts/calibrate_props.py): AFL matchup/venue/weather
# effects are real but modest -- recent form already encodes much of them. The
# form-adjusted residual is less noisy than the naive delta, so it earns a
# slightly higher weight, but full weight still over-fits. Hence the per-stat
# weights below.
OPP_N = 6
VENUE_N = 6
LOCAL_WINDOW = 3          # games either side used as the "form at the time"
SPLIT_SHRINK = 6.0
DEFAULT_SPLIT_WEIGHT = 0.45
SPLIT_WEIGHT_BY_STAT: dict[str, float] = {
    "disposals": 0.30,   # R16 2026: lighter weight -- single season opp data is low-sample
    "goals": 0.15,       # recent form already captures it; kept small
    "marks": 0.40,
    "tackles": 0.15,     # ditto goals
}
# Fallback per-factor weights when project_from_history is called directly.
OPP_WEIGHT = DEFAULT_SPLIT_WEIGHT
VENUE_WEIGHT = DEFAULT_SPLIT_WEIGHT
WEATHER_WEIGHT = DEFAULT_SPLIT_WEIGHT
USE_SPLITS = True


def _recent(player_stats: pd.DataFrame, player: str, stat: str,
            n: int) -> pd.Series:
    rows = player_stats[player_stats["player"] == player].sort_values("date")
    return rows[stat].tail(n).astype(float)


def projection_stats(values, *, is_home: bool, stat: str,
                     elo_exp: float | None, elo_weight: float,
                     dispersion_scale: float,
                     decay: float | None = None) -> tuple[float, float]:
    """Core base (mean, sd) maths shared by live projection and the backtest.

    ``values`` are the player's most recent statlines (oldest -> newest). This
    is the recency baseline *before* any opponent/venue/weather adjustment.
    ``decay`` (0,1] applies exponential recency weighting; ``None`` keeps the
    flatter linear weighting.
    """
    values = np.asarray(values, dtype=float)
    n = len(values)
    if decay is None:
        weights = np.linspace(0.5, 1.0, n)
    else:
        weights = np.asarray(decay, dtype=float) ** np.arange(n - 1, -1, -1)
    ewma = float(np.average(values, weights=weights))
    sd = float(values.std(ddof=0)) or max(1.0, ewma ** 0.5)

    if elo_exp is not None:
        mean = (1 - elo_weight) * ewma + elo_weight * elo_exp
    else:
        mean = ewma * (1.03 if is_home else 0.98)

    mean = max(0.05, mean)
    sd = max(1.0, sd * dispersion_scale)
    return mean, sd


def _shrunk_delta(sub_values: np.ndarray, baseline: float, shrink: float) -> float:
    """Sample-size-shrunk deviation of a split's mean from the baseline."""
    m = len(sub_values)
    if m == 0:
        return 0.0
    delta = float(np.mean(sub_values)) - baseline
    return delta * (m / (m + shrink))


def form_adjusted_effect(vals: np.ndarray, mask: np.ndarray, *,
                         window: int = LOCAL_WINDOW, shrink: float = SPLIT_SHRINK,
                         max_n: int | None = None, min_other: int = 2
                         ) -> tuple[float, int]:
    """How much a condition moves a player vs their form *at the time*.

    For each game where ``mask`` is True, the local baseline is the mean of the
    ``window`` games either side that are NOT themselves in the mask (so a venue
    effect isn't washed out by other games at the same venue, etc.). The residual
    is game - local_baseline; the effect is the recency-weighted mean residual,
    shrunk by n/(n+shrink). Only games before the projected one are ever seen,
    so this stays leak-free in the backtest.

    Returns (shrunk_effect, n_samples).
    """
    idxs = np.flatnonzero(mask)
    if max_n is not None and len(idxs) > max_n:
        idxs = idxs[-max_n:]                      # most recent occurrences
    n = len(vals)
    resids = []
    for i in idxs:
        lo, hi = max(0, i - window), min(n, i + window + 1)
        local = [vals[j] for j in range(lo, hi) if j != i and not mask[j]]
        if len(local) < min_other:
            continue
        resids.append(vals[i] - float(np.mean(local)))
    m = len(resids)
    if m == 0:
        return 0.0, 0
    # Recency-weight the residuals (latest meeting matters most).
    w = np.linspace(0.6, 1.0, m)
    eff = float(np.average(resids, weights=w))
    return eff * (m / (m + shrink)), m


def explain_split(player_stats: pd.DataFrame, player: str, stat: str, *,
                  opponent: str | None = None, venue_norm: str | None = None,
                  window: int = LOCAL_WINDOW) -> pd.DataFrame:
    """Per-occurrence breakdown of a condition vs the player's local form.

    Shows, for each game vs ``opponent`` (or at ``venue_norm``), the value, the
    mean of the ``window`` non-matching games either side, and the residual --
    so you can see whether a low/high count was the matchup or just their form
    at the time. This is the raw material behind the opponent/venue adjustment.
    """
    h = player_stats[player_stats["player"] == player].sort_values("date").reset_index(drop=True)
    vals = h[stat].to_numpy(float)
    if opponent is not None:
        mask = (h["opponent"] == opponent).to_numpy()
    elif venue_norm is not None:
        mask = (h["venue_norm"] == venue_norm).to_numpy()
    else:
        return pd.DataFrame()
    n = len(vals)
    rows = []
    for i in np.flatnonzero(mask):
        lo, hi = max(0, i - window), min(n, i + window + 1)
        local = [vals[j] for j in range(lo, hi) if j != i and not mask[j]]
        lf = float(np.mean(local)) if local else float("nan")
        rows.append({"date": h.loc[i, "date"].date(), "venue": h.loc[i, "venue"],
                     stat: int(vals[i]), "local_form": round(lf, 1),
                     "residual": round(vals[i] - lf, 1) if local else None})
    return pd.DataFrame(rows)


def project_from_history(prior: pd.DataFrame, stat: str, *, opponent: str,
                         venue_norm: str | None, is_home: bool,
                         forecast: dict | None, elo_exp: float | None,
                         recent_n: int, elo_weight: float, dispersion_scale: float,
                         use_splits: bool = USE_SPLITS,
                         opp_weight: float | None = None,
                         venue_weight: float | None = None,
                         weather_weight: float | None = None,
                         split_shrink: float | None = None,
                         decay: float | None = None,
                         use_role_drift: bool | None = None
                         ) -> tuple[float, float, int, dict]:
    """Build (mean, sd, n_games, components) from a player's prior games.

    ``prior`` is that player's games strictly before the one being projected,
    chronologically ordered, with at least the columns ``stat``, ``opponent``,
    ``venue_norm`` and (optionally) ``wet``/``windy`` for the weather split.
    Split weights default to the module constants but can be overridden (the
    calibration grid search does this).
    """
    opp_weight = OPP_WEIGHT if opp_weight is None else opp_weight
    venue_weight = VENUE_WEIGHT if venue_weight is None else venue_weight
    weather_weight = WEATHER_WEIGHT if weather_weight is None else weather_weight
    split_shrink = SPLIT_SHRINK if split_shrink is None else split_shrink
    if use_role_drift is None:
        use_role_drift = role_change.USE_ROLE_DRIFT

    # Role-change detection: when the player's recent stat mix has drifted from
    # their baseline, react by weighting post-change games more heavily,
    # damping the flat anchor, and widening the SD.
    drift, drift_flag = (role_change.detect_drift(prior)
                         if use_role_drift else (0.0, False))
    anchor_scale = 1.0
    if drift_flag:
        decay = min(decay if decay is not None else 1.0, role_change.DRIFT_DECAY)
        anchor_scale = role_change.ANCHOR_DAMP

    vals = prior[stat].to_numpy(dtype=float)
    n = len(vals)
    base_mean, sd = projection_stats(
        vals[-recent_n:], is_home=is_home, stat=stat, elo_exp=elo_exp,
        elo_weight=elo_weight, dispersion_scale=dispersion_scale, decay=decay)

    # Blend with a flat ANCHOR_N-game mean to dampen hot/cold streak inflation.
    # The anchor uses no decay and no Elo — it is simply the unweighted mean of
    # the last 10 games (or fewer if the player hasn't played that many), scaled
    # by the same home/away factor as the main projection.
    anchor_w = ANCHOR_BLEND_BY_STAT.get(stat, DEFAULT_ANCHOR_BLEND) * anchor_scale
    anchor_delta = 0.0
    if anchor_w > 0 and n >= 3:
        anc_n = min(ANCHOR_N, n)
        anchor_raw = float(np.mean(vals[-anc_n:]))
        anchor_mean = max(0.05, anchor_raw * (1.03 if is_home else 0.98))
        anchor_delta = anchor_mean - base_mean      # +ve = anchor pulls up, -ve pulls down
        base_mean = (1 - anchor_w) * base_mean + anchor_w * anchor_mean
        base_mean = max(0.05, base_mean)
        # SD from the union of both windows (more stable estimate)
        union_vals = vals[-max(recent_n, anc_n):]
        sd = max(1.0, float(union_vals.std(ddof=0)) * dispersion_scale)

    if drift_flag:
        sd *= role_change.SD_WIDEN

    comp = {"base": round(base_mean, 2), "anchor_delta": round(anchor_delta, 2),
            "opponent": 0.0, "venue": 0.0, "weather": 0.0,
            "role_drift": round(drift, 3)}
    mean = base_mean

    if use_splits and n >= 3:
        # Form-adjusted residual effects (vs the player's local form at the time
        # of each occurrence), so we isolate the condition from form/era drift.
        if opponent is not None and opp_weight:
            mask = (prior["opponent"] == opponent).to_numpy()
            eff, _ = form_adjusted_effect(vals, mask, shrink=split_shrink, max_n=OPP_N)
            comp["opponent"] = round(eff * opp_weight, 2)

        if venue_norm and venue_weight and "venue_norm" in prior:
            mask = (prior["venue_norm"] == venue_norm).to_numpy()
            eff, _ = form_adjusted_effect(vals, mask, shrink=split_shrink, max_n=VENUE_N)
            comp["venue"] = round(eff * venue_weight, 2)

        # Weather: only when the forecast for THIS game is wet and/or windy.
        if forecast is not None and weather_weight and {"wet", "windy"} <= set(prior.columns):
            from ..data import weather as _w
            wadj = 0.0
            if forecast.get("rain_mm", 0.0) >= _w.WET_MM:
                eff, _ = form_adjusted_effect(vals, prior["wet"].to_numpy(bool),
                                              shrink=split_shrink)
                wadj += eff
            if forecast.get("wind_kmh", 0.0) >= _w.WINDY_KMH:
                eff, _ = form_adjusted_effect(vals, prior["windy"].to_numpy(bool),
                                              shrink=split_shrink)
                wadj += eff
            comp["weather"] = round(wadj * weather_weight, 2)

        mean = max(0.05, base_mean + comp["opponent"] + comp["venue"] + comp["weather"])

    comp["projection"] = round(mean, 2)
    return mean, sd, n, comp


def project(player_stats: pd.DataFrame, player: str, stat: str, opponent: str,
            is_home: bool, *, elo: player_elo.PlayerEloModel | None = None,
            venue: str | None = None, forecast: dict | None = None,
            recent_n: int | None = None, elo_weight: float | None = None,
            dispersion_scale: float | None = None,
            use_splits: bool = USE_SPLITS,
            position_table=None, tactical=None) -> PropProjection:
    """Project a player's stat for an upcoming game.

    Layers situational adjustments onto a recency baseline:
      * recent form (recency-weighted, optional opponent-aware Elo blend)
      * last 5 meetings vs ``opponent``
      * last 5 games at ``venue``
      * weather: if ``forecast`` is wet/windy, the player's wet/windy history
      * position concession: how the opponent defends against this position group
      * tactical context: pace/pressure, tagging, game script, teammate absence
        (``tactical`` is a ``tactical.TacticalContext``)
    """
    recent_n = recent_n or RECENT_N_BY_STAT.get(stat, DEFAULT_RECENT_N)
    elo_weight = (ELO_WEIGHT_BY_STAT.get(stat, DEFAULT_ELO_WEIGHT)
                  if elo_weight is None else elo_weight)
    dispersion_scale = (DISPERSION_SCALE_BY_STAT.get(stat, DEFAULT_DISPERSION_SCALE)
                        if dispersion_scale is None else dispersion_scale)

    prior = player_stats[player_stats["player"] == player].sort_values("date").copy()
    dist = "poisson" if stat == "goals" else "nbinom"
    if prior.empty:
        league = float(player_stats[stat].mean()) if stat in player_stats else 0.0
        return PropProjection(player, stat, opponent, is_home, league,
                              max(1.0, league ** 0.5), 0, dist)

    venue_norm = None
    if venue is not None:
        from ..data import stadiums
        venue_norm = stadiums.normalise_venue(venue)
        if "venue" in prior and "venue_norm" not in prior:
            prior["venue_norm"] = prior["venue"].map(stadiums.normalise_venue)

    split_weight = SPLIT_WEIGHT_BY_STAT.get(stat, DEFAULT_SPLIT_WEIGHT)
    decay = DECAY_BY_STAT.get(stat, DEFAULT_DECAY)
    elo_exp = elo.expected(player, opponent, is_home) if elo is not None else None
    mean, sd, n, comp = project_from_history(
        prior, stat, opponent=opponent, venue_norm=venue_norm, is_home=is_home,
        forecast=forecast, elo_exp=elo_exp, recent_n=recent_n,
        elo_weight=elo_weight, dispersion_scale=dispersion_scale,
        use_splits=use_splits, opp_weight=split_weight, venue_weight=split_weight,
        weather_weight=split_weight, decay=decay)

    # Position-group concession adjustment: how the opponent defends against
    # this player's position (Key Defender / Midfielder / Ruck / Forward).
    # Applied after the individual form/opponent splits so it adds a
    # population-level signal on top of the individual-level baseline.
    comp["position_adj"] = 0.0
    comp["position_group"] = None
    if position_table is not None and n >= 3:
        pos_group = position_table.position_of(player)
        comp["position_group"] = pos_group
        pos_delta = position_table.adj(player, opponent, stat, mean)
        if pos_delta != 0.0:
            mean = max(0.05, mean + pos_delta)
            comp["position_adj"] = round(pos_delta, 2)
            comp["projection"] = round(mean, 2)

    # Tactical context: pace/pressure, tagging, game script, teammate absence.
    if tactical is not None and n >= 3:
        from . import tactical as _tact
        team = str(prior["team"].iloc[-1]) if "team" in prior.columns else None
        mean = _tact.apply_tactical(mean, comp, player=player, stat=stat,
                                    opponent=opponent, team=team,
                                    tactical=tactical)

    # Apply the walk-forward's learned per-stat bias correction (live path only;
    # the calibration/backtest call project_from_history directly and skip this).
    from .adjustments import current as _adj
    adj = _adj()
    if adj is not None:
        delta = adj.bias(stat)
        if delta:
            mean = max(0.05, mean + delta)
            comp["learned_bias"] = round(delta, 2)
            comp["projection"] = round(mean, 2)
    return PropProjection(player, stat, opponent, is_home, mean, sd, n, dist, comp)


def project_line(player_stats: pd.DataFrame, player: str, stat: str,
                 opponent: str, is_home: bool, line: float,
                 *, elo: player_elo.PlayerEloModel | None = None,
                 venue: str | None = None, forecast: dict | None = None) -> dict:
    """Convenience: projection + over/under probabilities for a single line."""
    proj = project(player_stats, player, stat, opponent, is_home, elo=elo,
                   venue=venue, forecast=forecast)
    out = proj.as_dict()
    out["line"] = line
    out["prob_over"] = round(proj.prob_over(line), 4)
    out["prob_under"] = round(proj.prob_under(line), 4)
    return out
