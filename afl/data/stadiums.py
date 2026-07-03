"""Venue metadata: coordinates (for weather), roof status, and the teams that
treat each ground as a home venue (for home-ground-advantage adjustments).

Squiggle reports venues with a variety of spellings/sponsor names, so
``normalise_venue`` maps the noisy strings onto canonical keys.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Venue:
    name: str
    lat: float
    lon: float
    roof: bool = False           # fully enclosed / closable roof -> weather-neutral
    timezone: str = "Australia/Melbourne"
    home_teams: tuple[str, ...] = field(default_factory=tuple)


# Canonical venues. home_teams use Squiggle's full team names.
VENUES: dict[str, Venue] = {
    "MCG": Venue("MCG", -37.8200, 144.9834, timezone="Australia/Melbourne",
                 home_teams=("Richmond", "Collingwood", "Melbourne", "Hawthorn",
                             "Carlton", "Essendon")),
    "Marvel Stadium": Venue("Marvel Stadium", -37.8166, 144.9474, roof=True,
                            timezone="Australia/Melbourne",
                            home_teams=("Western Bulldogs", "St Kilda", "Essendon",
                                        "North Melbourne", "Carlton")),
    "Adelaide Oval": Venue("Adelaide Oval", -34.9156, 138.5961,
                           timezone="Australia/Adelaide",
                           home_teams=("Adelaide", "Port Adelaide")),
    "Optus Stadium": Venue("Optus Stadium", -31.9510, 115.8890,
                           timezone="Australia/Perth",
                           home_teams=("West Coast", "Fremantle")),
    "Gabba": Venue("Gabba", -27.4858, 153.0381, timezone="Australia/Brisbane",
                   home_teams=("Brisbane Lions",)),
    "SCG": Venue("SCG", -33.8915, 151.2249, timezone="Australia/Sydney",
                 home_teams=("Sydney",)),
    "Engie Stadium": Venue("Engie Stadium", -33.8430, 151.0630,
                           timezone="Australia/Sydney",
                           home_teams=("GWS",)),  # Sydney Showground / GIANTS Stadium
    "GMHBA Stadium": Venue("GMHBA Stadium", -38.1580, 144.3540,
                           timezone="Australia/Melbourne",
                           home_teams=("Geelong",)),
    "Gold Coast Stadium": Venue("Gold Coast Stadium", -28.0066, 153.3660,
                                timezone="Australia/Brisbane",
                                home_teams=("Gold Coast",)),
    "TIO Stadium": Venue("TIO Stadium", -12.3990, 130.8870,
                         timezone="Australia/Darwin"),
    "Manuka Oval": Venue("Manuka Oval", -35.3180, 149.1340,
                         timezone="Australia/Sydney", home_teams=("GWS",)),
    "Blundstone Arena": Venue("Blundstone Arena", -42.8770, 147.3730,
                              timezone="Australia/Hobart",
                              home_teams=("North Melbourne",)),
    "University of Tasmania Stadium": Venue(
        "University of Tasmania Stadium", -41.4260, 147.1380,
        timezone="Australia/Hobart", home_teams=("Hawthorn", "North Melbourne")),
    "Mars Stadium": Venue("Mars Stadium", -37.5470, 143.8470,
                          timezone="Australia/Melbourne", home_teams=("Western Bulldogs",)),
    "Norwood Oval": Venue("Norwood Oval", -34.9180, 138.6320,
                          timezone="Australia/Adelaide"),
    "People First Stadium": Venue("People First Stadium", -28.0066, 153.3660,
                                  timezone="Australia/Brisbane",
                                  home_teams=("Gold Coast",)),
}


# Map messy Squiggle / AFL Tables venue strings onto canonical keys above.
_ALIASES = {
    "m.c.g.": "MCG",
    "mcg": "MCG",
    "melbourne cricket ground": "MCG",
    "docklands": "Marvel Stadium",
    "marvel stadium": "Marvel Stadium",
    "etihad stadium": "Marvel Stadium",
    "telstra dome": "Marvel Stadium",
    "colonial stadium": "Marvel Stadium",
    "adelaide oval": "Adelaide Oval",
    "optus stadium": "Optus Stadium",
    "perth stadium": "Optus Stadium",
    "gabba": "Gabba",
    "the gabba": "Gabba",
    "brisbane cricket ground": "Gabba",
    "scg": "SCG",
    "sydney cricket ground": "SCG",
    "engie stadium": "Engie Stadium",
    "giants stadium": "Engie Stadium",
    "sydney showground": "Engie Stadium",
    "showground stadium": "Engie Stadium",
    "spotless stadium": "Engie Stadium",
    "gmhba stadium": "GMHBA Stadium",
    "kardinia park": "GMHBA Stadium",
    "simonds stadium": "GMHBA Stadium",
    "skilled stadium": "GMHBA Stadium",
    "gold coast stadium": "Gold Coast Stadium",
    "metricon stadium": "People First Stadium",
    "people first stadium": "People First Stadium",
    "carrara": "People First Stadium",
    "tio stadium": "TIO Stadium",
    "marrara oval": "TIO Stadium",
    "manuka oval": "Manuka Oval",
    "blundstone arena": "Blundstone Arena",
    "bellerive oval": "Blundstone Arena",
    "university of tasmania stadium": "University of Tasmania Stadium",
    "utas stadium": "University of Tasmania Stadium",
    "york park": "University of Tasmania Stadium",
    "aurora stadium": "University of Tasmania Stadium",
    "mars stadium": "Mars Stadium",
    "eureka stadium": "Mars Stadium",
    "norwood oval": "Norwood Oval",
}


def normalise_venue(raw: str) -> str:
    """Return the canonical venue key for a raw venue string (best effort)."""
    if not raw:
        return ""
    key = raw.strip().lower()
    if key in _ALIASES:
        return _ALIASES[key]
    # direct match against canonical names
    for canon in VENUES:
        if key == canon.lower():
            return canon
    return raw.strip()  # unknown -> pass through so it's at least visible


def get_venue(raw: str) -> Venue | None:
    return VENUES.get(normalise_venue(raw))


def is_home_ground(team: str, raw_venue: str) -> bool:
    venue = get_venue(raw_venue)
    return bool(venue and team in venue.home_teams)
