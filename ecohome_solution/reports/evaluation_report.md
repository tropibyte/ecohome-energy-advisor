# EcoHome Energy Advisor - Evaluation Report
Generated 2026-09-26T17:03:45 | agent `gpt-4.1-mini` | judge `gpt-4o`

## Overall
| Metric | Value |
|---|---|
| overall score | 0.928 |
| response quality score | 0.91 |
| tool usage score | 0.956 |
| pass rate | 0.938 |
| tests passed | 15 |
| tests total | 16 |
| mean latency s | 13.1 |
| p90 latency s | 16.3 |
| mean tool calls | 3.5 |
| mean llm calls | 4.2 |
| numeric grounding ratio | 0.924 |
| knowledge base citation rate | 0.938 |
| tool error count | 0 |

## Response quality (1-10)
| Metric | Mean | Min | Max |
|---|---|---|---|
| accuracy | 8.94 | 7 | 10 |
| relevance | 9.81 | 9 | 10 |
| completeness | 8.81 | 8 | 10 |
| usefulness | 9.0 | 8 | 10 |
| clarity | 9.31 | 9 | 10 |

## Tool usage (0-1)
| Metric | Mean |
|---|---|
| tool_appropriateness | 0.969 |
| tool_completeness | 0.906 |
| tool_success_rate | 1.0 |
| efficiency | 1.0 |
| argument_quality | 1.0 |

## By category
| Category | Response | Tools | Combined |
|---|---|---|---|
| Seasonal & knowledge-based advice | 1.0 | 1.0 | 1.0 |
| Out of scope / guardrails | 0.975 | 1.0 | 0.985 |
| Usage forecasting (ML) | 0.95 | 1.0 | 0.97 |
| EV charging optimization | 0.948 | 1.0 | 0.968 |
| Solar power maximization | 0.92 | 1.0 | 0.952 |
| Usage analysis & personalization | 0.938 | 0.971 | 0.951 |
| Thermostat settings | 0.855 | 1.0 | 0.913 |
| Appliance scheduling | 0.833 | 1.0 | 0.9 |
| Cost savings calculations | 0.895 | 0.694 | 0.814 |

## Per test
| Test | Acc | Rel | Comp | Use | Tools | Combined | Pass |
|---|---|---|---|---|---|---|---|
| ev_charging_1 | 9 | 10 | 9 | 10 | 1.0 | 0.967 | yes |
| ev_charging_deadline | 10 | 10 | 9 | 9 | 1.0 | 0.97 | yes |
| thermostat_price_spike | 9 | 10 | 9 | 9 | 1.0 | 0.952 | yes |
| thermostat_heat_precool | 7 | 9 | 8 | 8 | 1.0 | 0.874 | yes |
| dishwasher_offpeak | 9 | 10 | 9 | 9 | 1.0 | 0.952 | yes |
| laundry_weekend | 7 | 9 | 8 | 8 | 1.0 | 0.874 | yes |
| pool_pump_week | 7 | 9 | 8 | 8 | 1.0 | 0.874 | yes |
| solar_self_consumption | 9 | 10 | 9 | 9 | 1.0 | 0.952 | yes |
| usage_history_three_ways | 10 | 10 | 10 | 10 | 1.0 | 1.0 | yes |
| ev_shift_annual_savings | 9 | 10 | 8 | 9 | 0.825 | 0.867 | yes |
| battery_roi | 9 | 10 | 8 | 9 | 0.562 | 0.762 | NO |
| usage_forecast_tomorrow | 10 | 10 | 9 | 9 | 1.0 | 0.97 | yes |
| yesterday_summary | 9 | 10 | 9 | 9 | 0.912 | 0.917 | yes |
| seasonal_winter | 10 | 10 | 10 | 10 | 1.0 | 1.0 | yes |
| personalization_departure | 9 | 10 | 8 | 9 | 1.0 | 0.937 | yes |
| out_of_scope | 10 | 10 | 10 | 9 | 1.0 | 0.985 | yes |

## Strengths
- Accuracy averages 8.94/10 (range 7-10).
- Relevance averages 9.81/10 (range 9-10).
- Completeness averages 8.81/10 (range 8-10).
- Usefulness averages 9.0/10 (range 8-10).
- Clarity averages 9.31/10 (range 9-10).
- Tool appropriateness: 97%.
- Tool success rate: 100%.
- Efficiency: 100%.
- Argument quality: 100%.
- Strongest category: Seasonal & knowledge-based advice (1.00).
- 92% of stated $/kWh/°F/% figures trace back to tool outputs.
- Knowledge-base sources cited in 94% of answers.

## Weaknesses
- Weakest category: Cost savings calculations (0.81).
- FAILED battery_roi (score 0.76): Lacks detailed explanation of the peak/export price spread.; Estimated annual savings slightly below expected range, affecting payback period.; calculate_energy_savings

## Recommendations
- Tool completeness: the most often skipped tools were {'calculate_energy_savings or optimize_device_schedule': 1, 'calculate_energy_savings': 1, 'analyze_usage_patterns or get_recent_energy_summary or query_solar_generation': 1}. Add explicit 'always call X for Y' rules to the system prompt for those question types.
- Judge suggestion: Include the exact solar midday rate in the response for completeness.
- Judge suggestion: Consider providing a brief explanation of how solar power integration could be optimized for users with flexible schedules.
- Judge suggestion: Clarify the assumed departure time to ensure it aligns with the user's needs.
- Judge suggestion: Consider confirming the user's typical charging habits to personalize savings estimates further.
- Coverage: grow the test set with multi-turn, adversarial and non-California-tariff scenarios, and re-run the evaluation on every prompt change (regression suite).
