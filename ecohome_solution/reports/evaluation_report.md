# EcoHome Energy Advisor - Evaluation Report
Generated 2026-09-26T18:28:48 | agent `gpt-4.1-mini` | judge `gpt-4o`

## Overall
| Metric | Value |
|---|---|
| overall score | 0.948 |
| response quality score | 0.929 |
| tool usage score | 0.978 |
| pass rate | 1.0 |
| tests passed | 18 |
| tests total | 18 |
| mean latency s | 13.6 |
| p90 latency s | 18.5 |
| mean tool calls | 4.6 |
| mean llm calls | 4.3 |
| numeric grounding ratio | 0.951 |
| knowledge base citation rate | 0.944 |
| tool error count | 0 |

## Response quality (1-10)
| Metric | Mean | Min | Max |
|---|---|---|---|
| accuracy | 9.22 | 7 | 10 |
| relevance | 9.89 | 9 | 10 |
| completeness | 8.94 | 7 | 10 |
| usefulness | 9.22 | 8 | 10 |
| clarity | 9.39 | 8 | 10 |

## Tool usage (0-1)
| Metric | Mean |
|---|---|
| tool_appropriateness | 0.957 |
| tool_completeness | 1.0 |
| tool_success_rate | 1.0 |
| efficiency | 0.95 |
| argument_quality | 1.0 |

## Tool coverage
Required tools covered: 7/7
| Tool | Required | Successful calls | Tests |
|---|---|---|---|
| search_energy_tips | yes | 21 | ev_charging_1, ev_charging_deadline, thermostat_price_spike, thermostat_heat_precool, dishwasher_offpeak, laundry_weekend, pool_pump_week, solar_self_consumption, usage_history_three_ways, ev_shift_annual_savings, battery_roi, usage_forecast_tomorrow, recent_24h_summary, yesterday_summary, solar_week_history, seasonal_winter, personalization_departure |
| get_electricity_prices | yes | 17 | ev_charging_1, ev_charging_deadline, thermostat_price_spike, thermostat_heat_precool, dishwasher_offpeak, laundry_weekend, pool_pump_week, ev_shift_annual_savings, battery_roi, personalization_departure |
| get_weather_forecast | yes | 7 | ev_charging_1, ev_charging_deadline, thermostat_price_spike, thermostat_heat_precool, laundry_weekend, pool_pump_week, personalization_departure |
| calculate_energy_savings | yes | 3 | dishwasher_offpeak, ev_shift_annual_savings, battery_roi |
| query_energy_usage | yes | 3 | ev_shift_annual_savings, battery_roi, yesterday_summary |
| query_solar_generation | yes | 3 | battery_roi, yesterday_summary, solar_week_history |
| get_recent_energy_summary | yes | 1 | recent_24h_summary |
| optimize_device_schedule |  | 19 | ev_charging_1, ev_charging_deadline, thermostat_price_spike, thermostat_heat_precool, laundry_weekend, pool_pump_week, usage_history_three_ways, ev_shift_annual_savings, battery_roi, personalization_departure |
| analyze_usage_patterns |  | 3 | dishwasher_offpeak, solar_self_consumption, usage_history_three_ways |
| get_user_preferences |  | 3 | usage_forecast_tomorrow, seasonal_winter, personalization_departure |
| predict_energy_usage |  | 1 | usage_forecast_tomorrow |
| update_user_preference |  | 1 | personalization_departure |

## By category
| Category | Response | Tools | Combined |
|---|---|---|---|
| Seasonal & knowledge-based advice | 0.975 | 1.0 | 0.985 |
| Out of scope / guardrails | 0.975 | 1.0 | 0.985 |
| EV charging optimization | 0.972 | 1.0 | 0.984 |
| Usage forecasting (ML) | 0.95 | 1.0 | 0.97 |
| Solar power maximization | 0.935 | 1.0 | 0.961 |
| Thermostat settings | 0.92 | 1.0 | 0.952 |
| Usage analysis & personalization | 0.935 | 0.948 | 0.94 |
| Appliance scheduling | 0.893 | 0.955 | 0.918 |
| Cost savings calculations | 0.87 | 0.971 | 0.91 |

## Per test
| Test | Acc | Rel | Comp | Use | Tools | Combined | Pass |
|---|---|---|---|---|---|---|---|
| ev_charging_1 | 10 | 10 | 10 | 10 | 1.0 | 1.0 | yes |
| ev_charging_deadline | 9 | 10 | 9 | 10 | 1.0 | 0.967 | yes |
| thermostat_price_spike | 9 | 10 | 9 | 9 | 1.0 | 0.952 | yes |
| thermostat_heat_precool | 9 | 10 | 9 | 9 | 1.0 | 0.952 | yes |
| dishwasher_offpeak | 9 | 10 | 9 | 10 | 1.0 | 0.967 | yes |
| laundry_weekend | 7 | 9 | 8 | 9 | 1.0 | 0.889 | yes |
| pool_pump_week | 9 | 10 | 9 | 9 | 0.865 | 0.898 | yes |
| solar_self_consumption | 9 | 10 | 9 | 9 | 1.0 | 0.952 | yes |
| usage_history_three_ways | 9 | 10 | 9 | 9 | 0.79 | 0.868 | yes |
| ev_shift_annual_savings | 9 | 10 | 9 | 10 | 1.0 | 0.967 | yes |
| battery_roi | 8 | 9 | 7 | 8 | 0.942 | 0.854 | yes |
| usage_forecast_tomorrow | 10 | 10 | 9 | 9 | 1.0 | 0.97 | yes |
| recent_24h_summary | 10 | 10 | 9 | 9 | 1.0 | 0.97 | yes |
| yesterday_summary | 10 | 10 | 9 | 9 | 1.0 | 0.97 | yes |
| solar_week_history | 10 | 10 | 9 | 9 | 1.0 | 0.97 | yes |
| seasonal_winter | 10 | 10 | 9 | 10 | 1.0 | 0.985 | yes |
| personalization_departure | 9 | 10 | 9 | 9 | 1.0 | 0.952 | yes |
| out_of_scope | 10 | 10 | 10 | 9 | 1.0 | 0.985 | yes |

## Strengths
- Accuracy averages 9.22/10 (range 7-10).
- Relevance averages 9.89/10 (range 9-10).
- Completeness averages 8.94/10 (range 7-10).
- Usefulness averages 9.22/10 (range 8-10).
- Clarity averages 9.39/10 (range 8-10).
- Tool appropriateness: 96%.
- Tool completeness: 100%.
- Tool success rate: 100%.
- Efficiency: 95%.
- Argument quality: 100%.
- Strongest category: Seasonal & knowledge-based advice (0.98).
- 95% of stated $/kWh/°F/% figures trace back to tool outputs.
- Knowledge-base sources cited in 94% of answers.
- All 7 required tools were exercised successfully by at least one test.

## Weaknesses
- No metric fell below its threshold.

## Recommendations
- Judge suggestion: Provide a more detailed breakdown of the savings calculation.
- Judge suggestion: Ensure the effective rate matches the tool evidence exactly.
- Judge suggestion: Consider mentioning the exact off-peak rate from the tool evidence for transparency.
- Judge suggestion: Include the exact forecast temperature during peak hours for more precise advice.
- Coverage: grow the test set with multi-turn, adversarial and non-California-tariff scenarios, and re-run the evaluation on every prompt change (regression suite).
