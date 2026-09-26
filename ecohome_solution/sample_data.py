"""
Realistic sample data for the EcoHome database.

The starter notebook recorded every device every hour (an EV drawing ~10 kWh
every hour of the day, i.e. ~250 kWh/day), which makes any advice built on it
meaningless.  This generator models discrete device behaviour instead, using
the habits of a household that has *not* optimised yet, so the history holds
genuine, discoverable savings:

* the EV is usually plugged in on arrival (~18:00, on-peak), sometimes on a timer;
* the dishwasher runs after dinner, overlapping the 16:00-21:00 peak;
* the pool pump runs 12:00-18:00, so two hours land in the peak;
* HVAC load follows the outdoor temperature (cooling on hot afternoons).

Costs are computed with the same tariff the pricing tool returns
(energy_model.hourly_rate), so recorded and quoted prices agree.
Solar generation comes from the same PV model the forecast tool uses, fed by
real Open-Meteo weather for the last N days when online (mock otherwise).
"""
from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, List, Tuple

from energy_model import DEFAULT_HOUSEHOLD_PROFILE, effective_rate
from weather import get_history

SEED = 42


def _weather_index(hourly: List[Dict]) -> Dict[Tuple[str, int], Dict]:
    return {(r["date"], r["hour"]): r for r in hourly}


def generate_sample_data(days: int = 30, location: str = None, seed: int = SEED,
                         now: datetime | None = None) -> Dict[str, object]:
    """Return usage rows, generation rows, and provenance for `days` full days plus today so far."""
    rng = random.Random(seed)
    now = now or datetime.now()
    location = location or DEFAULT_HOUSEHOLD_PROFILE["location"]
    weather_rows, weather_source = get_history(location, past_days=days)
    wx = _weather_index(weather_rows)
    start_day = (now - timedelta(days=days)).date()

    usage: List[Dict] = []
    generation: List[Dict] = []
    ev_energy_needed = 20.0  # kWh owed to the car at the start of the window

    def add(ts: datetime, kwh: float, device_type: str, device_name: str):
        if kwh <= 0.005 or ts > now:
            return
        usage.append({"timestamp": ts, "consumption_kwh": round(kwh, 3), "device_type": device_type,
                      "device_name": device_name, "cost_usd": round(kwh * effective_rate(ts), 4)})

    for offset in range(days + 1):
        d = start_day + timedelta(days=offset)
        weekday = d.weekday()
        weekend = weekday >= 5
        day_start = datetime(d.year, d.month, d.day)
        temps = [wx.get((d.isoformat(), h), {}).get("temperature_c", 18.0) for h in range(24)]

        # --- solar generation (daylight hours only, like the starter) ----------
        for h in range(24):
            row = wx.get((d.isoformat(), h))
            ts = day_start + timedelta(hours=h)
            if not row or row["solar_irradiance"] <= 0 or ts > now:
                continue
            gen = row["estimated_solar_kwh"] * rng.uniform(0.95, 1.03)  # panel/inverter noise
            generation.append({"timestamp": ts, "generation_kwh": round(gen, 3),
                               "weather_condition": row["condition"], "temperature_c": row["temperature_c"],
                               "solar_irradiance": row["solar_irradiance"]})

        # --- always-on base load: fridge, networking, standby, lighting -------
        for h in range(24):
            kwh = 0.32 if h < 6 else 0.45 if h < 17 else 0.85 if h < 23 else 0.4
            if not weekend and weekday not in (0, 4) and 9 <= h < 17:
                kwh -= 0.1  # house empty on commute days
            add(day_start + timedelta(hours=h), kwh * rng.uniform(0.85, 1.15), "base_load",
                "Fridge, lighting & electronics")

        # --- HVAC: heat pump driven by outdoor temperature ---------------------
        for h in range(24):
            t = temps[h]
            occupied = weekend or weekday in (0, 4) or h < 8 or h >= 17
            kwh = 0.0
            if t > 24 and occupied and 11 <= h <= 21:
                kwh = min(3.0, (t - 24) * 0.38 + 0.4)
            elif t < 13 and (6 <= h <= 9 or 17 <= h <= 22):
                kwh = min(3.0, (15 - t) * 0.22)
            add(day_start + timedelta(hours=h), kwh * rng.uniform(0.9, 1.1), "HVAC", "Main Heat Pump")

        # --- EV: charge sessions -------------------------------------------------
        ev_energy_needed += DEFAULT_HOUSEHOLD_PROFILE["ev_daily_miles"] * rng.uniform(0.6, 1.4) * 0.25
        if ev_energy_needed > 18 or (weekend and ev_energy_needed > 10):
            if weekend and rng.random() < 0.4:
                start_h = rng.choice([11, 12])         # weekend midday top-up
            elif rng.random() < 0.65:
                start_h = rng.choice([17, 18, 18, 19])  # plug in on arrival: on-peak
            else:
                start_h = 23                            # scheduled overnight charge
            remaining = ev_energy_needed
            h = start_h
            while remaining > 0.05:
                kwh = min(7.4, remaining)
                add(day_start + timedelta(hours=h), kwh, "EV", "Tesla Model 3")
                remaining -= kwh
                h += 1
            ev_energy_needed = 0.0

        # --- dishwasher: after dinner most days ------------------------------------
        if rng.random() < 0.85:
            h = rng.choice([19, 20, 20, 21])
            add(day_start + timedelta(hours=h), 0.75 * rng.uniform(0.9, 1.1), "appliance", "Dishwasher")
            add(day_start + timedelta(hours=h + 1), 0.45 * rng.uniform(0.9, 1.1), "appliance", "Dishwasher")

        # --- laundry: weekday evenings and weekend mornings ----------------------
        if weekday in (1, 3) or weekend:
            h = rng.choice([9, 10]) if weekend else rng.choice([17, 18])
            add(day_start + timedelta(hours=h), 0.5 * rng.uniform(0.9, 1.1), "appliance", "Washing Machine")
            add(day_start + timedelta(hours=h + 1), 2.9 * rng.uniform(0.9, 1.1), "appliance", "Dryer")

        # --- pool pump: 12:00-18:00 (two hours inside the peak) ---------------------
        for h in range(12, 18):
            add(day_start + timedelta(hours=h), 1.1 * rng.uniform(0.95, 1.05), "pool_pump", "Variable-Speed Pool Pump")

        # --- heat pump water heater: morning and evening recovery ----------------
        for h, kwh in ((6, 0.45), (7, 0.55), (8, 0.3), (19, 0.4), (20, 0.5), (21, 0.3)):
            add(day_start + timedelta(hours=h), kwh * rng.uniform(0.85, 1.15), "water_heater", "Heat Pump Water Heater")

    return {"usage": usage, "generation": generation, "weather_source": weather_source,
            "start": datetime.combine(start_day, datetime.min.time()), "end": now}


