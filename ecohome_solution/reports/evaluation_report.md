# EcoHome Energy Advisor - Evaluation Report
Generated 2026-09-26T18:38:13 | agent `gpt-4.1-mini` | judge `gpt-4o`

## Overall
| Metric | Value |
|---|---|
| overall score | 0.954 |
| response quality score | 0.943 |
| tool usage score | 0.97 |
| pass rate | 1.0 |
| tests passed | 18 |
| tests total | 18 |
| mean latency s | 14.1 |
| p90 latency s | 18.6 |
| mean tool calls | 4.1 |
| mean llm calls | 4.1 |
| numeric grounding ratio | 0.949 |
| knowledge base citation rate | 0.944 |
| tool error count | 0 |

## Response quality (1-10)
| Metric | Mean | Min | Max |
|---|---|---|---|
| accuracy | 9.39 | 8 | 10 |
| relevance | 9.94 | 9 | 10 |
| completeness | 9.0 | 7 | 10 |
| usefulness | 9.5 | 8 | 10 |
| clarity | 9.39 | 9 | 10 |

## Tool usage (0-1)
| Metric | Mean |
|---|---|
| tool_appropriateness | 0.991 |
| tool_completeness | 0.944 |
| tool_success_rate | 1.0 |
| efficiency | 0.95 |
| argument_quality | 1.0 |

## Tool coverage
Required tools covered: 7/7
| Tool | Required | Successful calls | Tests |
|---|---|---|---|
| search_energy_tips | yes | 19 | ev_charging_1, ev_charging_deadline, thermostat_price_spike, thermostat_heat_precool, dishwasher_offpeak, laundry_weekend, pool_pump_week, solar_self_consumption, usage_history_three_ways, ev_shift_annual_savings, battery_roi, usage_forecast_tomorrow, recent_24h_summary, yesterday_summary, solar_week_history, seasonal_winter, personalization_departure |
| get_electricity_prices | yes | 18 | ev_charging_1, ev_charging_deadline, thermostat_price_spike, thermostat_heat_precool, dishwasher_offpeak, laundry_weekend, pool_pump_week, ev_shift_annual_savings, battery_roi, usage_forecast_tomorrow, personalization_departure |
| get_weather_forecast | yes | 7 | ev_charging_1, ev_charging_deadline, thermostat_price_spike, thermostat_heat_precool, laundry_weekend, pool_pump_week, personalization_departure |
| query_energy_usage | yes | 4 | ev_shift_annual_savings, battery_roi, yesterday_summary |
| calculate_energy_savings | yes | 3 | dishwasher_offpeak, ev_shift_annual_savings, battery_roi |
| query_solar_generation | yes | 2 | yesterday_summary, solar_week_history |
| get_recent_energy_summary | yes | 1 | recent_24h_summary |
| optimize_device_schedule |  | 15 | ev_charging_1, ev_charging_deadline, thermostat_price_spike, thermostat_heat_precool, laundry_weekend, pool_pump_week, battery_roi, personalization_departure |
| analyze_usage_patterns |  | 3 | dishwasher_offpeak, solar_self_consumption, usage_history_three_ways |
| predict_energy_usage |  | 1 | usage_forecast_tomorrow |
| get_user_preferences |  | 1 | seasonal_winter |

## By category
| Category | Response | Tools | Combined |
|---|---|---|---|
| EV charging optimization | 1.0 | 1.0 | 1.0 |
| Out of scope / guardrails | 0.975 | 1.0 | 0.985 |
| Thermostat settings | 0.96 | 1.0 | 0.976 |
| Usage forecasting (ML) | 0.95 | 1.0 | 0.97 |
| Seasonal & knowledge-based advice | 0.95 | 1.0 | 0.97 |
| Solar power maximization | 0.945 | 1.0 | 0.967 |
| Usage analysis & personalization | 0.954 | 0.956 | 0.955 |
| Appliance scheduling | 0.895 | 0.955 | 0.919 |
| Cost savings calculations | 0.895 | 0.884 | 0.891 |

