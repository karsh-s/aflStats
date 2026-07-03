"""Tiny count-distribution helpers (Poisson / Negative Binomial).

Implemented in pure Python/NumPy to avoid a SciPy build dependency. Player-prop
lines are small integers, so direct summation of the PMF is fast and exact.
"""
from __future__ import annotations

import math


def poisson_pmf(k: int, mean: float) -> float:
    if mean <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-mean) * mean ** k / math.factorial(k)


def poisson_sf(k: int, mean: float) -> float:
    """P(X > k) for X ~ Poisson(mean)."""
    if k < 0:
        return 1.0
    cdf = sum(poisson_pmf(i, mean) for i in range(0, k + 1))
    return max(0.0, 1.0 - cdf)


def _nb_params(mean: float, sd: float) -> tuple[float, float]:
    """Convert (mean, sd) to NegBinom (r, p). Falls back near-Poisson."""
    var = sd * sd
    if var <= mean:  # not over-dispersed -> approximate with large r
        var = mean * 1.25 + 1e-6
    p = mean / var
    p = min(max(p, 1e-6), 1 - 1e-6)
    r = mean * p / (1 - p)
    r = max(r, 1e-6)
    return r, p


def nbinom_pmf(k: int, r: float, p: float) -> float:
    # P(X=k) = Gamma(k+r)/(k! Gamma(r)) p^r (1-p)^k
    log = (math.lgamma(k + r) - math.lgamma(k + 1) - math.lgamma(r)
           + r * math.log(p) + k * math.log(1 - p))
    return math.exp(log)


def nbinom_sf(k: int, mean: float, sd: float) -> float:
    """P(X > k) for an over-dispersed count with given mean/sd."""
    if k < 0:
        return 1.0
    r, p = _nb_params(mean, sd)
    cdf = sum(nbinom_pmf(i, r, p) for i in range(0, k + 1))
    return min(1.0, max(0.0, 1.0 - cdf))
