"""Offline tests for the energy model and every tool in TOOL_KIT."""
from datetime import date, datetime, timedelta

import pytest

import tools
from energy_model import (TARIFF, clear_sky_ghi, hourly_rate, is_critical_peak_day, pv_output_kwh,
                          solar_elevation_deg, tou_period)


# --------------------------------------------------------------- energy model
def test_tou_periods_cover_the_day():
    weekday = date(2026, 9, 29)  # Tuesday
    assert tou_period(2, weekday) == "off_peak"
    assert tou_period(12, weekday) == "solar_midday"
    assert tou_period(8, weekday) == "mid_peak"
    assert tou_period(17, weekday) in ("on_peak", "critical_peak")
    assert tou_period(23, weekday) == "off_peak"


def test_weekends_have_no_on_peak_or_critical_peak():
    for offset in range(60):
        d = date(2026, 1, 1) + timedelta(days=offset)
        if d.weekday() >= 5:
            assert not is_critical_peak_day(d)
            assert all(tou_period(h, d) not in ("on_peak", "critical_peak") for h in range(24))


def test_critical_peak_days_exist_and_are_expensive():
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(120)]
    cpp = [d for d in days if is_critical_peak_day(d)]
    assert 5 <= len(cpp) <= 30
    assert hourly_rate(17, cpp[0])["effective_rate"] > 0.9


def test_solar_is_zero_at_night_and_peaks_midday():
    d = date(2026, 6, 21)
    assert solar_elevation_deg(d, 1, 37.77, -122.42) < 0
    assert solar_elevation_deg(d, 13, 37.77, -122.42) > 60
    assert clear_sky_ghi(-5) == 0
    assert pv_output_kwh(0, 20) == 0
    assert 4.0 < pv_output_kwh(900, 20, 7.2) < 6.5


# ------------------------------------------------------------ date parsing
def test_parse_date_accepts_words_and_weekdays():
    today = date(2026, 9, 26)  # Saturday
    assert tools.parse_date("tomorrow", today) == date(2026, 9, 27)
    assert tools.parse_date("yesterday", today) == date(2026, 9, 25)
    assert tools.parse_date("Wednesday", today) == date(2026, 9, 30)
    assert tools.parse_date("next monday", today) == date(2026, 9, 28)
    assert tools.parse_date("2026-10-02T10:00:00", today) == date(2026, 10, 2)
    assert tools.parse_date(None, today) == today


# ---------------------------------------------------------- electricity prices
def test_electricity_prices_structure():
    r = tools.get_electricity_prices.invoke({"date": "2026-09-29"})
    assert r["date"] == "2026-09-29"
    assert r["pricing_type"] == "time_of_use" and r["currency"] == "USD" and r["unit"] == "per_kWh"
    assert len(r["hourly_rates"]) == 24
    for row in r["hourly_rates"]:
        assert {"hour", "rate", "period", "demand_charge", "effective_rate"} <= set(row)
        if row["period"] in ("off_peak", "solar_midday"):
            assert row["demand_charge"] == 0
    s = r["summary"]
    assert s["min_effective_rate"] < s["max_effective_rate"]
    assert all(h >= 22 or h < 7 or 10 <= h < 15 for h in s["cheapest_hours"])


def test_electricity_prices_default_today_and_bad_date():
    assert tools.get_electricity_prices.invoke({})["date"] == date.today().isoformat()
    assert "error" in tools.get_electricity_prices.invoke({"date": "31/12/2026"})


# ------------------------------------------------------------ weather forecast
def test_weather_forecast_mock_structure():
    r = tools.get_weather_forecast.invoke({"location": "San Francisco, CA", "days": 3})
    assert r["forecast_days"] == 3
    assert r["source"].startswith("mock")
    assert len(r["hourly"]) == 72 and len(r["daily"]) == 3
    first = r["hourly"][0]
    for key in ("hour", "temperature_c", "condition", "solar_irradiance", "humidity", "wind_speed",
                "estimated_solar_kwh"):
        assert key in first
    assert {"temperature_c", "condition", "humidity", "wind_speed"} <= set(r["current"])
    night = [h for h in r["hourly"] if h["hour"] in (0, 1, 2, 3)]
    assert all(h["solar_irradiance"] == 0 for h in night)
    assert max(h["estimated_solar_kwh"] for h in r["hourly"]) > 0


