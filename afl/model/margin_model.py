"""Predicted-margin model (home score minus away score).

Companion to ``win_model``: same feature matrix, but a gradient-boosted
regressor on the final margin instead of a classifier on the winner. The
predicted margin feeds the game-script adjustment for player props (see
``afl.model.game_script``) — a projected blowout changes how players
accumulate stats.

When no trained pickle exists, ``expected_margin`` falls back to a linear
Elo rule: ``margin ≈ MARGIN_PER_ELO × elo_diff``.
"""
from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error

from .. import config
from ..features.build import FEATURE_COLUMNS, feature_row_for_fixture

# OLS of margin on elo_diff over features.pkl 2015-2026. The GBM does not
# beat this linear rule in walk-forward MAE (26.97 vs 26.86), so the linear
# rule is the default live path; a pickle is only saved when the GBM wins.
MARGIN_PER_ELO = 0.0943


@dataclass
class MarginModel:
    reg: object
    features: list[str]

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Return predicted home margin (points) for each row."""
        Xm = X[self.features].fillna(0.0).to_numpy()
        return self.reg.predict(Xm)

    def save(self, path: Path | None = None) -> Path:
        path = path or (config.MODEL_DIR / "margin_model.pkl")
        with open(path, "wb") as fh:
            pickle.dump({"reg": self.reg, "features": self.features}, fh)
        return path

    @classmethod
    def load(cls, path: Path | None = None) -> "MarginModel":
        path = path or (config.MODEL_DIR / "margin_model.pkl")
        with open(path, "rb") as fh:
            blob = pickle.load(fh)
        return cls(reg=blob["reg"], features=blob["features"])


def _completed(feat: pd.DataFrame) -> pd.DataFrame:
    df = feat[feat["home_win"].notna()].copy()
    df["margin"] = df["hscore"].astype(float) - df["ascore"].astype(float)
    return df


def train(feat: pd.DataFrame, *, features: list[str] | None = None) -> MarginModel:
    features = features or FEATURE_COLUMNS
    df = _completed(feat)
    X = df[features].fillna(0.0).to_numpy()
    y = df["margin"].to_numpy()
    reg = GradientBoostingRegressor(
        n_estimators=300, learning_rate=0.03, max_depth=3,
        subsample=0.8, loss="absolute_error", random_state=42)
    reg.fit(X, y)
    return MarginModel(reg=reg, features=features)


def time_series_backtest(feat: pd.DataFrame, *,
                         features: list[str] | None = None,
                         min_train: int = 600) -> dict:
    """Walk-forward MAE per season, model vs linear-Elo baseline."""
    features = features or FEATURE_COLUMNS
    df = _completed(feat).sort_values("date").reset_index(drop=True)
    seasons = sorted(df["year"].dropna().unique())

    preds, base, truth = [], [], []
    for season in seasons:
        train_df = df[df["year"] < season]
        test_df = df[df["year"] == season]
        if len(train_df) < min_train or test_df.empty:
            continue
        model = train(train_df, features=features)
        preds.extend(model.predict(test_df))
        base.extend(MARGIN_PER_ELO * test_df["elo_diff"].fillna(0.0).to_numpy())
        truth.extend(test_df["margin"].to_numpy())

    if not truth:
        return {"note": "not enough data for a walk-forward backtest"}

    return {
        "n_games": int(len(truth)),
        "model_mae": round(float(mean_absolute_error(truth, preds)), 2),
        "elo_mae": round(float(mean_absolute_error(truth, base)), 2),
    }


def expected_margin(model: MarginModel | None, elo, history: pd.DataFrame,
                    home: str, away: str, venue: str, match_date) -> float:
    """Predicted home margin for an unplayed fixture.

    Falls back to the linear Elo rule when ``model`` is None or the feature
    row can't be built (e.g. weather API unavailable).
    """
    try:
        row = feature_row_for_fixture(elo, history, home, away, venue, match_date)
        if model is not None:
            return float(model.predict(pd.DataFrame([row]))[0])
        return float(MARGIN_PER_ELO * row.get("elo_diff", 0.0))
    except Exception:
        try:
            hga = elo.hga if hasattr(elo, "hga") else 0.0
            return float(MARGIN_PER_ELO * ((elo.rating(home) + hga) - elo.rating(away)))
        except Exception:
            return 0.0
