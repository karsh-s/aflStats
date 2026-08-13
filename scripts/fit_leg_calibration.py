#!/usr/bin/env python3
"""Refit the SGM leg-probability calibration from settled tracker bets.

Run after each round so the correction tracks the model's current bias:

    .venv/bin/python scripts/fit_leg_calibration.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression

ROOT = Path(__file__).resolve().parent.parent
TRACKER = ROOT / "api" / "data" / "multi_tracker.json"
OUT = ROOT / "api" / "data" / "leg_calibration.json"


def _logit(p: float) -> float:
    p = min(max(float(p), 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def main() -> None:
    data = json.loads(TRACKER.read_text())
    bets = [b for b in data["bets"] if b["status"] in ("won", "lost")]
    uniq: dict = {}
    for b in bets:
        for l in b["legs"]:
            if l.get("result") is None:
                continue
            # raw model prob if stored, else the (possibly calibrated) prob
            raw = l.get("prob_raw", l.get("prob"))
            uniq[(b["game"], l["player"], l["milestone"], l["stat"])] = (
                raw, l.get("odds"), 1.0 if l["result"] else 0.0)
    rows = [r for r in uniq.values() if r[0] and r[1]]
    if len(rows) < 100:
        print(f"Only {len(rows)} settled legs — need >=100 to refit. Aborting.")
        return
    X = np.array([[_logit(p), _logit(1.0 / o)] for p, o, _ in rows])
    y = np.array([r[2] for r in rows])
    m = LogisticRegression().fit(X, y)
    out = {
        "w_model": float(m.coef_[0][0]),
        "w_market": float(m.coef_[0][1]),
        "intercept": float(m.intercept_[0]),
        "n_legs": int(len(y)),
        "raw_model_mean": float(np.mean(X[:, 0] > 0)),
        "actual_hit_rate": float(y.mean()),
    }
    OUT.write_text(json.dumps(out, indent=2))
    print(f"Fitted on {len(y)} legs -> {OUT}")
    print(f"  w_model={out['w_model']:.3f} w_market={out['w_market']:.3f} "
          f"intercept={out['intercept']:.3f}")
    print(f"  actual hit rate {out['actual_hit_rate']:.1%}")


if __name__ == "__main__":
    main()
