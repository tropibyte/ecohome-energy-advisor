"""
Tools for EcoHome Energy Advisor Agent

Required tools (rubric): get_weather_forecast, get_electricity_prices, search_energy_tips.
Starter tools (kept, bugs fixed): query_energy_usage, query_solar_generation,
get_recent_energy_summary, calculate_energy_savings.
Added tools: optimize_device_schedule, analyze_usage_patterns, predict_energy_usage,
get_user_preferences, update_user_preference.

Every tool returns a JSON-serialisable dict and never raises: failures come
back as {"error": ...} so the agent can explain or recover instead of crashing.
"""
import json
import math
import os
import random
from collections import Counter, defaultdict
from datetime import date as date_cls, datetime, timedelta
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool

import config
import rag
import weather as wx
from energy_model import (DEFAULT_HOUSEHOLD_PROFILE, DEVICE_LOADS, GRID_CO2_KG_PER_KWH,
                          PEAK_MARGINAL_CO2_KG_PER_KWH, TARIFF, hourly_rate, is_critical_peak_day, tou_period)
from models.energy import DatabaseManager

# Initialize database manager
db_manager = DatabaseManager(str(config.DB_PATH))

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def parse_date(value: Optional[str], today: Optional[date_cls] = None) -> date_cls:
    """Accept YYYY-MM-DD, ISO datetimes, 'today'/'tomorrow'/'yesterday' or a weekday name."""
    today = today or date_cls.today()
    if value is None or str(value).strip() == "":
        return today
    v = str(value).strip().lower()
    if v == "today":
        return today
    if v == "tomorrow":
        return today + timedelta(days=1)
    if v == "yesterday":
        return today - timedelta(days=1)
    for prefix in ("next ", "this "):
        if v.startswith(prefix):
            v = v[len(prefix):]
    if v in _WEEKDAYS:
        delta = (_WEEKDAYS.index(v) - today.weekday()) % 7
        return today + timedelta(days=delta)
    return datetime.strptime(v[:10], "%Y-%m-%d").date()


def _household(key: str):
    try:
        prefs = db_manager.get_preferences()
    except Exception:
        prefs = {}
    return prefs.get(key, DEFAULT_HOUSEHOLD_PROFILE.get(key))


_DEVICE_ALIASES = {
    "ev": "EV", "electric vehicle": "EV", "electric car": "EV", "car": "EV", "tesla": "EV",
    "hvac": "HVAC", "ac": "HVAC", "air conditioner": "HVAC", "heat pump": "HVAC", "thermostat": "HVAC",
    "heating": "HVAC", "cooling": "HVAC",
    "appliance": "appliance", "appliances": "appliance",
    "pool": "pool_pump", "pool pump": "pool_pump", "pool_pump": "pool_pump",
    "water heater": "water_heater", "water_heater": "water_heater",
    "base": "base_load", "base_load": "base_load", "always on": "base_load",
}


def _matches_device(record, device_type: Optional[str]) -> bool:
    """Case-insensitive match on device_type, with aliases, or on device_name (e.g. 'dishwasher')."""
    if not device_type:
        return True
    wanted = device_type.strip().lower()
    canonical = _DEVICE_ALIASES.get(wanted)
    if canonical and (record.device_type or "").lower() == canonical.lower():
        return True
    if (record.device_type or "").lower() == wanted:
        return True
    return wanted.replace("_", " ") in (record.device_name or "").lower()


def _date_range(start_date: str, end_date: str):
    start = parse_date(start_date)
    end = parse_date(end_date)
    if end < start:
        start, end = end, start
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end, datetime.min.time()) + timedelta(days=1)
    return start, end, start_dt, end_dt


def _no_data_hint() -> Dict[str, Any]:
    rng = db_manager.get_data_range()
    return {"available_data_range": rng,
            "hint": "No rows in that range. Query dates inside available_data_range."
            if rng["first"] else "The database is empty - run 01_db_setup.ipynb first."}


