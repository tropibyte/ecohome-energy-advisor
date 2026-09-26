"""
Shared physical and economic model for EcoHome.

One module owns the time-of-use tariff, the clear-sky solar model, the PV
output model and the default household profile.  The sample-data notebook,
the pricing tool, the weather mock and the schedule optimiser all import from
here, so a cost recorded in the database is the same cost the agent quotes.
"""
from __future__ import annotations

import hashlib
import math
import random
from datetime import date, datetime, timedelta
from typing import Dict, List

# ---------------------------------------------------------------------------
# Household profile (seeded into the user_preferences table by notebook 01)
# ---------------------------------------------------------------------------
DEFAULT_HOUSEHOLD_PROFILE: Dict[str, object] = {
    "location": "San Francisco, CA",
    "latitude": 37.7749,
    "longitude": -122.4194,
    "solar_system_kw": 7.2,
    "battery_capacity_kwh": 13.5,
    "battery_power_kw": 5.0,
    "ev_model": "Tesla Model 3 Long Range",
    "ev_battery_kwh": 75.0,
    "ev_charger_kw": 7.7,
    "ev_efficiency_kwh_per_mile": 0.25,
    "ev_daily_miles": 35,
    "ev_departure_time": "07:30",
    "hvac_type": "3-ton heat pump",
    "hvac_power_kw": 3.0,
    "comfort_cooling_setpoint_f": 76,
    "comfort_heating_setpoint_f": 68,
    "comfort_max_f": 78,
    "comfort_min_f": 66,
    "pool_pump_kw": 1.1,
    "pool_pump_hours_per_day": 6,
    "dishwasher_kwh_per_cycle": 1.2,
    "washer_kwh_per_cycle": 0.5,
    "dryer_kwh_per_cycle": 3.0,
    "water_heater_type": "heat pump water heater",
    "optimization_priority": "balanced",  # cost | carbon | comfort | balanced
    "occupancy": "Two adults; one works from home Mon/Fri",
}

# Typical device loads used by the schedule optimiser when the caller does not
# supply energy/duration.  kWh per run and run length in hours.
DEVICE_LOADS: Dict[str, Dict[str, float]] = {
    "ev": {"energy_kwh": 30.0, "power_kw": 7.7},
    "dishwasher": {"energy_kwh": 1.2, "power_kw": 0.6},
    "washing_machine": {"energy_kwh": 0.5, "power_kw": 0.5},
    "dryer": {"energy_kwh": 3.0, "power_kw": 3.0},
    "pool_pump": {"energy_kwh": 6.6, "power_kw": 1.1},
    "hvac_precool": {"energy_kwh": 4.5, "power_kw": 3.0},
    "water_heater": {"energy_kwh": 2.0, "power_kw": 0.5},
    "battery": {"energy_kwh": 13.5, "power_kw": 5.0},
}

# Average grid carbon intensity (kg CO2 per kWh).  California grid average is
# far below the US average because of hydro, nuclear and utility solar.
GRID_CO2_KG_PER_KWH = {"CA": 0.22, "US": 0.37}
# Evening peak hours in CA are served by gas peakers, so a kWh moved out of the
# peak window displaces dirtier generation than the average.
PEAK_MARGINAL_CO2_KG_PER_KWH = 0.45

# ---------------------------------------------------------------------------
# Time-of-use tariff (mock, modelled on California residential TOU-EV plans)
# ---------------------------------------------------------------------------
TARIFF = {
    "name": "EcoHome Mock TOU-EV (modelled on California residential time-of-use plans)",
    "currency": "USD",
    "periods": {
        "off_peak": {"rate": 0.22, "demand_charge": 0.00, "window": "22:00-07:00"},
        "mid_peak": {"rate": 0.32, "demand_charge": 0.02, "window": "07:00-10:00, 15:00-16:00, 21:00-22:00"},
        "solar_midday": {"rate": 0.24, "demand_charge": 0.00, "window": "10:00-15:00"},
        "on_peak": {"rate": 0.48, "demand_charge": 0.05, "window": "16:00-21:00 (weekdays)"},
        "critical_peak": {"rate": 0.96, "demand_charge": 0.10, "window": "16:00-21:00 on event days"},
    },
    "solar_export_credit": 0.05,  # NEM 3.0-style export credit, $/kWh
}


def is_us_dst(d: date) -> bool:
    """US daylight saving: second Sunday of March to first Sunday of November."""
    march = date(d.year, 3, 8)
    dst_start = march + timedelta(days=(6 - march.weekday()) % 7)
    nov = date(d.year, 11, 1)
    dst_end = nov + timedelta(days=(6 - nov.weekday()) % 7)
    return dst_start <= d < dst_end


def _seed(*parts: object) -> int:
    """Stable seed from arbitrary values (Python's hash() is salted per process)."""
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(digest[:12], 16)


