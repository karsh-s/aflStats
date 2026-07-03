"""Central configuration: paths, credentials, and tunable constants.

Values are read from environment variables (optionally a ``.env`` file) so the
same code runs locally and, later, inside a deployed web app.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env sitting at the project root, if present.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# Filesystem layout
# ---------------------------------------------------------------------------
DATA_DIR = Path(os.getenv("AFL_DATA_DIR", PROJECT_ROOT / "data"))
CACHE_DIR = DATA_DIR / "cache"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
MODEL_DIR = DATA_DIR / "models"

for _d in (DATA_DIR, CACHE_DIR, RAW_DIR, PROCESSED_DIR, MODEL_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Credentials / external services
# ---------------------------------------------------------------------------
# The Odds API key (https://the-odds-api.com/). Free tier ~500 requests/month.
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
ODDS_API_REGION = os.getenv("ODDS_API_REGION", "au")  # au books incl. Sportsbet

# Squiggle asks scrapers to identify themselves with a contact address.
USER_AGENT = os.getenv(
    "AFL_USER_AGENT",
    "afl-predictor/0.1 (https://github.com/your/repo; contact via app owner)",
)

# How long cached HTTP responses stay fresh (seconds). Completed historical
# data effectively never changes, so the default is generous.
CACHE_TTL_SECONDS = int(os.getenv("AFL_CACHE_TTL", 60 * 60 * 24))  # 1 day

# ---------------------------------------------------------------------------
# Modelling constants
# ---------------------------------------------------------------------------
ELO_K = float(os.getenv("AFL_ELO_K", 24.0))          # base K-factor
ELO_HGA = float(os.getenv("AFL_ELO_HGA", 35.0))      # home-ground advantage (Elo pts)
ELO_MEAN = 1500.0
ELO_REGRESS = 0.25  # fraction regressed toward mean between seasons
ELO_MOV = True      # scale K by margin of victory

# First season to pull when building a training set from scratch.
DEFAULT_START_SEASON = int(os.getenv("AFL_START_SEASON", 2015))