# ---------------------------------------------------------------------------
# Required tool 1: weather forecast
# ---------------------------------------------------------------------------
@tool
def get_weather_forecast(location: str = "San Francisco, CA", days: int = 3,
                         start_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Get weather forecast for a specific location and number of days.

    Uses the free Open-Meteo API (live data, no key needed) and falls back to a
    deterministic mock if the API is unreachable. Each hour includes solar
    irradiance and the estimated output of the household's PV array, so the
    result can be used directly to plan solar-powered device runs.

    Args:
        location (str): Location to get weather for (e.g., "San Francisco, CA")
        days (int): Number of days to forecast (1-7), starting today
        start_date (str): Optional first day (YYYY-MM-DD, 'tomorrow' or a weekday name);
            defaults to today

    Returns:
        Dict[str, Any]: Weather forecast data including temperature, conditions, and solar irradiance:
        location, source, forecast_days, current conditions, a per-day summary
        (high/low, dominant condition, total estimated solar kWh, peak solar hours)
        and an hourly list (hour, temperature_c, condition, solar_irradiance W/m2,
        humidity, wind_speed km/h, estimated_solar_kwh).
    """
    try:
        days = max(1, min(int(days or 3), 7))
        start = parse_date(start_date) if start_date else None
        system_kw = float(_household("solar_system_kw") or 7.2)
        fc = wx.get_forecast(location or DEFAULT_HOUSEHOLD_PROFILE["location"], days=days,
                             start_date=start, system_kw=system_kw)
        forecast = {
            "location": fc["geo"]["name"],
            "coordinates": {"latitude": fc["geo"]["latitude"], "longitude": fc["geo"]["longitude"]},
            "timezone": fc["geo"]["timezone"],
            "source": fc["source"],
            "forecast_days": days,
            "solar_system_kw": system_kw,
            "current": fc["current"],
            "daily": fc["daily"],
            "hourly": fc["hourly"],
            "units": {"temperature": "C", "solar_irradiance": "W/m2", "wind_speed": "km/h",
                      "estimated_solar_kwh": "kWh produced in that hour by the household PV array"},
        }
        return forecast
    except Exception as e:
        return {"error": f"Failed to get weather forecast: {str(e)}"}


# ---------------------------------------------------------------------------
# Required tool 2: electricity prices
# ---------------------------------------------------------------------------
@tool
def get_electricity_prices(date: str = None) -> Dict[str, Any]:
    """
    Get electricity prices for a specific date or current day.

    Time-of-use tariff with off-peak (22:00-07:00), solar-midday (10:00-15:00),
    mid-peak and on-peak (16:00-21:00 weekdays) periods. On grid-emergency days
    the on-peak window becomes a critical-peak event with roughly double prices.

    Args:
        date (str): Date in YYYY-MM-DD format (defaults to today). Also accepts
            'today', 'tomorrow' or a weekday name such as 'Wednesday'.

    Returns:
        Dict[str, Any]: Electricity pricing data with hourly rates. Each hour has
        rate ($/kWh energy charge), period, demand_charge ($/kWh adder, 0 off-peak)
        and effective_rate (rate + demand_charge, the number to use for costs),
        plus a summary with the cheapest and most expensive hours.
    """
    try:
        d = parse_date(date)
        hourly_rates = [hourly_rate(h, d) for h in range(24)]
        by_cost = sorted(hourly_rates, key=lambda r: (r["effective_rate"], r["hour"]))
        eff = [r["effective_rate"] for r in hourly_rates]
        cpp = any(r["period"] == "critical_peak" for r in hourly_rates)
        periods: Dict[str, List[int]] = defaultdict(list)
        for r in hourly_rates:
            periods[r["period"]].append(r["hour"])
        prices = {
            "date": d.isoformat(),
            "weekday": d.strftime("%A"),
            "day_type": "weekend" if d.weekday() >= 5 else "weekday",
            "pricing_type": "time_of_use",
            "tariff": TARIFF["name"],
            "currency": "USD",
            "unit": "per_kWh",
            "critical_peak_event": cpp,
            "hourly_rates": hourly_rates,
            "summary": {
                "average_effective_rate": round(sum(eff) / 24, 4),
                "min_effective_rate": min(eff),
                "max_effective_rate": max(eff),
                "cheapest_hours": [r["hour"] for r in by_cost[:6]],
                "most_expensive_hours": [r["hour"] for r in by_cost[-5:][::-1]],
                "period_hours": dict(periods),
                "peak_to_offpeak_ratio": round(max(eff) / min(eff), 2),
            },
            "solar_export_credit_per_kwh": TARIFF["solar_export_credit"],
            "notes": ("Self-consuming a solar kWh saves the full effective_rate; exporting it earns only the "
                      "export credit, so shifting flexible loads into solar hours is worth "
                      "(effective_rate - export credit) per kWh."
                      + (" CRITICAL PEAK EVENT: avoid all flexible load 16:00-21:00; pre-cool/pre-charge "
                         "before 16:00." if cpp else "")),
            "source": "mock tariff (deterministic, modelled on California TOU-EV plans)",
        }
        return prices
    except ValueError as e:
        return {"error": f"Invalid date '{date}': use YYYY-MM-DD, 'today', 'tomorrow' or a weekday name ({e})"}
    except Exception as e:
        return {"error": f"Failed to get electricity prices: {str(e)}"}


# ---------------------------------------------------------------------------
# Database tools (starter tools, fixed)
# ---------------------------------------------------------------------------
@tool
def query_energy_usage(start_date: str, end_date: str, device_type: str = None,
                       include_records: bool = False, max_records: int = 48) -> Dict[str, Any]:
    """
    Query energy usage data from the database for a specific date range.

    Returns aggregates (per device, per day, per time-of-use period and an
    average hourly profile) instead of thousands of raw rows.

    Args:
        start_date (str): Start date in YYYY-MM-DD format (or 'yesterday', 'today')
        end_date (str): End date in YYYY-MM-DD format (inclusive)
        device_type (str): Optional device filter. Types: "EV", "HVAC", "appliance",
            "pool_pump", "water_heater", "base_load". Device names also work
            (e.g. "Dishwasher", "Dryer").
        include_records (bool): Also return raw hourly records (capped by max_records)
        max_records (int): Maximum raw records to return when include_records is True

    Returns:
        Dict[str, Any]: Energy usage data with consumption details
    """
    try:
        start, end, start_dt, end_dt = _date_range(start_date, end_date)
        records = db_manager.get_usage_by_date_range(start_dt, end_dt)
        records = [r for r in records if _matches_device(r, device_type)]
        n_days = (end - start).days + 1

        by_device = defaultdict(lambda: {"consumption_kwh": 0.0, "cost_usd": 0.0, "records": 0})
        by_name = defaultdict(lambda: {"consumption_kwh": 0.0, "cost_usd": 0.0})
        by_day = defaultdict(lambda: {"consumption_kwh": 0.0, "cost_usd": 0.0})
        by_period = defaultdict(lambda: {"consumption_kwh": 0.0, "cost_usd": 0.0})
        by_hour = defaultdict(float)
        for r in records:
            for bucket in (by_device[r.device_type or "unknown"], by_day[r.timestamp.date().isoformat()],
                           by_period[tou_period(r.timestamp.hour, r.timestamp.date())]):
                bucket["consumption_kwh"] += r.consumption_kwh
                bucket["cost_usd"] += r.cost_usd or 0
            by_device[r.device_type or "unknown"]["records"] += 1
            by_name[r.device_name or "unknown"]["consumption_kwh"] += r.consumption_kwh
            by_name[r.device_name or "unknown"]["cost_usd"] += r.cost_usd or 0
            by_hour[r.timestamp.hour] += r.consumption_kwh

        def rounded(d):
            return {k: {kk: round(vv, 2) if isinstance(vv, float) else vv for kk, vv in v.items()} for k, v in d.items()}

        total_kwh = sum(r.consumption_kwh for r in records)
        total_cost = sum(r.cost_usd or 0 for r in records)
        usage_data = {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "days": n_days,
            "device_type": device_type,
            "total_records": len(records),
            "total_consumption_kwh": round(total_kwh, 2),
            "total_cost_usd": round(total_cost, 2),
            "average_daily_kwh": round(total_kwh / n_days, 2),
            "average_daily_cost_usd": round(total_cost / n_days, 2),
            "average_cost_per_kwh": round(total_cost / total_kwh, 4) if total_kwh else None,
            "by_device_type": rounded(by_device),
            "by_device_name": rounded(by_name),
            "by_tou_period": rounded(by_period),
            "daily_totals": rounded(dict(sorted(by_day.items()))),
            "average_hourly_profile_kwh": {h: round(by_hour[h] / n_days, 3) for h in range(24)},
            "cost_note": "cost_usd is the gross tariff cost of the consumption, before any solar offset.",
            "records": [],
        }
        if include_records:
            for record in records[: max(0, int(max_records))]:
                usage_data["records"].append({
                    "timestamp": record.timestamp.isoformat(),
                    "consumption_kwh": record.consumption_kwh,
                    "device_type": record.device_type,
                    "device_name": record.device_name,
                    "cost_usd": record.cost_usd
                })
            usage_data["records_truncated"] = len(records) > len(usage_data["records"])
        if not records:
            usage_data.update(_no_data_hint())
        return usage_data
    except Exception as e:
        return {"error": f"Failed to query energy usage: {str(e)}"}


@tool
def query_solar_generation(start_date: str, end_date: str, include_records: bool = False) -> Dict[str, Any]:
    """
    Query solar generation data from the database for a specific date range.

    Args:
        start_date (str): Start date in YYYY-MM-DD format (or 'yesterday', 'today')
        end_date (str): End date in YYYY-MM-DD format (inclusive)
        include_records (bool): Also return raw hourly records (up to 72)

    Returns:
        Dict[str, Any]: Solar generation data with production details: totals,
        daily totals, generation by weather condition and the average hourly profile.
    """
    try:
        start, end, start_dt, end_dt = _date_range(start_date, end_date)
        records = db_manager.get_generation_by_date_range(start_dt, end_dt)
        n_days = (end - start).days + 1
        by_day = defaultdict(float)
        by_hour = defaultdict(float)
        by_cond = defaultdict(lambda: {"generation_kwh": 0.0, "hours": 0})
        day_cond: Dict[str, Counter] = defaultdict(Counter)
        for r in records:
            by_day[r.timestamp.date().isoformat()] += r.generation_kwh
            by_hour[r.timestamp.hour] += r.generation_kwh
            by_cond[r.weather_condition or "unknown"]["generation_kwh"] += r.generation_kwh
            by_cond[r.weather_condition or "unknown"]["hours"] += 1
            day_cond[r.timestamp.date().isoformat()][r.weather_condition] += 1
        total = sum(r.generation_kwh for r in records)
        daily = {d: {"generation_kwh": round(v, 2), "condition": day_cond[d].most_common(1)[0][0]}
                 for d, v in sorted(by_day.items())}
        best = max(daily.items(), key=lambda kv: kv[1]["generation_kwh"]) if daily else None
        worst = min(daily.items(), key=lambda kv: kv[1]["generation_kwh"]) if daily else None
        generation_data = {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "total_records": len(records),
            "total_generation_kwh": round(total, 2),
            "average_daily_generation": round(total / max(1, n_days), 2),
            "best_day": {"date": best[0], **best[1]} if best else None,
            "worst_day": {"date": worst[0], **worst[1]} if worst else None,
            "daily_totals": daily,
            "by_weather_condition": {k: {"generation_kwh": round(v["generation_kwh"], 2), "hours": v["hours"],
                                         "avg_kwh_per_hour": round(v["generation_kwh"] / v["hours"], 2)}
                                     for k, v in by_cond.items()},
            "average_hourly_profile_kwh": {h: round(by_hour[h] / n_days, 3) for h in range(24) if by_hour[h] > 0},
            "records": [],
        }
        if include_records:
            for record in records[:72]:
                generation_data["records"].append({
                    "timestamp": record.timestamp.isoformat(),
                    "generation_kwh": record.generation_kwh,
                    "weather_condition": record.weather_condition,
                    "temperature_c": record.temperature_c,
                    "solar_irradiance": record.solar_irradiance
                })
        if not records:
            generation_data.update(_no_data_hint())
        return generation_data
    except Exception as e:
        return {"error": f"Failed to query solar generation: {str(e)}"}


@tool
def get_recent_energy_summary(hours: int = 24) -> Dict[str, Any]:
    """
    Get a summary of recent energy usage and solar generation.

    Args:
        hours (int): Number of hours to look back (default 24)

    Returns:
        Dict[str, Any]: Summary of recent energy data: consumption and cost by
        device, solar generation, the dominant weather, net grid balance and
        solar self-sufficiency.
    """
    try:
        usage_records = db_manager.get_recent_usage(hours)
        generation_records = db_manager.get_recent_generation(hours)
        weather_counts = Counter(r.weather_condition for r in generation_records if r.weather_condition)

        summary = {
            "time_period_hours": hours,
            "usage": {
                "total_consumption_kwh": round(sum(r.consumption_kwh for r in usage_records), 2),
                "total_cost_usd": round(sum(r.cost_usd or 0 for r in usage_records), 2),
                "device_breakdown": {}
            },
            "generation": {
                "total_generation_kwh": round(sum(r.generation_kwh for r in generation_records), 2),
                "average_weather": weather_counts.most_common(1)[0][0] if weather_counts else "unknown",
                "weather_hours": dict(weather_counts),
            }
        }

        # Calculate device breakdown
        for record in usage_records:
            device = record.device_type or "unknown"
            if device not in summary["usage"]["device_breakdown"]:
                summary["usage"]["device_breakdown"][device] = {
                    "consumption_kwh": 0,
                    "cost_usd": 0,
                    "records": 0
                }
            summary["usage"]["device_breakdown"][device]["consumption_kwh"] += record.consumption_kwh
            summary["usage"]["device_breakdown"][device]["cost_usd"] += record.cost_usd or 0
            summary["usage"]["device_breakdown"][device]["records"] += 1

        # Round the breakdown values
        for device_data in summary["usage"]["device_breakdown"].values():
            device_data["consumption_kwh"] = round(device_data["consumption_kwh"], 2)
            device_data["cost_usd"] = round(device_data["cost_usd"], 2)

        # Hour-by-hour net balance: solar used on site vs. imported vs. exported.
        load_by_hour = defaultdict(float)
        gen_by_hour = defaultdict(float)
        for r in usage_records:
            load_by_hour[r.timestamp.replace(minute=0, second=0, microsecond=0)] += r.consumption_kwh
        for r in generation_records:
            gen_by_hour[r.timestamp.replace(minute=0, second=0, microsecond=0)] += r.generation_kwh
        self_used = sum(min(load_by_hour[h], gen_by_hour[h]) for h in gen_by_hour)
        total_load = summary["usage"]["total_consumption_kwh"]
        total_gen = summary["generation"]["total_generation_kwh"]
        summary["balance"] = {
            "net_grid_kwh": round(total_load - total_gen, 2),
            "solar_self_consumed_kwh": round(self_used, 2),
            "solar_exported_kwh": round(total_gen - self_used, 2),
            "grid_imported_kwh": round(total_load - self_used, 2),
            "self_sufficiency_pct": round(100 * self_used / total_load, 1) if total_load else None,
            "solar_self_consumption_pct": round(100 * self_used / total_gen, 1) if total_gen else None,
        }
        return summary
    except Exception as e:
        return {"error": f"Failed to get recent energy summary: {str(e)}"}


# ---------------------------------------------------------------------------
# Required tool 3: knowledge-base search (RAG)
# ---------------------------------------------------------------------------
@tool
def search_energy_tips(query: str, max_results: int = 5) -> Dict[str, Any]:
    """
    Search for energy-saving tips and best practices using RAG.

    Hybrid retrieval over the EcoHome knowledge base (HVAC, EV charging, solar,
    batteries, seasonal plans, smart-home automation, water heating, pools,
    time-of-use rates): dense embeddings + BM25 keywords fused with Reciprocal
    Rank Fusion, at most two passages per source document.

    Args:
        query (str): Search query for energy tips
        max_results (int): Maximum number of results to return

    Returns:
        Dict[str, Any]: Relevant energy tips and best practices, each with its
        source document so the answer can cite it.
    """
    try:
        max_results = max(1, min(int(max_results or 5), 10))
        persist_directory = config.VECTORSTORE_DIR

        # 1. Initialize vector store if it doesn't exist
        if not os.path.exists(persist_directory):
            os.makedirs(persist_directory)

        if not rag.vectorstore_is_current(persist_directory):
            # 2. Load and split documents if the vector store doesn't exist (or a document was added or
            #    changed since it was built): every file in data/documents is loaded, split on section
            #    boundaries with contextual headers, embedded and persisted to Chroma.
            existed = os.path.exists(os.path.join(persist_directory, "chroma.sqlite3"))
            documents = rag.load_documents()
            splits = rag.split_documents(documents)
            vectorstore = rag.create_vectorstore(splits, persist_directory)
            index_status = "rebuilt" if existed else "built"
        else:
            # 3. Else load the existing vector store.
            vectorstore = rag.load_vectorstore(persist_directory)
            index_status = "loaded"

        # 4. Search for relevant documents (hybrid dense + BM25 with weighted RRF and diversity re-ranking)
        search = rag.hybrid_search(query, k=max_results, persist_directory=persist_directory, store=vectorstore)

        # 5. Return a results dict
        results = {
            "query": query,
            "total_results": len(search["results"]),
            "search_method": "hybrid (dense embeddings + BM25, reciprocal rank fusion, per-source diversity)",
            "index_status": index_status,
            "tips": []
        }
        for i, hit in enumerate(search["results"]):
            doc = hit["doc"]
            norm = hit["rrf"] / search["top_rrf"] if search["top_rrf"] else 0
            results["tips"].append({
                "rank": i + 1,
                "content": doc.page_content,
                "source": doc.metadata.get("source", "unknown"),
                "title": doc.metadata.get("title"),
                "section": doc.metadata.get("section") or None,
                "relevance_score": "high" if norm >= 0.8 else "medium" if norm >= 0.55 else "low",
                "fused_score": round(norm, 3),
                "vector_similarity": hit["vector_score"],
                "keyword_score": hit["bm25_score"],
            })
        return results
    except Exception as e:
        return {"error": f"Failed to search energy tips: {str(e)}"}


# ---------------------------------------------------------------------------
# Savings calculator (starter tool, extended but backward compatible)
# ---------------------------------------------------------------------------
@tool
def calculate_energy_savings(device_type: str, current_usage_kwh: float,
                             optimized_usage_kwh: float, price_per_kwh: float = 0.12,
                             optimized_price_per_kwh: Optional[float] = None,
                             frequency_per_year: float = 365,
                             upfront_cost_usd: Optional[float] = None,
                             shifted_out_of_peak: bool = False) -> Dict[str, Any]:
    """
    Calculate potential energy savings from optimization.

    Handles both kinds of savings:
    - efficiency (use fewer kWh): pass current and optimized kWh at one price_per_kwh;
    - load shifting (same kWh, cheaper hours): pass equal kWh, price_per_kwh = current
      effective rate and optimized_price_per_kwh = new effective rate.

    Args:
        device_type (str): Type of device being optimized
        current_usage_kwh (float): Current energy usage in kWh (per run or per day)
        optimized_usage_kwh (float): Optimized energy usage in kWh (same basis)
        price_per_kwh (float): Current price per kWh (use the effective_rate from get_electricity_prices)
        optimized_price_per_kwh (float): Price per kWh after optimization (defaults to price_per_kwh)
        frequency_per_year (float): How many times per year the saving recurs (365 = daily, 52 = weekly)
        upfront_cost_usd (float): Optional investment cost, to compute payback period / ROI
        shifted_out_of_peak (bool): True if the saving moves load out of the 16:00-21:00 peak
            (uses the higher peak-marginal carbon factor)

    Returns:
        Dict[str, Any]: Savings calculation results per event and per year, CO2 avoided and payback
    """
    try:
        opt_price = price_per_kwh if optimized_price_per_kwh is None else optimized_price_per_kwh
        current_cost = current_usage_kwh * price_per_kwh
        optimized_cost = optimized_usage_kwh * opt_price
        savings_kwh = current_usage_kwh - optimized_usage_kwh
        savings_usd = current_cost - optimized_cost
        savings_percentage = (savings_usd / current_cost) * 100 if current_cost > 0 else 0
        annual = savings_usd * frequency_per_year
        co2_factor = PEAK_MARGINAL_CO2_KG_PER_KWH - GRID_CO2_KG_PER_KWH["CA"] if shifted_out_of_peak else 0
        co2_per_event = savings_kwh * GRID_CO2_KG_PER_KWH["CA"] + (optimized_usage_kwh * co2_factor)
        result = {
            "device_type": device_type,
            "current_usage_kwh": current_usage_kwh,
            "optimized_usage_kwh": optimized_usage_kwh,
            "current_cost_usd": round(current_cost, 2),
            "optimized_cost_usd": round(optimized_cost, 2),
            "savings_kwh": round(savings_kwh, 2),
            "savings_usd": round(savings_usd, 2),
            "savings_percentage": round(savings_percentage, 1),
            "price_per_kwh": price_per_kwh,
            "optimized_price_per_kwh": opt_price,
            "frequency_per_year": frequency_per_year,
            "monthly_savings_usd": round(annual / 12, 2),
            "annual_savings_usd": round(annual, 2),
            "annual_energy_savings_kwh": round(savings_kwh * frequency_per_year, 1),
            "annual_co2_avoided_kg": round(co2_per_event * frequency_per_year, 1),
        }
        if upfront_cost_usd:
            result["upfront_cost_usd"] = upfront_cost_usd
            result["simple_payback_years"] = round(upfront_cost_usd / annual, 1) if annual > 0 else None
            result["ten_year_roi_pct"] = round(100 * (annual * 10 - upfront_cost_usd) / upfront_cost_usd, 1)
        return result
    except Exception as e:
        return {"error": f"Failed to calculate savings: {str(e)}"}


# ---------------------------------------------------------------------------
# Added tool: schedule optimiser (prices x solar forecast)
# ---------------------------------------------------------------------------
_DEVICE_KEY_ALIASES = {
    "ev": "ev", "electric vehicle": "ev", "electric car": "ev", "car": "ev", "tesla": "ev",
    "dishwasher": "dishwasher", "washer": "washing_machine", "washing machine": "washing_machine",
    "washing_machine": "washing_machine", "laundry": "washing_machine", "dryer": "dryer",
    "pool": "pool_pump", "pool pump": "pool_pump", "pool_pump": "pool_pump",
    "hvac": "hvac_precool", "precool": "hvac_precool", "pre-cool": "hvac_precool", "hvac_precool": "hvac_precool",
    "water heater": "water_heater", "water_heater": "water_heater", "battery": "battery",
}
_TYPICAL_START = {"ev": 18, "dishwasher": 20, "washing_machine": 18, "dryer": 19, "pool_pump": 12,
                  "hvac_precool": 16, "water_heater": 19, "battery": 22}
_RUNS_PER_YEAR = {"ev": 150, "dishwasher": 300, "washing_machine": 180, "dryer": 180, "pool_pump": 365,
                  "hvac_precool": 90, "water_heater": 365, "battery": 365}


@tool
def optimize_device_schedule(device: str, date: Optional[str] = None, energy_kwh: Optional[float] = None,
                             power_kw: Optional[float] = None, earliest_start_hour: int = 0,
                             latest_end_hour: int = 24, location: Optional[str] = None,
                             use_solar: bool = True, current_start_hour: Optional[int] = None) -> Dict[str, Any]:
    """
    Find the cheapest time to run a flexible load by combining hourly prices with the solar forecast.

    Scores every feasible start hour: cost = grid kWh x effective rate + solar kWh used x export
    credit (the credit you give up by using your own solar instead of exporting it).

    Args:
        device (str): "ev", "dishwasher", "washing_machine", "dryer", "pool_pump",
            "hvac_precool", "water_heater" or "battery" (other names use energy_kwh/power_kw)
        date (str): Day the run starts (YYYY-MM-DD, 'today', 'tomorrow' or weekday name). Default tomorrow.
        energy_kwh (float): Energy the run needs (defaults per device, e.g. EV 30 kWh, dishwasher 1.2 kWh)
        power_kw (float): Power draw while running (defaults per device, e.g. EV 7.7 kW)
        earliest_start_hour (int): Earliest allowed start hour 0-23 (default 0)
        latest_end_hour (int): Hour by which the run must finish (1-24). If it is <= earliest_start_hour
            the window wraps past midnight into the next day, e.g. 18 -> 7 for overnight EV charging.
        location (str): Location for the solar forecast (defaults to the household location)
        use_solar (bool): Account for the household's own solar production (default True)
        current_start_hour (int): When the user runs it today, to quantify savings (defaults to a typical habit)

    Returns:
        Dict[str, Any]: best window, runner-up windows, worst window, comparison with the current habit,
        and annualised savings.
    """
    try:
        key = _DEVICE_KEY_ALIASES.get(device.strip().lower(), device.strip().lower())
        defaults = DEVICE_LOADS.get(key, {})
        energy = float(energy_kwh or defaults.get("energy_kwh") or 0)
        power = float(power_kw or defaults.get("power_kw") or 0)
        if energy <= 0 or power <= 0:
            return {"error": f"Unknown device '{device}': pass energy_kwh and power_kw explicitly."}
        duration = max(1, math.ceil(energy / power - 1e-9))
        run_date = parse_date(date) if date else date_cls.today() + timedelta(days=1)
        start_h = int(earliest_start_hour) % 24
        end_h = int(latest_end_hour)
        if end_h <= start_h:
            end_h += 24  # wraps into the next day
        if end_h - start_h < duration:
            return {"error": f"Window {start_h}:00-{end_h % 24}:00 is shorter than the {duration} h the run needs."}

        # Hourly prices and solar for the (up to) two days the window touches.
        day_count = 2 if end_h > 24 else 1
        prices = {}
        for i in range(day_count):
            d = run_date + timedelta(days=i)
            for h in range(24):
                prices[i * 24 + h] = hourly_rate(h, d)
        solar = defaultdict(float)
        forecast_source = "not used"
        if use_solar:
            days_needed = (run_date - date_cls.today()).days + day_count
            if 0 <= days_needed - day_count and days_needed <= 7:
                fc = wx.get_forecast(location or _household("location"), days=days_needed,
                                     system_kw=float(_household("solar_system_kw") or 7.2))
                forecast_source = fc["source"]
                for row in fc["hourly"]:
                    offset = (date_cls.fromisoformat(row["date"]) - run_date).days
                    if 0 <= offset < day_count:
                        solar[offset * 24 + row["hour"]] = row["estimated_solar_kwh"]
            else:
                forecast_source = "outside the 7-day forecast horizon; solar ignored"
        base_load = 0.6  # kWh/h the rest of the house draws; solar serves it first
        credit = TARIFF["solar_export_credit"]

        def evaluate(s: int) -> Dict[str, Any]:
            remaining, cost, grid, sol, hours = energy, 0.0, 0.0, 0.0, []
            for h in range(s, s + duration):
                load = min(power, remaining)
                remaining -= load
                avail = max(0.0, solar[h] - base_load)
                used = min(load, avail)
                g = load - used
                rate = prices[h]["effective_rate"]
                cost += g * rate + used * credit
                grid += g
                sol += used
                hours.append({"hour": h % 24, "next_day": h >= 24, "kwh": round(load, 2),
                              "solar_kwh": round(used, 2), "rate": rate, "period": prices[h]["period"]})
            return {"start": f"{s % 24:02d}:00" + (" (+1 day)" if s >= 24 else ""),
                    "end": f"{(s + duration) % 24:02d}:00" + (" (+1 day)" if s + duration > 24 else ""),
                    "start_hour": s % 24, "cost_usd": round(cost, 2), "grid_kwh": round(grid, 2),
                    "solar_kwh": round(sol, 2),
                    "average_rate_paid": round(cost / energy, 4),
                    "periods": sorted({x["period"] for x in hours}), "hourly_plan": hours}

        options = [evaluate(s) for s in range(start_h, end_h - duration + 1)]
        options.sort(key=lambda o: (o["cost_usd"], o["start_hour"]))
        best, worst = options[0], options[-1]
        cur_h = current_start_hour if current_start_hour is not None else _TYPICAL_START.get(key)
        current = None
        if cur_h is not None:
            cur_s = int(cur_h) if int(cur_h) >= start_h else int(cur_h) + 24
            current = evaluate(cur_s) if cur_s + duration <= start_h + 48 and cur_s + duration <= day_count * 24 else None
        baseline = current or worst
        per_run = round(baseline["cost_usd"] - best["cost_usd"], 2)
        runs = _RUNS_PER_YEAR.get(key, 365)
        peak_kwh_avoided = sum(x["kwh"] for x in baseline["hourly_plan"]
                               if x["period"] in ("on_peak", "critical_peak"))
        for o in options[1:]:
            o.pop("hourly_plan", None)  # only the recommended window keeps its hour-by-hour plan
        # If the caller narrowed the window, say what the unconstrained day would have allowed, so a cheaper
        # solar window is never hidden by an assumed constraint.
        unconstrained = None
        if (start_h, end_h) != (0, 24):
            full = sorted((evaluate(s) for s in range(0, 24 - duration + 1)),
                          key=lambda o: (o["cost_usd"], o["start_hour"]))[0]
            if full["cost_usd"] < best["cost_usd"] - 0.10:
                full.pop("hourly_plan", None)
                unconstrained = {**full, "extra_saving_vs_best_usd": round(best["cost_usd"] - full["cost_usd"], 2),
                                 "note": "Cheapest window on this day with no time restriction; only possible if the "
                                         "device (e.g. the car) is available then."}
        return {
            "device": key,
            "date": run_date.isoformat(),
            "weekday": run_date.strftime("%A"),
            "critical_peak_event": is_critical_peak_day(run_date),
            "energy_kwh": energy,
            "power_kw": power,
            "duration_hours": duration,
            "allowed_window": f"{start_h:02d}:00-{end_h % 24:02d}:00" + (" (+1 day)" if end_h > 24 else ""),
            "solar_forecast_source": forecast_source,
            "best_window": best,
            "unconstrained_best_window": unconstrained,
            "alternatives": options[1:4],
            "worst_window": {k: v for k, v in worst.items() if k != "hourly_plan"},
            "compared_with": {"label": "current habit" if current_start_hour is not None
                              else "typical habit" if current else "worst window",
                              **{k: v for k, v in baseline.items() if k != "hourly_plan"}},
            "savings_per_run_usd": per_run,
            "estimated_runs_per_year": runs,
            "estimated_annual_savings_usd": round(per_run * runs, 2),
            "peak_kwh_avoided_per_run": round(peak_kwh_avoided, 2),
            "co2_avoided_per_run_kg": round(peak_kwh_avoided * (PEAK_MARGINAL_CO2_KG_PER_KWH - GRID_CO2_KG_PER_KWH["CA"])
                                            + best["solar_kwh"] * GRID_CO2_KG_PER_KWH["CA"], 2),
        }
    except ValueError as e:
        return {"error": f"Invalid argument: {e}"}
    except Exception as e:
        return {"error": f"Failed to optimize schedule: {str(e)}"}


# ---------------------------------------------------------------------------
# Added tool: usage pattern analysis (personalised opportunities)
# ---------------------------------------------------------------------------
_SHIFTABLE = {"EV", "appliance", "pool_pump", "water_heater"}


@tool
def analyze_usage_patterns(days: int = 30, device_type: Optional[str] = None) -> Dict[str, Any]:
    """
    Analyse the household's own usage history and rank concrete savings opportunities.

    Computes each device's share of consumption and cost, how much of it lands in
    the expensive 16:00-21:00 peak, its typical run hours, how well solar is
    self-consumed, and the dollar value of shifting each flexible load to its
    cheapest period. Use this for 'based on my usage history' questions.

    Args:
        days (int): Look-back window in days (default 30)
        device_type (str): Optional filter: a type (EV, HVAC, appliance, pool_pump, water_heater, base_load)
            or a single device name such as "dishwasher", "dryer" or "washing machine"

    Returns:
        Dict[str, Any]: per-device statistics, solar self-consumption, and ranked opportunities
    """
    try:
        days = max(1, min(int(days), 90))
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=days)
        usage = [r for r in db_manager.get_usage_by_date_range(start_dt, end_dt) if _matches_device(r, device_type)]
        gen = db_manager.get_generation_by_date_range(start_dt, end_dt)
        if not usage:
            return {"error": "No usage data in the window.", **_no_data_hint()}
        total_kwh = sum(r.consumption_kwh for r in usage)
        total_cost = sum(r.cost_usd or 0 for r in usage)

        stats: Dict[str, Dict[str, Any]] = {}
        name_stats: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
        hours_hist: Dict[str, Counter] = defaultdict(Counter)
        name_hours: Dict[str, Counter] = defaultdict(Counter)
        for r in usage:
            peak = tou_period(r.timestamp.hour, r.timestamp.date()) in ("on_peak", "critical_peak")
            name = r.device_name or r.device_type
            for s in (stats.setdefault(r.device_type, {"kwh": 0.0, "cost": 0.0, "peak_kwh": 0.0, "peak_cost": 0.0}),
                      name_stats[r.device_type].setdefault(name, {"kwh": 0.0, "cost": 0.0, "peak_kwh": 0.0,
                                                                  "peak_cost": 0.0})):
                s["kwh"] += r.consumption_kwh
                s["cost"] += r.cost_usd or 0
                if peak:
                    s["peak_kwh"] += r.consumption_kwh
                    s["peak_cost"] += r.cost_usd or 0
            hours_hist[r.device_type][r.timestamp.hour] += r.consumption_kwh
            name_hours[name][r.timestamp.hour] += r.consumption_kwh

        off_rate = TARIFF["periods"]["off_peak"]["rate"]
        solar_rate = TARIFF["periods"]["solar_midday"]["rate"]
        devices, opportunities = {}, []
        for dev, s in sorted(stats.items(), key=lambda kv: -kv[1]["cost"]):
            avg_rate = s["cost"] / s["kwh"] if s["kwh"] else 0
            devices[dev] = {
                "consumption_kwh": round(s["kwh"], 1),
                "cost_usd": round(s["cost"], 2),
                "share_of_kwh_pct": round(100 * s["kwh"] / total_kwh, 1),
                "share_of_cost_pct": round(100 * s["cost"] / total_cost, 1) if total_cost else 0,
                "average_daily_kwh": round(s["kwh"] / days, 2),
                "average_rate_paid": round(avg_rate, 4),
                "on_peak_share_pct": round(100 * s["peak_kwh"] / s["kwh"], 1) if s["kwh"] else 0,
                "typical_hours": [h for h, _ in hours_hist[dev].most_common(4)],
                "shiftable": dev in _SHIFTABLE,
            }
            # Individual devices inside the category (appliance = Dishwasher + Washing Machine + Dryer),
            # so figures for one device are never read off the category total.
            if len(name_stats[dev]) > 1:
                devices[dev]["by_device_name"] = {
                    n: {"consumption_kwh": round(ns["kwh"], 1), "cost_usd": round(ns["cost"], 2),
                        "average_daily_kwh": round(ns["kwh"] / days, 2),
                        "average_rate_paid": round(ns["cost"] / ns["kwh"], 4) if ns["kwh"] else 0,
                        "on_peak_share_pct": round(100 * ns["peak_kwh"] / ns["kwh"], 1) if ns["kwh"] else 0,
                        "typical_hours": [h for h, _ in name_hours[n].most_common(3)]}
                    for n, ns in sorted(name_stats[dev].items(), key=lambda kv: -kv[1]["cost"])}
            if dev == "appliance":
                # One opportunity per named appliance: "the dishwasher saves $X" must mean the dishwasher only.
                for n, ns in name_stats[dev].items():
                    monthly = (ns["cost"] - ns["kwh"] * off_rate) * 30 / days
                    if monthly > 0.5:
                        opportunities.append({
                            "device_type": dev, "device_name": n,
                            "action": f"Delay-start the {n.lower()} to after 22:00, or run it 10:00-15:00 on solar days.",
                            "current_average_rate": round(ns["cost"] / ns["kwh"], 4), "target_rate": off_rate,
                            "kwh_per_month": round(ns["kwh"] * 30 / days, 1),
                            "on_peak_kwh_per_month": round(ns["peak_kwh"] * 30 / days, 1),
                            "estimated_monthly_savings_usd": round(monthly, 2),
                            "estimated_annual_savings_usd": round(monthly * 12, 2),
                        })
            elif dev in _SHIFTABLE and s["kwh"] > 0:
                target = solar_rate if dev == "pool_pump" else off_rate
                monthly = (s["cost"] - s["kwh"] * target) * 30 / days
                if monthly > 0.5:
                    opportunities.append({
                        "device_type": dev,
                        "action": {
                            "EV": "Schedule EV charging to start after 22:00 (or 10:00-15:00 on sunny weekend days) "
                                  "instead of plugging in on arrival.",
                            "pool_pump": "Move the pool pump to 09:00-15:00 so it runs on solar instead of into the "
                                         "16:00 peak.",
                            "water_heater": "Pre-heat the heat-pump water heater midday and avoid evening "
                                            "recovery in the peak.",
                        }[dev],
                        "current_average_rate": round(avg_rate, 4),
                        "target_rate": target,
                        "on_peak_kwh_per_month": round(s["peak_kwh"] * 30 / days, 1),
                        "estimated_monthly_savings_usd": round(monthly, 2),
                        "estimated_annual_savings_usd": round(monthly * 12, 2),
                    })
        opportunities.sort(key=lambda o: -o["estimated_monthly_savings_usd"])

        # Solar self-consumption, hour by hour.
        load_h, gen_h = defaultdict(float), defaultdict(float)
        for r in db_manager.get_usage_by_date_range(start_dt, end_dt):
            load_h[r.timestamp.replace(minute=0, second=0, microsecond=0)] += r.consumption_kwh
        for r in gen:
            gen_h[r.timestamp.replace(minute=0, second=0, microsecond=0)] += r.generation_kwh
        total_gen = sum(gen_h.values())
        self_used = sum(min(load_h[h], g) for h, g in gen_h.items())
        exported = total_gen - self_used
        solar = {
            "total_generation_kwh": round(total_gen, 1),
            "self_consumed_kwh": round(self_used, 1),
            "exported_kwh": round(exported, 1),
            "self_consumption_pct": round(100 * self_used / total_gen, 1) if total_gen else None,
            "export_value_usd": round(exported * TARIFF["solar_export_credit"], 2),
            "value_if_self_consumed_usd": round(exported * solar_rate, 2),
        }
        if exported > 0 and total_gen:
            opportunities.append({
                "device_type": "solar",
                "action": "Soak up exported midday solar with flexible loads or a home battery; every exported kWh "
                          f"earns ${TARIFF['solar_export_credit']:.2f} but is worth about ${solar_rate:.2f} used on site.",
                "exported_kwh_per_month": round(exported * 30 / days, 1),
                "estimated_monthly_savings_usd": round(exported * (solar_rate - TARIFF["solar_export_credit"]) * 30 / days * 0.5, 2),
                "estimated_annual_savings_usd": round(exported * (solar_rate - TARIFF["solar_export_credit"]) * 365 / days * 0.5, 2),
                "note": "Assumes half of today's exports can realistically be shifted into self-consumption.",
            })
            opportunities.sort(key=lambda o: -o["estimated_monthly_savings_usd"])
        return {
            "window_days": days,
            "device_filter": device_type,
            "total_consumption_kwh": round(total_kwh, 1),
            "total_cost_usd": round(total_cost, 2),
            "average_daily_kwh": round(total_kwh / days, 1),
            "average_daily_cost_usd": round(total_cost / days, 2),
            "projected_monthly_bill_usd": round(total_cost * 30 / days, 2),
            "devices": devices,
            "solar": solar,
            "top_opportunities": opportunities[:5],
            "total_addressable_monthly_savings_usd": round(sum(o["estimated_monthly_savings_usd"] for o in opportunities), 2),
        }
    except Exception as e:
        return {"error": f"Failed to analyze usage patterns: {str(e)}"}


# ---------------------------------------------------------------------------
# Added tool: ML usage prediction
# ---------------------------------------------------------------------------
_MODEL_CACHE: Dict[str, Any] = {}


def _training_frame():
    """Hourly consumption per device (zeros filled) with calendar and temperature features."""
    import pandas as pd
    rng = db_manager.get_data_range()
    if not rng["first"]:
        raise RuntimeError("database is empty - run 01_db_setup.ipynb first")
    start = datetime.fromisoformat(rng["first"]).replace(hour=0, minute=0, second=0, microsecond=0)
    end = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)  # full days only
    usage = db_manager.get_usage_by_date_range(start, end)
    gen = db_manager.get_generation_by_date_range(start, end)
    df = pd.DataFrame([{"ts": r.timestamp.replace(minute=0, second=0, microsecond=0), "device": r.device_type,
                        "kwh": r.consumption_kwh} for r in usage])
    pivot = df.pivot_table(index="ts", columns="device", values="kwh", aggfunc="sum")
    pivot = pivot.reindex(pd.date_range(start, end - timedelta(hours=1), freq="h"), fill_value=0).fillna(0)
    temps = pd.DataFrame([{"date": r.timestamp.date(), "t": r.temperature_c} for r in gen if r.temperature_c is not None])
    daily_high = temps.groupby("date")["t"].max() if not temps.empty else pd.Series(dtype=float)
    feats = pd.DataFrame(index=pivot.index)
    feats["hour"] = pivot.index.hour
    feats["dow"] = pivot.index.dayofweek
    feats["weekend"] = (feats["dow"] >= 5).astype(int)
    feats["hour_sin"] = [math.sin(2 * math.pi * h / 24) for h in feats["hour"]]
    feats["hour_cos"] = [math.cos(2 * math.pi * h / 24) for h in feats["hour"]]
    default_high = float(daily_high.mean()) if len(daily_high) else 20.0
    feats["daily_high_c"] = [float(daily_high.get(ts.date(), default_high)) for ts in pivot.index]
    return feats, pivot


def _train_models():
    from sklearn.ensemble import GradientBoostingRegressor
    stamp = os.path.getmtime(db_manager.db_path) if os.path.exists(db_manager.db_path) else 0
    if _MODEL_CACHE.get("stamp") == stamp:
        return _MODEL_CACHE
    feats, pivot = _training_frame()
    cutoff = pivot.index.max() - timedelta(days=7)
    train, test = pivot.index <= cutoff, pivot.index > cutoff
    models, metrics = {}, {}
    for dev in pivot.columns:
        y = pivot[dev].values
        m = GradientBoostingRegressor(n_estimators=150, max_depth=3, learning_rate=0.05, random_state=0)
        m.fit(feats[train].values, y[train])
        pred = m.predict(feats[test].values).clip(0)
        # Baseline: mean kWh for the same hour and weekday/weekend type in the training window.
        base = feats[train].assign(y=y[train]).groupby(["hour", "weekend"])["y"].mean()
        naive = [base.get((h, w), 0) for h, w in zip(feats[test]["hour"], feats[test]["weekend"])]
        actual_daily = y[test].sum() / 7
        metrics[dev] = {
            "holdout_mae_kwh_per_hour": round(float(abs(pred - y[test]).mean()), 3),
            "baseline_mae_kwh_per_hour": round(float(abs(pd_array(naive) - y[test]).mean()), 3),
            "holdout_daily_error_pct": round(float(100 * abs(pred.sum() / 7 - actual_daily) / actual_daily), 1) if actual_daily else None,
        }
        m.fit(feats.values, y)  # refit on all data for forecasting
        models[dev] = m
    _MODEL_CACHE.clear()
    _MODEL_CACHE.update({"stamp": stamp, "models": models, "metrics": metrics, "columns": list(feats.columns),
                         "trained_on_hours": len(pivot), "default_high": float(feats["daily_high_c"].mean())})
    return _MODEL_CACHE


def pd_array(values):
    import numpy as np
    return np.asarray(values, dtype=float)


@tool
def predict_energy_usage(target_date: Optional[str] = None, device_type: Optional[str] = None,
                         location: Optional[str] = None) -> Dict[str, Any]:
    """
    Predict the household's hourly energy use for a future day with a machine-learning model.

    Gradient-boosted regression per device, trained on the usage history with hour-of-day,
    weekday/weekend and forecast daily high temperature as features; validated on the most
    recent 7 days against a same-hour-average baseline. Combines the prediction with the
    solar forecast and tariff to estimate the day's cost and grid import.

    Args:
        target_date (str): Day to predict (YYYY-MM-DD, 'tomorrow', weekday name). Default tomorrow.
        device_type (str): Optional single device type to report (EV, HVAC, appliance, pool_pump,
            water_heater, base_load)
        location (str): Location for the temperature and solar forecast (defaults to household)

    Returns:
        Dict[str, Any]: predicted kWh per device and per hour, expected solar, expected cost, and model accuracy
    """
    try:
        d = parse_date(target_date) if target_date else date_cls.today() + timedelta(days=1)
        cache = _train_models()
        horizon = (d - date_cls.today()).days + 1
        solar_by_hour, high, source = {}, cache["default_high"], "history average (date outside forecast horizon)"
        if 1 <= horizon <= 7:
            fc = wx.get_forecast(location or _household("location"), days=horizon,
                                 system_kw=float(_household("solar_system_kw") or 7.2))
            rows = [r for r in fc["hourly"] if r["date"] == d.isoformat()]
            if rows:
                high = max(r["temperature_c"] for r in rows)
                solar_by_hour = {r["hour"]: r["estimated_solar_kwh"] for r in rows}
                source = fc["source"]
        X = []
        for h in range(24):
            X.append([h, d.weekday(), int(d.weekday() >= 5), math.sin(2 * math.pi * h / 24),
                      math.cos(2 * math.pi * h / 24), high])
        per_device, hourly_total = {}, [0.0] * 24
        for dev, model in cache["models"].items():
            pred = model.predict(X).clip(0)
            per_device[dev] = round(float(pred.sum()), 2)
            for h in range(24):
                hourly_total[h] += float(pred[h])
        focus = None
        if device_type:
            key = _DEVICE_ALIASES.get(device_type.lower(), device_type)
            focus = {k: v for k, v in per_device.items() if k.lower() == key.lower()}
            if not focus:
                return {"error": f"No model for device '{device_type}'. Known: {sorted(per_device)}"}
        cost = grid = self_used = 0.0
        for h in range(24):
            s = solar_by_hour.get(h, 0.0)
            used = min(hourly_total[h], s)
            g = hourly_total[h] - used
            cost += g * hourly_rate(h, d)["effective_rate"] - (s - used) * TARIFF["solar_export_credit"]
            grid += g
            self_used += used
        total = sum(hourly_total)
        peak_hours = sorted(range(24), key=lambda h: -hourly_total[h])[:4]
        return {
            "date": d.isoformat(),
            "weekday": d.strftime("%A"),
            "forecast_daily_high_c": round(high, 1),
            "weather_source": source,
            "predicted_total_kwh": round(total, 1),
            "predicted_kwh_by_device": dict(sorted(per_device.items(), key=lambda kv: -kv[1])),
            "device_focus": focus,
            "predicted_hourly_kwh": [round(v, 2) for v in hourly_total],
            "predicted_peak_hours": sorted(peak_hours),
            "expected_solar_kwh": round(sum(solar_by_hour.values()), 1),
            "expected_self_consumed_solar_kwh": round(self_used, 1),
            "expected_grid_import_kwh": round(grid, 1),
            "expected_net_cost_usd": round(cost, 2),
            "model": {
                "type": "GradientBoostingRegressor per device (scikit-learn)",
                "features": cache["columns"],
                "trained_on_hours": cache["trained_on_hours"],
                "validation_last_7_days": cache["metrics"],
            },
        }
    except ValueError as e:
        return {"error": f"Invalid date: {e}"}
    except Exception as e:
        return {"error": f"Failed to predict energy usage: {str(e)}"}


# ---------------------------------------------------------------------------
# Added tools: personalisation
# ---------------------------------------------------------------------------
@tool
def get_user_preferences(category: Optional[str] = None) -> Dict[str, Any]:
    """
    Get the household profile and the user's saved preferences.

    Includes solar array size, battery, EV model and departure time, thermostat comfort range,
    appliance sizes and the optimisation priority (cost, carbon, comfort or balanced).
    Read this before giving personalised schedules or thermostat advice.

    Args:
        category (str): Optional filter: "profile", "comfort", "schedule" or "goal"

    Returns:
        Dict[str, Any]: preferences keyed by name
    """
    try:
        prefs = db_manager.get_preferences(category)
        if not prefs and not category:
            prefs = dict(DEFAULT_HOUSEHOLD_PROFILE)
            return {"preferences": prefs, "source": "built-in defaults (database not seeded)"}
        return {"preferences": prefs, "category": category, "count": len(prefs)}
    except Exception as e:
        return {"error": f"Failed to read preferences: {str(e)}"}


@tool
def update_user_preference(key: str, value: str, category: str = "profile") -> Dict[str, Any]:
    """
    Save a preference the user states so future advice is personalised
    (e.g. 'I leave for work at 7:00' -> key 'ev_departure_time', value '07:00').

    Only call this when the user explicitly states a fact or preference about their home or habits.

    Args:
        key (str): Preference name in snake_case (reuse existing keys such as ev_departure_time,
            comfort_cooling_setpoint_f, optimization_priority, ev_daily_miles)
        value (str): The value; numbers and JSON are parsed automatically
        category (str): "profile", "comfort", "schedule" or "goal"

    Returns:
        Dict[str, Any]: the stored preference and its previous value
    """
    try:
        key = key.strip().lower().replace(" ", "_")
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            parsed = value
        previous = db_manager.get_preferences().get(key)
        db_manager.set_preference(key, parsed, category=category, source="user")
        return {"saved": True, "key": key, "value": parsed, "previous_value": previous, "category": category}
    except Exception as e:
        return {"error": f"Failed to save preference: {str(e)}"}


TOOL_KIT = [
    get_weather_forecast,
    get_electricity_prices,
    query_energy_usage,
    query_solar_generation,
    get_recent_energy_summary,
    search_energy_tips,
    calculate_energy_savings,
    optimize_device_schedule,
    analyze_usage_patterns,
    predict_energy_usage,
    get_user_preferences,
    update_user_preference,
]