def is_critical_peak_day(d: date) -> bool:
    """Deterministic 'grid emergency' days, roughly one weekday in seven.

    Real utilities announce critical-peak events a day ahead during heat waves;
    the mock reproduces that as a reproducible pseudo-random calendar.
    """
    if d.weekday() >= 5:
        return False
    return _seed("cpp", d.isoformat()) % 7 == 3


def tou_period(hour: int, d: date) -> str:
    weekend = d.weekday() >= 5
    if hour >= 22 or hour < 7:
        return "off_peak"
    if 10 <= hour < 15:
        return "solar_midday"
    if 16 <= hour < 21:
        if weekend:
            return "mid_peak"
        return "critical_peak" if is_critical_peak_day(d) else "on_peak"
    return "mid_peak"


def daily_price_factor(d: date) -> float:
    """+/-4% day-to-day drift standing in for the wholesale-indexed component."""
    rng = random.Random(_seed("price", d.isoformat()))
    return round(1.0 + rng.uniform(-0.04, 0.04), 4)


def hourly_rate(hour: int, d: date) -> Dict[str, object]:
    period = tou_period(hour, d)
    spec = TARIFF["periods"][period]
    factor = daily_price_factor(d)
    rate = round(spec["rate"] * factor, 4)
    demand = round(spec["demand_charge"], 4)
    return {
        "hour": hour,
        "time": f"{hour:02d}:00-{(hour + 1) % 24:02d}:00",
        "rate": rate,
        "period": period,
        "demand_charge": demand,
        "effective_rate": round(rate + demand, 4),
    }


def effective_rate(ts: datetime) -> float:
    return hourly_rate(ts.hour, ts.date())["effective_rate"]


# ---------------------------------------------------------------------------
# Solar geometry and PV output
# ---------------------------------------------------------------------------
CONDITION_CLOUD_FACTOR = {
    "sunny": 1.0,
    "clear": 1.0,
    "partly_cloudy": 0.65,
    "foggy": 0.45,
    "cloudy": 0.30,
    "rainy": 0.12,
    "stormy": 0.08,
    "snowy": 0.15,
}


def solar_elevation_deg(d: date, hour: float, latitude: float, longitude: float,
                        utc_offset_std: float | None = None) -> float:
    """Approximate solar elevation for the middle of a local clock hour."""
    n = d.timetuple().tm_yday
    decl = math.radians(23.45) * math.sin(math.radians(360 / 365 * (284 + n)))
    if utc_offset_std is None:
        utc_offset_std = round(longitude / 15)
    std_meridian = 15 * utc_offset_std
    clock = hour + 0.5 - (1 if is_us_dst(d) else 0)
    solar_time = clock + (longitude - std_meridian) * 4 / 60
    omega = math.radians(15 * (solar_time - 12))
    lat = math.radians(latitude)
    sin_el = math.sin(lat) * math.sin(decl) + math.cos(lat) * math.cos(decl) * math.cos(omega)
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_el))))


def clear_sky_ghi(elevation_deg: float) -> float:
    """Haurwitz clear-sky global horizontal irradiance, W/m^2."""
    if elevation_deg <= 0:
        return 0.0
    cos_z = math.sin(math.radians(elevation_deg))
    return 1098 * cos_z * math.exp(-0.057 / cos_z)


def pv_output_kwh(irradiance_w_m2: float, temperature_c: float,
                  system_kw: float = DEFAULT_HOUSEHOLD_PROFILE["solar_system_kw"]) -> float:
    """Energy produced in one hour by a PV array.

    0.86 system derate (inverter, wiring, soiling) and -0.4%/degC cell
    temperature loss above 25 degC; cell temperature is estimated from ambient
    plus irradiance heating.
    """
    if irradiance_w_m2 <= 0:
        return 0.0
    cell_temp = temperature_c + 0.03 * irradiance_w_m2
    temp_factor = 1 - 0.004 * max(0.0, cell_temp - 25)
    return max(0.0, system_kw * irradiance_w_m2 / 1000 * 0.86 * temp_factor)


def co2_kg(kwh: float, peak: bool = False, region: str = "CA") -> float:
    factor = PEAK_MARGINAL_CO2_KG_PER_KWH if peak else GRID_CO2_KG_PER_KWH.get(region, 0.37)
    return kwh * factor


def next_days_table(now: datetime, days: int = 8) -> List[Dict[str, str]]:
    """Date lookup the agent uses to resolve 'tomorrow', 'Wednesday', etc."""
    out = []
    for i in range(days):
        d = (now + timedelta(days=i)).date()
        label = "today" if i == 0 else "tomorrow" if i == 1 else ""
        out.append({"date": d.isoformat(), "weekday": d.strftime("%A"), "label": label})
    return out
