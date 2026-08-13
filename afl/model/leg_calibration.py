"""Empirical calibration of SGM leg probabilities against settled results.

Post-mortem finding (936 settled legs across R16-R19 2026): the raw model is
systematically OVERCONFIDENT on the legs it selects — it claimed 80.2% and
delivered 68.2%, with a 10-14 point gap in every probability bucket. Worse,
the bookmaker's implied probability beat the model outright (Brier 0.204 vs
0.215), so the "edge" the optimiser was chasing was largely model error.

Some of that gap is selection bias by construction: we only ever bet legs the
model rated ABOVE the market, which is exactly the sample where model noise
looks like edge (winner's curse). That does not make the gap harmless — it
means legs chosen this way need correcting, which is precisely what this
module does.

The fix is a logistic recalibration fitted on settled legs:

    logit(p_true) = w_model * logit(p_model) + w_market * logit(p_market) + b

Fitted weights (~0.43 model / 0.53 market, intercept -0.44) shrink confidence
and lean on the market, which the out-of-sample test confirms: Brier improves
from 0.2296 (raw model) to 0.2122 (calibrated). Refit with
``scripts/fit_leg_calibration.py`` as more rounds settle.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

CALIB_PATH = Path(__file__).parent.parent.parent / "api" / "data" / "leg_calibration.json"

# Fallback if the file is missing: identity (no calibration).
_DEFAULT = {"w_model": 1.0, "w_market": 0.0, "intercept": 0.0}

_cache: dict | None = None

USE_CALIBRATION = True


def _params() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(CALIB_PATH.read_text())
        except Exception:
            _cache = dict(_DEFAULT)
    return _cache


def invalidate_cache() -> None:
    global _cache
    _cache = None


def _logit(p: float) -> float:
    p = min(max(float(p), 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def calibrate(model_prob: float, odds: float | None) -> float:
    """Return the calibrated probability for a leg.

    ``odds`` are the bookmaker's decimal odds (its implied probability is the
    market signal). When odds are unavailable the market term is dropped and
    the model logit is rescaled so the transform stays sensible.
    """
    if not USE_CALIBRATION:
        return float(model_prob)
    p = _params()
    wm, wk, b = p["w_model"], p.get("w_market", 0.0), p["intercept"]
    lo = _logit(model_prob)
    if odds and odds > 1.0 and wk:
        z = wm * lo + wk * _logit(1.0 / float(odds)) + b
    else:
        # No market: keep the same total shrink by folding the market weight
        # onto the model logit (it is the only signal available).
        z = (wm + wk) * lo + b
    return 1.0 / (1.0 + math.exp(-z))