## Per test
| Test | Acc | Rel | Comp | Use | Tools | Combined | Pass |
|---|---|---|---|---|---|---|---|
| ev_charging_1 | 10 | 10 | 10 | 10 | 1.0 | 1.0 | yes |
| ev_charging_deadline | 10 | 10 | 10 | 10 | 1.0 | 1.0 | yes |
| thermostat_price_spike | 10 | 10 | 9 | 10 | 1.0 | 0.985 | yes |
| thermostat_heat_precool | 9 | 10 | 9 | 10 | 1.0 | 0.967 | yes |
| dishwasher_offpeak | 9 | 10 | 9 | 10 | 1.0 | 0.967 | yes |
| laundry_weekend | 9 | 10 | 9 | 10 | 1.0 | 0.967 | yes |
| pool_pump_week | 8 | 9 | 7 | 8 | 0.865 | 0.823 | yes |
| solar_self_consumption | 9 | 10 | 9 | 10 | 1.0 | 0.967 | yes |
| usage_history_three_ways | 10 | 10 | 10 | 10 | 1.0 | 1.0 | yes |
| ev_shift_annual_savings | 9 | 10 | 8 | 9 | 1.0 | 0.937 | yes |
| battery_roi | 9 | 10 | 8 | 9 | 0.767 | 0.844 | yes |
| usage_forecast_tomorrow | 10 | 10 | 9 | 9 | 1.0 | 0.97 | yes |
| recent_24h_summary | 9 | 10 | 9 | 9 | 1.0 | 0.952 | yes |
| yesterday_summary | 10 | 10 | 9 | 9 | 1.0 | 0.97 | yes |
| solar_week_history | 9 | 10 | 9 | 10 | 1.0 | 0.967 | yes |
| seasonal_winter | 10 | 10 | 9 | 9 | 1.0 | 0.97 | yes |
| personalization_departure | 9 | 10 | 9 | 10 | 0.825 | 0.897 | yes |
| out_of_scope | 10 | 10 | 10 | 9 | 1.0 | 0.985 | yes |

## Strengths
- Accuracy averages 9.39/10 (range 8-10).
- Relevance averages 9.94/10 (range 9-10).
- Completeness averages 9.0/10 (range 7-10).
- Usefulness averages 9.5/10 (range 8-10).
- Clarity averages 9.39/10 (range 9-10).
- Tool appropriateness: 99%.
- Tool success rate: 100%.
- Efficiency: 95%.
- Argument quality: 100%.
- Strongest category: EV charging optimization (1.00).
- 95% of stated $/kWh/°F/% figures trace back to tool outputs.
- Knowledge-base sources cited in 94% of answers.
- All 7 required tools were exercised successfully by at least one test.

## Weaknesses
- Relative: completeness is the lowest response metric (9.0/10). Lowest: pool_pump_week (7), ev_shift_annual_savings (8), battery_roi (8). Judge on pool_pump_week: The response covers most expected elements but lacks specific adjustments for cloudy days and a detailed comparison with the current schedule.
- Relative: tool completeness is the lowest tool metric (94%); battery_roi: ['analyze_usage_patterns or get_recent_energy_summary or query_solar_generation']; personalization_departure: ['update_user_preference'].
- Relative: pool_pump_week is among the two lowest-scoring tests (0.82): Lacks specific adjustments for cloudy days in the forecast.
- Relative: battery_roi is among the two lowest-scoring tests (0.84): Lacks detailed caveats about variability in solar exports and price spreads.
- Relative: 15/18 first drafts were sent back by the quality gate before release ({'no knowledge-base search': 15, 'savings figure without the calculator': 2}). The final answers passed, but the model does not yet follow these rules unprompted, which costs an extra LLM call each time.
- Relative: some stated figures could not be traced to a tool output in laundry_weekend (80% grounded), solar_self_consumption (83% grounded), battery_roi (83% grounded) (these may be derived by arithmetic, but they cannot be verified automatically).
- Relative: p90 latency is 18.6 s; slowest pool_pump_week (29.83 s, 16 tool calls), personalization_departure (18.97 s, 4 tool calls). Quality-gate revisions add a full LLM round-trip.

## Recommendations
- Tool completeness: the most often skipped tools were {'analyze_usage_patterns or get_recent_energy_summary or query_solar_generation': 1, 'update_user_preference': 1}. Add explicit 'always call X for Y' rules to the system prompt for those question types.
- First-draft compliance: 15 answers needed a quality-gate revision. Move the most frequent rule into the question-type examples of the system prompt, or force the tool with tool_choice when the question pattern matches, to save the extra LLM round-trip.
- Judge suggestion: Consider slightly more concise phrasing to enhance clarity further.
- Judge suggestion: Consider mentioning the exact forecast temperature for added completeness.
- Judge suggestion: Include specific solar output data for the pre-cooling hours to enhance completeness.
- Judge suggestion: Simplify the savings explanation for better clarity.
- Coverage: grow the test set with multi-turn, adversarial and non-California-tariff scenarios, and re-run the evaluation on every prompt change (regression suite).
