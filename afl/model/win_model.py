"""Match-winner model.

A gradient-boosted classifier over the engineered features, wrapped in a
calibrated, persistable object. Probabilities are calibrated (isotonic /
sigmoid) so that "70%" genuinely means ~70% — essential when comparing the
model's number against bookmaker-implied probabilities to find value.

The Elo expected-home-win-prob is itself a strong baseline; the model's job is
to improve on it using form, rest, H2H and weather. ``evaluate`` reports both
so you can see the lift (or lack of it).
"""
from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss

from .. import config
from ..features.build import FEATURE_COLUMNS


@dataclass
class WinModel:
    clf: object
    features: list[str]

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Return home-win probability for each row."""
        Xm = X[self.features].fillna(0.0).to_numpy()
        return self.clf.predict_proba(Xm)[:, 1]

    def save(self, path: Path | None = None) -> Path:
        path = path or (config.MODEL_DIR / "win_model.pkl")
        with open(path, "wb") as fh:
            pickle.dump({"clf": self.clf, "features": self.features}, fh)
        return path

    @classmethod
    def load(cls, path: Path | None = None) -> "WinModel":
        path = path or (config.MODEL_DIR / "win_model.pkl")
        with open(path, "rb") as fh:
            blob = pickle.load(fh)
        return cls(clf=blob["clf"], features=blob["features"])


def _completed(feat: pd.DataFrame) -> pd.DataFrame:
    df = feat[feat["home_win"].notna()].copy()
    df["home_win"] = df["home_win"].astype(int)
    return df


def train(feat: pd.DataFrame, *, features: list[str] | None = None,
          calibrate: bool = True) -> WinModel:
    features = features or FEATURE_COLUMNS
    df = _completed(feat)
    X = df[features].fillna(0.0).to_numpy()
    y = df["home_win"].to_numpy()

    base = GradientBoostingClassifier(
        n_estimators=300, learning_rate=0.03, max_depth=3,
        subsample=0.8, random_state=42)
    if calibrate and len(df) > 400:
        clf = CalibratedClassifierCV(base, method="isotonic", cv=4)
    else:
        clf = base
    clf.fit(X, y)
    return WinModel(clf=clf, features=features)


def time_series_backtest(feat: pd.DataFrame, *, features: list[str] | None = None,
                         min_train: int = 600, step_seasons: bool = True) -> dict:
    """Walk-forward evaluation: train on the past, predict the next season.

    Returns metrics for the model vs the raw Elo baseline so you can judge
    whether the extra features earn their keep.
    """
    features = features or FEATURE_COLUMNS
    df = _completed(feat).sort_values("date").reset_index(drop=True)
    seasons = sorted(df["year"].dropna().unique())

    preds, elos, truth = [], [], []
    for season in seasons:
        train_df = df[df["year"] < season]
        test_df = df[df["year"] == season]
        if len(train_df) < min_train or test_df.empty:
            continue
        model = train(train_df, features=features)
        p = model.predict_proba(test_df)
        preds.extend(p)
        elos.extend(test_df["elo_exp_home"].to_numpy())
        truth.extend(test_df["home_win"].to_numpy())

    if not truth:
        return {"note": "not enough data for a walk-forward backtest"}

    truth = np.array(truth)
    preds = np.clip(np.array(preds), 1e-6, 1 - 1e-6)
    elos = np.clip(np.array(elos), 1e-6, 1 - 1e-6)
    return {
        "n_games": int(len(truth)),
        "model_accuracy": round(accuracy_score(truth, preds > 0.5), 4),
        "model_logloss": round(log_loss(truth, preds), 4),
        "model_brier": round(brier_score_loss(truth, preds), 4),
        "elo_accuracy": round(accuracy_score(truth, elos > 0.5), 4),
        "elo_logloss": round(log_loss(truth, elos), 4),
        "elo_brier": round(brier_score_loss(truth, elos), 4),
    }
