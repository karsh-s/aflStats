"""Apply the adjustments learned by the walk-forward online run.

``scripts/walkforward.py`` saves what it learned to
``data/models/online_state.json``:

  * ``hga``           -- the home-ground edge it settled on (Elo points)
  * ``cal_a/cal_b``   -- an online logistic recalibration of win probability
  * ``player_bias``   -- per-stat systematic over/under-projection it detected

This module loads those and applies them at *prediction time* so the live
scripts and web app reflect the season's learning. Each category can be toggled
(see the module flags) because — as the walk-forward itself showed — the game
adjustments are well supported but the player bias is marginal and easy to turn
off if you'd rather not chase it.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

from .. import config

STATE_PATH = config.MODEL_DIR / "online_state.json"

# Master switches (the props/value/SGM paths read APPLY_PLAYER_BIAS).
APPLY_GAME_ADJUSTMENTS = True   # learned HGA + win-prob calibration
APPLY_PLAYER_BIAS = True        # per-stat projection bias


@dataclass
class Adjustments:
    hga: float = config.ELO_HGA
    cal_a: float = 1.0
    cal_b: float = 0.0
    player_bias: dict = field(default_factory=dict)
    cutoff_round: int | None = None
    year: int | None = None

    def calibrate(self, p: float) -> float:
        """Recalibrate a win probability with the learned logistic layer."""
        if not APPLY_GAME_ADJUSTMENTS:
            return p
        p = min(max(p, 1e-6), 1 - 1e-6)
        z = math.log(p / (1 - p))
        return 1.0 / (1.0 + math.exp(-(self.cal_a * z + self.cal_b)))

    def bias(self, stat: str) -> float:
        if not APPLY_PLAYER_BIAS:
            return 0.0
        return float(self.player_bias.get(stat, 0.0))

    @property
    def home_ground_edge(self) -> float:
        return self.hga if APPLY_GAME_ADJUSTMENTS else config.ELO_HGA


_cached: Adjustments | None = None
_loaded = False


def current() -> Adjustments | None:
    """Lazily load the saved adjustments (None if the walk-forward hasn't run)."""
    global _cached, _loaded
    if not _loaded:
        _loaded = True
        if STATE_PATH.exists():
            try:
                d = json.loads(STATE_PATH.read_text())
                _cached = Adjustments(
                    hga=float(d.get("hga", config.ELO_HGA)),
                    cal_a=float(d.get("cal_a", 1.0)),
                    cal_b=float(d.get("cal_b", 0.0)),
                    player_bias=dict(d.get("player_bias", {})),
                    cutoff_round=d.get("cutoff_round"), year=d.get("year"))
            except Exception:
                _cached = None
    return _cached


def reload() -> Adjustments | None:
    """Force a re-read (after a fresh walk-forward run)."""
    global _loaded
    _loaded = False
    return current()
