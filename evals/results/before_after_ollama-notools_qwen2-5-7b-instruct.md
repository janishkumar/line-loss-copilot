# Before/after eval: ollama-notools / qwen2.5:7b-instruct

- Date (UTC): 2026-11-07T11:57:04+00:00
- Facts found (right direction): 0/4 (0.0%)
- Wrong claims: 0 of 0 (neutral, on flat or ambiguous metrics: 0)

| Fact | Before | After | Readings | Status | Found |
|---|---|---|---|---|---|
| availability | 0.7359 | 0.7002 | value: down, ex_planned_gap: up | ambiguous | - |
| performance | 0.932 | 0.9374 | value: flat, ex_planned_gap: flat | flat | - |
| quality | 0.985 | 0.9682 | value: down, ex_planned_gap: down | scored | no |
| oee | 0.6756 | 0.6355 | value: down, ex_planned_gap: up | ambiguous | - |
| stop_time | 5.238e+05 | 3.459e+05 | total: down, per_shift: down | scored | no |
| stop_count | 612 | 505 | total: down, per_shift: up | ambiguous | - |
| mttr | 841.4 | 862.8 | value: flat | flat | - |
| reason:FAILURE | 1.868e+05 | 1.001e+05 | total: down, per_shift: down | scored | no |
| reason:OPERATIONAL | 1.045e+05 | 3.534e+04 | total: down, per_shift: down | scored | no |
| reason:SETUPS-CHANGEOVERS | 9.594e+04 | 8.43e+04 | total: down, per_shift: up | ambiguous | - |
| reason:MATERIALS | 1.366e+05 | 1.262e+05 | total: down, per_shift: up | ambiguous | - |

Caveats:

- In the before period, 13 days in October 2025 have a published planned time 2.9 to 8.1 hours larger than published production plus stops (docs/data-notes.md). Availability recomputed from the stop log is inflated on those days. Each ratio fact (availability, performance, quality, oee) is therefore also read without the days picked by that rule (truth.planned_gap_days); where the two readings disagree the fact is ambiguous and not scored. Both values are kept in the facts.
- Brick performance and quality are the published per-shift values (no independent source); oee here is recomputed availability times published performance and quality.
- stop_time, stop_count and reason:<group> are totals over windows with different numbers of shifts (truth.shifts). Each is read as a total and per shift; where the two readings disagree the fact is ambiguous and not scored.
- Facts below the minimum effect size (1 percentage point for ratios, 5% relative otherwise) are flat and not scored.
- Windows are calendar months by shift or stop start (UTC). The before data covers 2025-09-22 to 2025-12-18 and the after data 2026-01-30 to 2026-04-03.
