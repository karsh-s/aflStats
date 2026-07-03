"""Weather features via the Open-Meteo APIs (free, no key).

* Historical archive  -> for building the training set from past games.
* Forecast            -> for upcoming fixtures (up to ~16 days out).

Roofed venues (Marvel Stadium) are returned as weather-neutral.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from .. import http
from . import stadiums

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
FORECAST = "https://api.open-meteo.com/v1/forecast"

_DAILY = "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max"

# Returned for indoor venues / when no data is available.
NEUTRAL = {"temp_max": 21.0, "temp_min": 14.0, "rain_mm": 0.0,
           "wind_kmh": 8.0, "roofed": True}


def _parse_daily(payload: dict) -> dict:
    daily = payload.get("daily", {})
    def first(key, default):
        vals = daily.get(key) or []
        return vals[0] if vals and vals[0] is not None else default
    return {
        "temp_max": float(first("temperature_2m_max", NEUTRAL["temp_max"])),
        "temp_min": float(first("temperature_2m_min", NEUTRAL["temp_min"])),
        "rain_mm": float(first("precipitation_sum", 0.0)),
        "wind_kmh": float(first("wind_speed_10m_max", NEUTRAL["wind_kmh"])),
        "roofed": False,
    }


def weather_for(raw_venue: str, when: datetime | date) -> dict:
    """Best-effort daily weather for a venue/date.

    Falls back to a neutral profile for indoor grounds, unknown venues, or API
    errors, so feature building never crashes on a single bad lookup.
    """
    venue = stadiums.get_venue(raw_venue)
    if venue is None or venue.roof:
        return dict(NEUTRAL)

    d = when.date() if isinstance(when, datetime) else when
    day = d.isoformat()
    today = date.today()
    base = ARCHIVE if d < today else FORECAST
    params = {
        "latitude": round(venue.lat, 3),
        "longitude": round(venue.lon, 3),
        "daily": _DAILY,
        "timezone": venue.timezone,
        "start_date": day,
        "end_date": day,
    }
    if base == FORECAST:
        # forecast endpoint uses start_date/end_date too but caps ~16 days
        params["forecast_days"] = 16
        params.pop("start_date", None)
        params.pop("end_date", None)
    try:
        payload = http.get_json(base, params=params)
    except Exception:
        return dict(NEUTRAL)

    if base == FORECAST:
        # pick the row matching the requested date
        daily = payload.get("daily", {})
        times = daily.get("time") or []
        if day in times:
            i = times.index(day)
            def pick(key, default):
                vals = daily.get(key) or []
                return vals[i] if i < len(vals) and vals[i] is not None else default
            return {
                "temp_max": float(pick("temperature_2m_max", NEUTRAL["temp_max"])),
                "temp_min": float(pick("temperature_2m_min", NEUTRAL["temp_min"])),
                "rain_mm": float(pick("precipitation_sum", 0.0)),
                "wind_kmh": float(pick("wind_speed_10m_max", NEUTRAL["wind_kmh"])),
                "roofed": False,
            }
        return dict(NEUTRAL)
    return _parse_daily(payload)


# ---------------------------------------------------------------------------
# Bulk historical weather (one archive call per venue) + player-stat enrichment
# ---------------------------------------------------------------------------
# A game is treated as wet/windy above these daily thresholds.
WET_MM = 1.0
WINDY_KMH = 30.0


def daily_history(raw_venue: str, start: "date | datetime",
                  end: "date | datetime") -> dict:
    """Map ISO-date -> {rain_mm, wind_kmh, temp_max} for a venue, in ONE call.

    Roofed/unknown venues return an empty map (callers treat as weather-neutral).
    """
    venue = stadiums.get_venue(raw_venue)
    if venue is None or venue.roof:
        return {}
    s = (start.date() if isinstance(start, datetime) else start).isoformat()
    e = (end.date() if isinstance(end, datetime) else end).isoformat()
    try:
        payload = http.get_json(ARCHIVE, params={
            "latitude": round(venue.lat, 3),
            "longitude": round(venue.lon, 3),
            "daily": _DAILY,
            "timezone": venue.timezone,
            "start_date": s,
            "end_date": e,
        })
    except Exception:
        return {}
    daily = payload.get("daily", {})
    times = daily.get("time") or []
    rain = daily.get("precipitation_sum") or []
    wind = daily.get("wind_speed_10m_max") or []
    tmax = daily.get("temperature_2m_max") or []
    out = {}
    for i, day in enumerate(times):
        out[day] = {
            "rain_mm": float(rain[i]) if i < len(rain) and rain[i] is not None else 0.0,
            "wind_kmh": float(wind[i]) if i < len(wind) and wind[i] is not None else NEUTRAL["wind_kmh"],
            "temp_max": float(tmax[i]) if i < len(tmax) and tmax[i] is not None else NEUTRAL["temp_max"],
        }
    return out


def attach_weather(player_stats):
    """Return a copy of player_stats with rain_mm/wind_kmh/wet/windy columns.

    Looks up each venue's full date range in a single archive request, so the
    whole dataset costs ~one call per venue rather than one per game.
    """
    import pandas as pd

    df = player_stats.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["rain_mm"] = float("nan")
    df["wind_kmh"] = float("nan")

    for raw_venue, grp in df.groupby("venue"):
        lo, hi = grp["date"].min(), grp["date"].max()
        hist = daily_history(raw_venue, lo, hi)
        if not hist:
            continue  # roofed/unknown -> leave NaN (neutral)
        keys = grp["date"].dt.strftime("%Y-%m-%d")
        df.loc[grp.index, "rain_mm"] = keys.map(lambda d: hist.get(d, {}).get("rain_mm")).values
        df.loc[grp.index, "wind_kmh"] = keys.map(lambda d: hist.get(d, {}).get("wind_kmh")).values

    df["wet"] = df["rain_mm"] >= WET_MM
    df["windy"] = df["wind_kmh"] >= WINDY_KMH
    return df