def seed_preferences(db_manager) -> int:
    """Store the household profile so the agent can personalise from turn one."""
    categories = {
        "comfort": ("comfort_cooling_setpoint_f", "comfort_heating_setpoint_f", "comfort_max_f", "comfort_min_f"),
        "schedule": ("ev_departure_time", "ev_daily_miles", "occupancy"),
        "goal": ("optimization_priority",),
    }
    lookup = {k: cat for cat, keys in categories.items() for k in keys}
    for key, value in DEFAULT_HOUSEHOLD_PROFILE.items():
        db_manager.set_preference(key, value, category=lookup.get(key, "profile"), source="seed")
    return len(DEFAULT_HOUSEHOLD_PROFILE)


def populate_database(db_manager, days: int = 30, seed: int = SEED, verbose: bool = True) -> Dict[str, object]:
    """Reset the database and fill it. Safe to re-run: no duplicate rows."""
    db_manager.reset_database()
    data = generate_sample_data(days=days, seed=seed)
    n_usage = db_manager.bulk_add_usage(data["usage"])
    n_gen = db_manager.bulk_add_generation(data["generation"])
    n_pref = seed_preferences(db_manager)
    totals = defaultdict(float)
    for r in data["usage"]:
        totals[r["device_type"]] += r["consumption_kwh"]
    summary = {"usage_records": n_usage, "generation_records": n_gen, "preferences": n_pref,
               "weather_source": data["weather_source"], "start": data["start"], "end": data["end"],
               "kwh_by_device": {k: round(v, 1) for k, v in sorted(totals.items(), key=lambda kv: -kv[1])}}
    if verbose:
        print(f"Created {n_usage} energy usage records and {n_gen} solar generation records "
              f"({data['start']:%Y-%m-%d} -> {data['end']:%Y-%m-%d %H:%M}); weather: {data['weather_source']}")
    return summary
