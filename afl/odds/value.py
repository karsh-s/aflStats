"""Turn prices + model probabilities into value signals.

Key ideas:
  * implied probability of decimal odds o is 1/o, but that includes the book's
    margin ("vig"). ``devig`` removes it so two/three-way markets sum to 100%.
  * edge / expected value compares the *model's* probability against the price.
  * Kelly gives a bankroll-fraction stake; we report fractional Kelly because
    full Kelly is famously too aggressive given model uncertainty.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def implied_prob(decimal_odds: float) -> float:
    return 1.0 / decimal_odds if decimal_odds and decimal_odds > 0 else np.nan


def devig(decimal_odds: list[float]) -> list[float]:
    """Normalise a set of mutually-exclusive prices to fair probabilities."""
    raw = np.array([implied_prob(o) for o in decimal_odds], dtype=float)
    total = np.nansum(raw)
    return list(raw / total) if total > 0 else list(raw)


def expected_value(model_prob: float, decimal_odds: float) -> float:
    """EV per 1 unit staked: p*(o-1) - (1-p)."""
    return model_prob * (decimal_odds - 1) - (1 - model_prob)


def edge(model_prob: float, decimal_odds: float) -> float:
    """Model probability minus the book's vig-free implied probability."""
    return model_prob - implied_prob(decimal_odds)


def kelly_fraction(model_prob: float, decimal_odds: float,
                   fraction: float = 0.25) -> float:
    """Fractional-Kelly stake (0 if no edge)."""
    b = decimal_odds - 1
    if b <= 0:
        return 0.0
    f = (model_prob * b - (1 - model_prob)) / b
    return max(0.0, f * fraction)


def evaluate_market(model_prob: float, decimal_odds: float,
                    pair_odds: float | None = None,
                    *, kelly: float = 0.25) -> dict:
    """Full value summary for one selection.

    If ``pair_odds`` (the opposite side's price) is supplied, the implied
    probability is de-vigged against it for a fairer comparison.
    """
    if pair_odds:
        fair = devig([decimal_odds, pair_odds])[0]
    else:
        fair = implied_prob(decimal_odds)
    return {
        "price": decimal_odds,
        "model_prob": round(model_prob, 4),
        "book_implied": round(implied_prob(decimal_odds), 4),
        "book_fair": round(fair, 4),
        "edge": round(model_prob - fair, 4),
        "ev_per_unit": round(expected_value(model_prob, decimal_odds), 4),
        "kelly_stake": round(kelly_fraction(model_prob, decimal_odds, kelly), 4),
        "value": model_prob > fair,
    }


def best_lines(odds_df: pd.DataFrame, *, group_cols: list[str],
               price_col: str = "price") -> pd.DataFrame:
    """Collapse multiple books to the single best (highest) price per selection."""
    if odds_df.empty:
        return odds_df
    idx = odds_df.groupby(group_cols)[price_col].idxmax()
    return odds_df.loc[idx].reset_index(drop=True)
