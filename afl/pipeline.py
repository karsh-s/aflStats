"""High-level orchestration shared by the CLI scripts (and a future web app).

Keeps the heavy lifting — loading games, building features, fitting Elo/models —
in one place so each script is a thin wrapper, and so the same calls can back a
Streamlit dashboard later.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import config
from .data import afltables, squiggle
from .features import build as build_mod
from .features import elo as elo_mod
from .model import win_model

GAMES_FILE = config.RAW_DIR / "games.pkl"
PLAYER_FILE = config.RAW_DIR / "player_stats.pkl"
PLAYER_ENRICHED_FILE = config.RAW_DIR / "player_stats_enriched.pkl"
FEATURES_FILE = config.PROCESSED_DIR / "features.pkl"


# ---------------------------------------------------------------------------
# Data loading (with on-disk persistence so re-runs are instant)
# ---------------------------------------------------------------------------
def load_games(start: int, end: int, *, refresh: bool = False) -> pd.DataFrame:
    if GAMES_FILE.exists() and not refresh:
        df = pd.read_pickle(GAMES_FILE)
        have = set(df["year"].unique())
        if set(range(start, end + 1)).issubset(have):
            return df
    df = squiggle.games_range(start, end)
    df.to_pickle(GAMES_FILE)
    return df


def load_player_stats(start: int, end: int, *, refresh: bool = False) -> pd.DataFrame:
    if PLAYER_FILE.exists() and not refresh:
        return pd.read_pickle(PLAYER_FILE)
    df = afltables.season_player_stats_range(start, end)
    if not df.empty:
        df.to_pickle(PLAYER_FILE)
    return df


def enrich_player_stats(*, refresh: bool = False) -> pd.DataFrame:
    """Add per-game weather (rain/wind, wet/windy) and a normalised venue column
    to the scraped box scores, for the opponent/venue/weather prop splits.

    Weather is fetched in one archive call per venue (cheap) and the result is
    persisted, so this only does real work the first time / after --refresh.
    """
    from .data import stadiums, weather

    if PLAYER_ENRICHED_FILE.exists() and not refresh:
        return pd.read_pickle(PLAYER_ENRICHED_FILE)
    base = pd.read_pickle(PLAYER_FILE)
    df = weather.attach_weather(base)
    df["venue_norm"] = df["venue"].map(stadiums.normalise_venue)
    df.to_pickle(PLAYER_ENRICHED_FILE)
    return df


def load_player_stats_enriched() -> pd.DataFrame:
    """Enriched box scores if available, else the raw box scores (so the prop
    model still runs, just without the weather split)."""
    if PLAYER_ENRICHED_FILE.exists():
        return pd.read_pickle(PLAYER_ENRICHED_FILE)
    return pd.read_pickle(PLAYER_FILE)


# ---------------------------------------------------------------------------
# Feature matrix + model
# ---------------------------------------------------------------------------
def build_features(start: int, end: int, *, with_weather: bool = True,
                   refresh: bool = False) -> tuple[pd.DataFrame, elo_mod.TeamElo]:
    games = load_games(start, end, refresh=refresh)
    feats, elo = build_mod.build_matrix(games, with_weather=with_weather)
    feats.to_pickle(FEATURES_FILE)
    return feats, elo


def load_features() -> pd.DataFrame:
    if not FEATURES_FILE.exists():
        raise FileNotFoundError(
            "No feature matrix found. Run scripts/train.py (or build_features) first.")
    return pd.read_pickle(FEATURES_FILE)


def fitted_elo(start: int, end: int, *, refresh: bool = False) -> elo_mod.TeamElo:
    """Return current Elo ratings without rebuilding the whole feature matrix."""
    games = load_games(start, end, refresh=refresh)
    _, elo = elo_mod.run(games)
    return elo


def load_model() -> win_model.WinModel:
    return win_model.WinModel.load()