def test_weather_days_are_clamped_and_deterministic():
    a = tools.get_weather_forecast.invoke({"location": "Chicago, IL", "days": 30})
    b = tools.get_weather_forecast.invoke({"location": "Chicago, IL", "days": 30})
    assert a["forecast_days"] == 7 and a["hourly"] == b["hourly"]


# ------------------------------------------------------------- usage queries
def _range(days_back=7):
    end = date.today() - timedelta(days=1)
    return (end - timedelta(days=days_back - 1)).isoformat(), end.isoformat()


def test_query_energy_usage_aggregates_match_totals():
    start, end = _range()
    r = tools.query_energy_usage.invoke({"start_date": start, "end_date": end})
    assert r["total_records"] > 100
    assert r["records"] == []  # raw rows only on request
    assert abs(sum(d["consumption_kwh"] for d in r["by_device_type"].values()) - r["total_consumption_kwh"]) < 0.1
    assert abs(sum(d["cost_usd"] for d in r["daily_totals"].values()) - r["total_cost_usd"]) < 0.1
    assert 15 < r["average_daily_kwh"] < 70  # a plausible home, not 340 kWh/day


def test_query_energy_usage_device_filters_and_aliases():
    start, end = _range()
    ev = tools.query_energy_usage.invoke({"start_date": start, "end_date": end, "device_type": "electric car"})
    assert set(ev["by_device_type"]) == {"EV"}
    dw = tools.query_energy_usage.invoke({"start_date": start, "end_date": end, "device_type": "dishwasher"})
    assert set(dw["by_device_name"]) == {"Dishwasher"}
    raw = tools.query_energy_usage.invoke({"start_date": start, "end_date": end, "include_records": True,
                                           "max_records": 5})
    assert len(raw["records"]) == 5 and raw["records_truncated"]


def test_query_energy_usage_out_of_range_gives_hint():
    r = tools.query_energy_usage.invoke({"start_date": "2020-01-01", "end_date": "2020-01-02"})
    assert r["total_records"] == 0 and "available_data_range" in r


def test_query_solar_generation():
    start, end = _range()
    r = tools.query_solar_generation.invoke({"start_date": start, "end_date": end})
    assert r["total_generation_kwh"] > 0
    assert r["best_day"]["generation_kwh"] >= r["worst_day"]["generation_kwh"]
    assert all(6 <= h <= 20 for h in r["average_hourly_profile_kwh"])


def test_recent_energy_summary_balance():
    r = tools.get_recent_energy_summary.invoke({"hours": 48})
    assert r["usage"]["total_consumption_kwh"] > 0
    b = r["balance"]
    assert abs(b["solar_self_consumed_kwh"] + b["solar_exported_kwh"] - r["generation"]["total_generation_kwh"]) < 0.05
    assert r["generation"]["average_weather"] != "sunny" or r["generation"]["weather_hours"]


# ----------------------------------------------------------------- savings
def test_calculate_energy_savings_backward_compatible():
    r = tools.calculate_energy_savings.invoke({"device_type": "HVAC", "current_usage_kwh": 10,
                                               "optimized_usage_kwh": 8})
    assert r["savings_kwh"] == 2 and r["savings_usd"] == 0.24 and r["annual_savings_usd"] == 87.6


