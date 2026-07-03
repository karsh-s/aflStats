"""Canonical team-name normalisation across data sources.

Each source spells clubs differently:
  * Squiggle      -> "Sydney", "GWS", "Adelaide"        (our canonical form)
  * AFL Tables    -> "Sydney", "Greater Western Sydney"
  * The Odds API  -> "Sydney Swans", "Greater Western Sydney Giants"

Everything is mapped onto the **Squiggle** spelling so Elo lookups, history
joins, and odds matching all line up.
"""
from __future__ import annotations

# Canonical (Squiggle) names.
CANONICAL = {
    "Adelaide", "Brisbane Lions", "Carlton", "Collingwood", "Essendon",
    "Fremantle", "Geelong", "Gold Coast", "GWS", "Hawthorn", "Melbourne",
    "North Melbourne", "Port Adelaide", "Richmond", "St Kilda", "Sydney",
    "West Coast", "Western Bulldogs",
}

# Any known variant (lower-cased) -> canonical.
_ALIASES = {
    # Odds API full nicknames
    "adelaide crows": "Adelaide",
    "brisbane lions": "Brisbane Lions",
    "carlton blues": "Carlton",
    "collingwood magpies": "Collingwood",
    "essendon bombers": "Essendon",
    "fremantle dockers": "Fremantle",
    "geelong cats": "Geelong",
    "gold coast suns": "Gold Coast",
    "greater western sydney giants": "GWS",
    "gws giants": "GWS",
    "hawthorn hawks": "Hawthorn",
    "melbourne demons": "Melbourne",
    "north melbourne kangaroos": "North Melbourne",
    "kangaroos": "North Melbourne",
    "port adelaide power": "Port Adelaide",
    "richmond tigers": "Richmond",
    "st kilda saints": "St Kilda",
    "sydney swans": "Sydney",
    "west coast eagles": "West Coast",
    "western bulldogs": "Western Bulldogs",
    # AFL Tables / other short forms
    "greater western sydney": "GWS",
    "brisbane": "Brisbane Lions",
    "brisbane bears": "Brisbane Lions",
    "footscray": "Western Bulldogs",
}


def normalise_team(name: str) -> str:
    """Map any known club spelling onto the canonical Squiggle name."""
    if not name:
        return name
    raw = str(name).strip()
    if raw in CANONICAL:
        return raw
    key = raw.lower()
    if key in _ALIASES:
        return _ALIASES[key]
    # Substring fallback: e.g. an unexpected "...Bulldogs" still resolves.
    for alias, canon in _ALIASES.items():
        if alias in key or key in alias:
            return canon
    return raw  # unknown -> leave visible rather than silently dropping
