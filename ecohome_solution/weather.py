"""
Weather data for EcoHome: live Open-Meteo forecasts with a deterministic mock.

Open-Meteo (https://open-meteo.com) is free, needs no API key, and returns
hourly shortwave radiation, which is exactly the input a PV estimate needs.
If the network is unavailable, or ECOHOME_OFFLINE=1, the mock produces
repeatable data from the same clear-sky model the rest of the project uses.
"""
from __future__ import annotations

import functools
import math
import random
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import httpx

import config
from energy_model import (CONDITION_CLOUD_FACTOR, DEFAULT_HOUSEHOLD_PROFILE, _seed,
                          clear_sky_ghi, pv_output_kwh, solar_elevation_deg)

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HTTP_TIMEOUT = 10.0

# Known locations so the mock (and offline runs) still get sensible coordinates.
KNOWN_LOCATIONS: Dict[str, Tuple[float, float, str]] = {
    "san francisco": (37.7749, -122.4194, "America/Los_Angeles"),
    "los angeles": (34.0522, -118.2437, "America/Los_Angeles"),
    "sacramento": (38.5816, -121.4944, "America/Los_Angeles"),
    "san diego": (32.7157, -117.1611, "America/Los_Angeles"),
    "phoenix": (33.4484, -112.0740, "America/Phoenix"),
    "austin": (30.2672, -97.7431, "America/Chicago"),
    "chicago": (41.8781, -87.6298, "America/Chicago"),
    "st. louis": (38.6270, -90.1994, "America/Chicago"),
    "new york": (40.7128, -74.0060, "America/New_York"),
    "seattle": (47.6062, -122.3321, "America/Los_Angeles"),
    "denver": (39.7392, -104.9903, "America/Denver"),
    "miami": (25.7617, -80.1918, "America/New_York"),
}


def weather_code_to_condition(code: int, is_day: bool = True) -> str:
    """Map WMO weather codes (used by Open-Meteo) to the project's vocabulary."""
    if code in (0, 1):
        return "sunny" if is_day else "clear"
    if code == 2:
        return "partly_cloudy"
    if code == 3:
        return "cloudy"
    if code in (45, 48):
        return "foggy"
    if 51 <= code <= 67 or 80 <= code <= 82:
        return "rainy"
    if 71 <= code <= 77 or code in (85, 86):
        return "snowy"
    if code >= 95:
        return "stormy"
    return "cloudy"