def test_calculate_energy_savings_load_shift_and_payback():
    r = tools.calculate_energy_savings.invoke({
        "device_type": "EV", "current_usage_kwh": 30, "optimized_usage_kwh": 30, "price_per_kwh": 0.53,
        "optimized_price_per_kwh": 0.22, "frequency_per_year": 150, "upfront_cost_usd": 700,
        "shifted_out_of_peak": True})
    assert r["savings_usd"] == pytest.approx(9.3, abs=0.01)
    assert r["annual_savings_usd"] == pytest.approx(1395, abs=1)
    assert r["simple_payback_years"] == pytest.approx(0.5, abs=0.05)
    assert r["annual_co2_avoided_kg"] > 0


# ------------------------------------------------------------ optimiser
def test_optimize_ev_overnight_wraps_midnight_and_avoids_peak():
    r = tools.optimize_device_schedule.invoke({"device": "ev", "date": "2026-09-29", "energy_kwh": 30,
                                               "earliest_start_hour": 18, "latest_end_hour": 7,
                                               "use_solar": False})
    best = r["best_window"]
    assert r["duration_hours"] == 4
    assert all(p == "off_peak" for p in best["periods"])
    assert r["savings_per_run_usd"] > 5  # vs plugging in at 18:00
    assert "+1 day" in r["allowed_window"]


def test_optimize_uses_solar_when_available():
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    r = tools.optimize_device_schedule.invoke({"device": "pool pump", "date": tomorrow})
    assert r["device"] == "pool_pump" and r["duration_hours"] == 6
    assert r["best_window"]["cost_usd"] <= r["compared_with"]["cost_usd"]
    assert r["solar_forecast_source"].startswith("mock")


def test_optimize_rejects_impossible_window_and_unknown_device():
    assert "error" in tools.optimize_device_schedule.invoke({"device": "ev", "earliest_start_hour": 1,
                                                             "latest_end_hour": 2})
    assert "error" in tools.optimize_device_schedule.invoke({"device": "sauna"})


# --------------------------------------------------- analysis, ML, preferences
def test_analyze_usage_patterns_ranks_opportunities():
    r = tools.analyze_usage_patterns.invoke({"days": 30})
    assert r["devices"] and r["top_opportunities"]
    savings = [o["estimated_monthly_savings_usd"] for o in r["top_opportunities"]]
    assert savings == sorted(savings, reverse=True)
    assert r["devices"]["EV"]["on_peak_share_pct"] > 20  # the seeded habit: plug in on arrival
    assert 0 < r["solar"]["self_consumption_pct"] <= 100


def test_predict_energy_usage_returns_24_hours_and_validation():
    r = tools.predict_energy_usage.invoke({"target_date": "tomorrow"})
    assert len(r["predicted_hourly_kwh"]) == 24
    assert r["predicted_total_kwh"] > 10
    metrics = r["model"]["validation_last_7_days"]
    assert "base_load" in metrics and metrics["base_load"]["holdout_mae_kwh_per_hour"] < 0.3
    assert "error" in tools.predict_energy_usage.invoke({"device_type": "hot tub"})


def test_preferences_round_trip():
    before = tools.get_user_preferences.invoke({})
    assert before["preferences"]["solar_system_kw"] == 7.2
    saved = tools.update_user_preference.invoke({"key": "EV Departure Time", "value": "07:00",
                                                 "category": "schedule"})
    assert saved["key"] == "ev_departure_time" and saved["previous_value"] == "07:30"
    assert tools.get_user_preferences.invoke({"category": "schedule"})["preferences"]["ev_departure_time"] == "07:00"
    num = tools.update_user_preference.invoke({"key": "comfort_max_f", "value": "80", "category": "comfort"})
    assert num["value"] == 80
    tools.update_user_preference.invoke({"key": "ev_departure_time", "value": "07:30"})  # restore


def test_every_tool_has_docstring_and_returns_errors_not_exceptions():
    for t in tools.TOOL_KIT:
        assert t.description and len(t.description) > 40, t.name
    assert "error" in tools.query_energy_usage.invoke({"start_date": "bad", "end_date": "worse"})
