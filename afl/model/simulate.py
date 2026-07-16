"""Monte Carlo game simulation for same-game multi probabilities.

Stats Insider-style: instead of assuming multi legs are independent, simulate
the whole game N times (default 10,000) and read joint probabilities off the
simulations — legs live and die together inside each simulated game.

Design: a Gaussian copula preserves each player's calibrated marginal
distribution EXACTLY (Poisson for goals, Negative Binomial otherwise, via
probability-integral transform), while shared latent factors induce
within-game correlation:

    w_i = sqrt(rho_game)            * Z_game            (game-wide factor)
        + sqrt(rho_team - rho_game) * Z_team(team_i)    (team factor)
        + sqrt(1 - rho_team)        * eps_i             (player factor)

The factor loadings are MEASURED, not assumed: across 106 games of 2026,
standardised disposal residuals of same-team players correlate at just
+0.04 and cross-team at ~0 — disposals are partly conserved within a game
(one player's extra touch is a teammate's lost one), so true correlation is
far weaker than intuition suggests. The sim therefore reports joint
probabilities close to, but honestly different from, the independence
product — and the framework supports richer correlation as more data arrives.
"""
from __future__ import annotations

import math

import numpy as np

# Measured on 2026 data (3,944 player-games):
#   * same-team residual correlation:            +0.040
#   * cross-team residual correlation:           -0.013
#   * corr(disposal residual, team margin):      +0.124  (goals: +0.119)
# The margin factor is the richer structure: a signed game-dominance shock
# (winners' players lift together, their opponents sink together). Its
# loading lambda=0.124 implies cross-team correlation of -lambda^2 = -0.015,
# which matches the directly-measured -0.013 — one factor explains both.
# The residual same-team factor carries what margin doesn't:
# rho_team - lambda^2 = 0.040 - 0.015 = 0.025.
LAMBDA_MARGIN = 0.124
RHO_TEAM = 0.04

N_SIMS = 10_000
SEED = 42
_MAX_K = 90       # count support cap for CDF tables (disposals rarely > 45)


def _norm_cdf(x: np.ndarray) -> np.ndarray:
    try:
        from scipy.special import ndtr        # scipy ships with sklearn
        return ndtr(x)
    except Exception:
        erf = np.vectorize(math.erf)
        return 0.5 * (1.0 + erf(x / math.sqrt(2.0)))


def _poisson_cdf_table(mean: float) -> np.ndarray:
    pmf = np.empty(_MAX_K + 1)
    pmf[0] = math.exp(-mean) if mean > 0 else 1.0
    for k in range(1, _MAX_K + 1):
        pmf[k] = pmf[k - 1] * mean / k
    return np.clip(np.cumsum(pmf), 0.0, 1.0)


def _nbinom_cdf_table(mean: float, sd: float) -> np.ndarray:
    from ._dist import _nb_params, nbinom_pmf
    r, p = _nb_params(mean, sd)
    pmf = np.array([nbinom_pmf(k, r, p) for k in range(_MAX_K + 1)])
    return np.clip(np.cumsum(pmf), 0.0, 1.0)


def simulate_game(players: list[dict], *, n_sims: int = N_SIMS,
                  seed: int = SEED) -> dict[str, np.ndarray]:
    """Simulate every listed player's stat n_sims times, correlated.

    ``players``: [{"key": str, "mean": float, "sd": float,
                   "dist": "poisson"|"nbinom", "team": str}, ...]
    Returns {key: int array (n_sims,)} whose marginals match the analytic
    distributions exactly (probability-integral transform).
    """
    if not players:
        return {}
    rng = np.random.default_rng(seed)
    teams = sorted({str(p["team"]) for p in players})
    # Signed game-dominance shock: +1 for the first team, -1 for the second.
    # Winners' players rise together while their opponents fall — this single
    # factor reproduces the measured negative cross-team correlation.
    sign = {t: (1.0 if i == 0 else -1.0) for i, t in enumerate(teams)}
    z_margin = rng.standard_normal(n_sims)
    z_team = {t: rng.standard_normal(n_sims) for t in teams}

    a_margin = LAMBDA_MARGIN
    a_team = math.sqrt(max(RHO_TEAM - LAMBDA_MARGIN ** 2, 0.0))
    a_idio = math.sqrt(max(1.0 - RHO_TEAM, 0.0))

    out: dict[str, np.ndarray] = {}
    for p in players:
        t = str(p["team"])
        w = (a_margin * sign[t] * z_margin
             + a_team * z_team[t]
             + a_idio * rng.standard_normal(n_sims))
        u = _norm_cdf(w)
        mean, sd = float(p["mean"]), float(p.get("sd") or max(1.0, p["mean"] ** 0.5))
        if p.get("dist") == "poisson":
            cdf = _poisson_cdf_table(mean)
        else:
            cdf = _nbinom_cdf_table(mean, sd)
        # X = smallest k with CDF(k) >= u  (inverse-CDF sampling)
        out[str(p["key"])] = np.searchsorted(cdf, u, side="left")
    return out


def joint_probability(sims: dict[str, np.ndarray],
                      legs: list[dict]) -> float | None:
    """Fraction of simulated games in which EVERY leg clears its line.

    ``legs``: [{"key": str (player key), "line": float}, ...]
    Returns None if any leg's player wasn't simulated.
    """
    mask: np.ndarray | None = None
    for leg in legs:
        x = sims.get(str(leg["key"]))
        if x is None:
            return None
        hit = x > float(leg["line"])     # 19.5 line -> needs 20+
        mask = hit if mask is None else (mask & hit)
    if mask is None:
        return None
    return float(mask.mean())