@functools.lru_cache(maxsize=64)
def geocode(location: str) -> Dict[str, object]:
    """Resolve 'City, ST' to coordinates. Falls back to the known table, then the household default."""
    name = (location or DEFAULT_HOUSEHOLD_PROFILE["location"]).split(",")[0].strip()
    key = name.lower()
    if not config.OFFLINE:
        try:
            r = httpx.get(GEOCODE_URL, params={"name": name, "count": 5, "language": "en"},
                          timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            results = r.json().get("results") or []
            # Prefer a US match when the caller wrote a two-letter state code.
            state = location.split(",")[1].strip() if "," in location else ""
            if len(state) == 2:
                us = [x for x in results if x.get("country_code") == "US"]
                results = us or results
            if results:
                top = results[0]
                return {"name": f"{top['name']}, {top.get('admin1', top.get('country', ''))}".strip(", "),
                        "latitude": top["latitude"], "longitude": top["longitude"],
                        "timezone": top.get("timezone", "auto"), "geocoder": "open-meteo"}
        except Exception:
            pass
    lat, lon, tz = KNOWN_LOCATIONS.get(key, KNOWN_LOCATIONS["san francisco"])
    return {"name": location or DEFAULT_HOUSEHOLD_PROFILE["location"], "latitude": lat,
            "longitude": lon, "timezone": tz,
            "geocoder": "built-in table" if key in KNOWN_LOCATIONS else "default (unrecognised location)"}


# ---------------------------------------------------------------------------
# Live API
# ---------------------------------------------------------------------------
def fetch_open_meteo(lat: float, lon: float, days: int = 3, past_days: int = 0,
                     start_date: Optional[date] = None, end_date: Optional[date] = None) -> Dict:
    params = {
        "latitude": lat, "longitude": lon, "timezone": "auto",
        "hourly": "temperature_2m,relative_humidity_2m,cloud_cover,shortwave_radiation,"
                  "wind_speed_10m,precipitation_probability,weather_code,is_day",
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code,is_day,cloud_cover",
        "wind_speed_unit": "kmh",
    }
    if start_date and end_date:
        params["start_date"] = start_date.isoformat()
        params["end_date"] = end_date.isoformat()
    else:
        params["forecast_days"] = days
        if past_days:
            params["past_days"] = past_days
    r = httpx.get(FORECAST_URL, params=params, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _hourly_from_open_meteo(payload: Dict, system_kw: float) -> List[Dict]:
    h = payload["hourly"]
    rows = []
    n = len(h["time"])
    for i, ts in enumerate(h["time"]):
        dt = datetime.fromisoformat(ts)
        # Open-Meteo radiation is the mean over the *preceding* hour, so the value stamped h+1 describes
        # hour h..h+1, which is what every row here means.
        irr = float(h["shortwave_radiation"][i + 1] or 0.0) if i + 1 < n else 0.0
        temp = float(h["temperature_2m"][i])
        is_day = bool(h["is_day"][i])
        rows.append({
            "date": dt.date().isoformat(),
            "hour": dt.hour,
            "datetime": dt.isoformat(timespec="minutes"),
            "temperature_c": round(temp, 1),
            "condition": weather_code_to_condition(int(h["weather_code"][i]), is_day),
            "cloud_cover_pct": h["cloud_cover"][i],
            "solar_irradiance": round(irr, 1),
            "humidity": h["relative_humidity_2m"][i],
            "wind_speed": h["wind_speed_10m"][i],
            "precipitation_probability": (h.get("precipitation_probability") or [None] * len(h["time"]))[i],
            "estimated_solar_kwh": round(pv_output_kwh(irr, temp, system_kw), 2),
        })
    return rows


# ---------------------------------------------------------------------------
# Deterministic mock
# ---------------------------------------------------------------------------
_MOCK_CONDITIONS = ["sunny", "partly_cloudy", "foggy", "cloudy", "rainy"]
_MOCK_WEIGHTS = [0.45, 0.25, 0.12, 0.12, 0.06]


def _seasonal_high_c(lat: float, d: date) -> float:
    """Rough daily high: warmer nearer the equator and in late July."""
    doy = d.timetuple().tm_yday
    annual_mean = 27 - 0.35 * abs(lat)
    swing = 0.2 * abs(lat) - 0.5
    return annual_mean + swing * math.cos(2 * math.pi * (doy - 200) / 365)


def mock_day(location: str, lat: float, lon: float, d: date) -> Dict[str, float | str]:
    rng = random.Random(_seed("wx", location.lower(), d.isoformat()))
    condition = rng.choices(_MOCK_CONDITIONS, weights=_MOCK_WEIGHTS)[0]
    high = _seasonal_high_c(lat, d) + rng.uniform(-3.5, 3.5)
    # A reproducible 'heat wave' roughly one day in twelve.
    if rng.random() < 1 / 12:
        high += 9
        condition = "sunny"
    if condition in ("cloudy", "rainy"):
        high -= 2.5
    low = high - rng.uniform(7, 10)
    return {"condition": condition, "high_c": round(high, 1), "low_c": round(low, 1)}


def mock_hour(location: str, lat: float, lon: float, d: date, hour: int, system_kw: float) -> Dict:
    day = mock_day(location, lat, lon, d)
    rng = random.Random(_seed("wxh", location.lower(), d.isoformat(), hour))
    # Temperature: minimum near 06:00, maximum near 15:00.
    x = (hour - 6) % 24  # hours since the 06:00 minimum
    phase = -math.cos(math.pi * x / 9) if x <= 9 else math.cos(math.pi * (x - 9) / 15)
    temp = day["low_c"] + (day["high_c"] - day["low_c"]) * (phase + 1) / 2
    elev = solar_elevation_deg(d, hour, lat, lon)
    condition = day["condition"]
    # Coastal morning fog burns off by 11:00.
    if condition == "foggy" and hour >= 11:
        condition = "partly_cloudy"
    irr = clear_sky_ghi(elev) * CONDITION_CLOUD_FACTOR[condition] * rng.uniform(0.92, 1.05)
    is_day = elev > 0
    if not is_day and condition == "sunny":
        condition = "clear"
    cloud = {"sunny": 5, "clear": 5, "partly_cloudy": 45, "foggy": 90, "cloudy": 85, "rainy": 95}[condition]
    return {
        "date": d.isoformat(),
        "hour": hour,
        "datetime": f"{d.isoformat()}T{hour:02d}:00",
        "temperature_c": round(temp, 1),
        "condition": condition,
        "cloud_cover_pct": cloud,
        "solar_irradiance": round(max(0.0, irr), 1),
        "humidity": int(rng.uniform(55, 85) if condition in ("sunny", "clear") else rng.uniform(75, 97)),
        "wind_speed": round(rng.uniform(5, 25), 1),
        "precipitation_probability": {"rainy": 80, "cloudy": 20, "foggy": 10}.get(condition, 0),
        "estimated_solar_kwh": round(pv_output_kwh(max(0.0, irr), temp, system_kw), 2),
    }


def mock_hourly(location: str, lat: float, lon: float, start: date, days: int, system_kw: float) -> List[Dict]:
    return [mock_hour(location, lat, lon, start + timedelta(days=i), h, system_kw)
            for i in range(days) for h in range(24)]


# ---------------------------------------------------------------------------
# Public helpers used by tools.py and the sample-data generator
# ---------------------------------------------------------------------------
def summarise_days(hourly: List[Dict]) -> List[Dict]:
    by_day: Dict[str, List[Dict]] = {}
    for row in hourly:
        by_day.setdefault(row["date"], []).append(row)
    days = []
    for d, rows in by_day.items():
        daylight = [r for r in rows if r["solar_irradiance"] > 0]
        conds = [r["condition"] for r in daylight] or [rows[0]["condition"]]
        dominant = max(set(conds), key=conds.count)
        best = sorted(daylight, key=lambda r: r["estimated_solar_kwh"], reverse=True)[:4]
        days.append({
            "date": d,
            "weekday": date.fromisoformat(d).strftime("%A"),
            "condition": dominant,
            "high_c": max(r["temperature_c"] for r in rows),
            "low_c": min(r["temperature_c"] for r in rows),
            "total_estimated_solar_kwh": round(sum(r["estimated_solar_kwh"] for r in rows), 1),
            "peak_solar_hours": sorted(r["hour"] for r in best),
            "max_precipitation_probability": max((r["precipitation_probability"] or 0) for r in rows),
        })
    return days


def get_forecast(location: str, days: int = 3, start_date: Optional[date] = None,
                 system_kw: float = DEFAULT_HOUSEHOLD_PROFILE["solar_system_kw"]) -> Dict:
    """Forecast from today (or start_date) for `days` days; live if possible, mock otherwise."""
    days = max(1, min(int(days), 7))
    geo = geocode(location)
    today = date.today()
    start = start_date or today
    source = "mock (deterministic)"
    current = None
    hourly: List[Dict] = []
    if not config.OFFLINE:
        try:
            if start == today:
                payload = fetch_open_meteo(geo["latitude"], geo["longitude"], days=days)
            else:
                payload = fetch_open_meteo(geo["latitude"], geo["longitude"], start_date=start,
                                           end_date=start + timedelta(days=days - 1))
            hourly = _hourly_from_open_meteo(payload, system_kw)
            c = payload.get("current") or {}
            if c:
                current = {
                    "temperature_c": c.get("temperature_2m"),
                    "condition": weather_code_to_condition(int(c.get("weather_code", 3)), bool(c.get("is_day", 1))),
                    "humidity": c.get("relative_humidity_2m"),
                    "wind_speed": c.get("wind_speed_10m"),
                    "cloud_cover_pct": c.get("cloud_cover"),
                    "observed_at": c.get("time"),
                }
            source = "open-meteo.com (live)"
        except Exception as exc:  # network down, bad date range, rate limit...
            source = f"mock (deterministic) - live API unavailable: {type(exc).__name__}"
            hourly = []
    if not hourly:
        hourly = mock_hourly(geo["name"], geo["latitude"], geo["longitude"], start, days, system_kw)
    if current is None:
        now_row = next((r for r in hourly if r["date"] == today.isoformat() and r["hour"] == datetime.now().hour),
                       hourly[0])
        current = {k: now_row[k] for k in ("temperature_c", "condition", "humidity", "wind_speed", "cloud_cover_pct")}
    return {"geo": geo, "source": source, "current": current, "hourly": hourly, "daily": summarise_days(hourly)}


def get_history(location: str, past_days: int,
                system_kw: float = DEFAULT_HOUSEHOLD_PROFILE["solar_system_kw"]) -> Tuple[List[Dict], str]:
    """Hourly weather for the last `past_days` days plus today (for the sample-data generator)."""
    geo = geocode(location)
    if not config.OFFLINE:
        try:
            payload = fetch_open_meteo(geo["latitude"], geo["longitude"], days=1, past_days=past_days)
            return _hourly_from_open_meteo(payload, system_kw), "open-meteo.com (observed/analysis)"
        except Exception:
            pass
    start = date.today() - timedelta(days=past_days)
    return mock_hourly(geo["name"], geo["latitude"], geo["longitude"], start, past_days + 1, system_kw), "mock"
