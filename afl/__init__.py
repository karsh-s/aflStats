"""AFL match-winner and player-prop prediction toolkit.

The package is organised so the same logic can back either the CLI scripts in
``scripts/`` or a future Streamlit/Flask web app:

    afl.data      -- raw data acquisition (Squiggle, AFL Tables, weather, venues)
    afl.features  -- Elo, form, head-to-head, feature assembly
    afl.model     -- match-winner model, player Elo, player-prop projections
    afl.odds      -- The Odds API client + value/edge maths
"""

__version__ = "0.1.0"
