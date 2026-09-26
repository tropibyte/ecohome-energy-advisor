# EcoHome Energy Advisor - Evaluation Report
Generated 2026-09-26T12:00:51 | agent `gpt-4.1-mini` | judge `gpt-4o`

## Overall
| Metric | Value |
|---|---|
| overall score | 0.928 |
| response quality score | 0.905 |
| tool usage score | 0.963 |
| pass rate | 0.938 |
| tests passed | 15 |
| tests total | 16 |
| mean latency s | 12.8 |
| p90 latency s | 17.4 |
| mean tool calls | 4.2 |
| mean llm calls | 4.2 |
| numeric grounding ratio | 0.938 |
| knowledge base citation rate | 0.938 |
| tool error count | 0 |

## Response quality (1-10)
| Metric | Mean | Min | Max |
|---|---|---|---|
| accuracy | 8.94 | 5 | 10 |
| relevance | 9.75 | 8 | 10 |
| completeness | 8.62 | 6 | 10 |
| usefulness | 9.06 | 7 | 10 |
| clarity | 9.25 | 7 | 10 |

## Tool usage (0-1)
| Metric | Mean |
|---|---|
| tool_appropriateness | 0.984 |
| tool_completeness | 0.938 |
| tool_success_rate | 1.0 |
| efficiency | 0.938 |
| argument_quality | 1.0 |

## By category
| Category | Response | Tools | Combined |
|---|---|---|---|
| Out of scope / guardrails | 0.975 | 1.0 | 0.985 |
| EV charging optimization | 0.972 | 1.0 | 0.984 |
| Seasonal & knowledge-based advice | 0.95 | 1.0 | 0.97 |
| Usage forecasting (ML) | 0.95 | 1.0 | 0.97 |
| Usage analysis & personalization | 0.947 | 0.971 | 0.956 |
| Solar power maximization | 0.92 | 1.0 | 0.952 |
| Thermostat settings | 0.87 | 1.0 | 0.922 |
| Cost savings calculations | 0.895 | 0.912 | 0.902 |
| Appliance scheduling | 0.792 | 0.892 | 0.832 |

## Per test
| Test | Acc | Rel | Comp | Use | Tools | Combined | Pass |
|---|---|---|---|---|---|---|---|
| ev_charging_1 | 9 | 10 | 9 | 10 | 1.0 | 0.967 | yes |
| ev_charging_deadline | 10 | 10 | 10 | 10 | 1.0 | 1.0 | yes |
| thermostat_price_spike | 9 | 10 | 9 | 10 | 1.0 | 0.967 | yes |
| thermostat_heat_precool | 8 | 9 | 7 | 8 | 1.0 | 0.877 | yes |
| dishwasher_offpeak | 5 | 8 | 6 | 7 | 0.825 | 0.711 | NO |
| laundry_weekend | 9 | 10 | 9 | 9 | 1.0 | 0.952 | yes |
| pool_pump_week | 8 | 9 | 7 | 9 | 0.85 | 0.832 | yes |
| solar_self_consumption | 9 | 10 | 9 | 9 | 1.0 | 0.952 | yes |
| usage_history_three_ways | 10 | 10 | 10 | 10 | 1.0 | 1.0 | yes |
| ev_shift_annual_savings | 9 | 10 | 8 | 9 | 1.0 | 0.937 | yes |
| battery_roi | 9 | 10 | 8 | 9 | 0.825 | 0.867 | yes |
| usage_forecast_tomorrow | 10 | 10 | 9 | 9 | 1.0 | 0.97 | yes |
| yesterday_summary | 9 | 10 | 9 | 9 | 0.912 | 0.917 | yes |
| seasonal_winter | 10 | 10 | 9 | 9 | 1.0 | 0.97 | yes |
| personalization_departure | 9 | 10 | 9 | 9 | 1.0 | 0.952 | yes |
| out_of_scope | 10 | 10 | 10 | 9 | 1.0 | 0.985 | yes |

## Strengths
- Accuracy averages 8.94/10 (range 5-10).
- Relevance averages 9.75/10 (range 8-10).
- Completeness averages 8.62/10 (range 6-10).
- Usefulness averages 9.06/10 (range 7-10).
- Clarity averages 9.25/10 (range 7-10).
- Tool appropriateness: 98%.
- Tool success rate: 100%.
- Argument quality: 100%.
- Strongest category: Out of scope / guardrails (0.98).
- 94% of stated $/kWh/°F/% figures trace back to tool outputs.
- Knowledge-base sources cited in 94% of answers.

## Weaknesses
- Weakest category: Appliance scheduling (0.83).
- FAILED dishwasher_offpeak (score 0.71): Inaccurate daily energy use figure for the dishwasher.; Missing specific savings per cycle calculation.; calculate_energy_savings or optimize_device_schedule

## Recommendations
- Tool completeness: the most often skipped tools were {'calculate_energy_savings or optimize_device_schedule': 1, 'calculate_energy_savings': 1}. Add explicit 'always call X for Y' rules to the system prompt for those question types.
- Efficiency: cache identical tool calls within a turn and tell the model to batch independent calls.
- Judge suggestion: Include the exact solar kWh used during the midday window for a more comprehensive solar consideration.
- Judge suggestion: Verify and include the user's normal setpoint from the tool evidence if available.
- Judge suggestion: Mention the exact forecast temperature for Wednesday afternoon to enhance completeness.
- Judge suggestion: Correct the high temperature forecast to 21.8°C (71.2°F).
- Coverage: grow the test set with multi-turn, adversarial and non-California-tariff scenarios, and re-run the evaluation on every prompt change (regression suite).
