"""Role-change detection from stat-profile drift.

A player who moves roles (midfielder to half-back, forward pinch-hitting in
the ruck) keeps racking up disposals but the *mix* of their stats changes:
kicks vs handballs, marks, tackles, clearances, hitouts. The existing form
window can't see this — it averages over both roles and projects a player
who no longer exists.

This module compares the player's recent stat *mix* against their earlier
baseline. When the L1 distance between the two mix vectors crosses a
threshold, the projection reacts three ways (applied in
``player_props.project_from_history``):

  * steepen the recency decay so post-change games dominate the mean
  * damp the flat anchor blend (it drags the mean back to the old role)
  * widen the SD (a role in transition is genuinely less predictable)

The mean is never shifted directly — the signal only reweights and widens.
All computation is NaN-tolerant: the 2026 dataset has rows with missing
profile columns, and the walk-forward backtest passes a minimal prior frame
that may lack them entirely; in both cases detection degrades to a no-op.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Stat-mix columns. Only columns present AND sufficiently populated in the
# prior frame are used; at least MIN_COLS must survive or detection is off.
ROLE_COLS = ["kicks", "handballs", "marks", "tackles", "clearances", "goals", "hitouts"]
MIN_COLS = 4

RECENT_K = 4            # candidate post-change window (games)
BASE_LO, BASE_HI = 5, 14  # baseline = games 5..14 back
MIN_BASELINE = 6        # need >= 6 baseline games to compare against

# L1 distance between 4-game-mean mix vectors on 2026 data: median 0.18,
# p75 0.25, p90 0.32. Genuine positional moves need to stand clear of that
# noise floor, so the flag fires around the 90th percentile only.
DRIFT_THRESHOLD = 0.30

# Backtest (cutoff 2026-06-01): reweighting the mean (steeper decay / damped
# anchor) made drift-flagged games WORSE (disposals sub-MAE 3.68 vs 3.66,
# bias sign flip) — the recent-window mix is too noisy to shift the mean on.
# Widening the SD alone improved ECE (tackles 0.0071 vs 0.0076) at zero MAE
# cost, so the shipped config is SD-only; decay/anchor knobs stay for retuning.
DRIFT_DECAY = 1.0       # 1.0 = no extra decay when flagged (mean untouched)
ANCHOR_DAMP = 1.0       # 1.0 = anchor blend unchanged when flagged
SD_WIDEN = 1.15         # widen SD by this factor when flagged

USE_ROLE_DRIFT = True


def detect_drift(prior: pd.DataFrame) -> tuple[float, bool]:
    """Return (drift, flagged) for a player's chronologically-ordered prior games.

    drift is the L1 distance between the recent and baseline stat-mix vectors;
    0.0 when there isn't enough data to tell.
    """
    if len(prior) < RECENT_K + MIN_BASELINE:
        return 0.0, False

    cols = [c for c in ROLE_COLS if c in prior.columns]
    if len(cols) < MIN_COLS:
        return 0.0, False

    window = prior.tail(BASE_HI + RECENT_K)
    recent = window.tail(RECENT_K)
    base = window.iloc[:-RECENT_K].tail(BASE_HI - BASE_LO + 1)
    if len(base) < MIN_BASELINE:
        return 0.0, False

    # Keep columns non-NaN in at least half the games of BOTH windows.
    keep = [c for c in cols
            if recent[c].notna().mean() >= 0.5 and base[c].notna().mean() >= 0.5]
    if len(keep) < MIN_COLS:
        return 0.0, False

    def mix(df: pd.DataFrame) -> np.ndarray | None:
        vals = df[keep].to_numpy(dtype=float)
        # Per game: each stat / (row sum + 1). +1 guards all-zero rows.
        totals = np.nansum(vals, axis=1, keepdims=True) + 1.0
        per_game = vals / totals
        m = np.nanmean(per_game, axis=0)
        if np.isnan(m).any():
            return None
        s = m.sum()
        return m / s if s > 0 else None

    m_recent, m_base = mix(recent), mix(base)
    if m_recent is None or m_base is None:
        return 0.0, False

    drift = float(np.abs(m_recent - m_base).sum())
    return drift, drift >= DRIFT_THRESHOLD
