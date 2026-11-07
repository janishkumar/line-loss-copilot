# Answer eval: ollama / qwen2.5:7b-instruct

- Model: `qwen2.5:7b-instruct` (digest/version: 845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e; ollama 0.40.14; claude cli n/a)
- Date (UTC): 2026-11-07T10:33:05+00:00
- Question set hash: `c32c30730107fd13be361ef1916b58909f2081f8e25ce93f170e186941d88f7c` (70 of 70 questions)

| Measure | Value |
|---|---|
| Accuracy, all | 38/70 (54.3%) |
| Accuracy, answerable | 28/60 (46.7%) |
| Accuracy, unanswerable (says not available) | 10/10 (100.0%) |
| Cited rows that support the answer (micro) | 7/7 (100.0%) |
| Answers fully supported by their citations | 4.3% |
| Answers with no citations | 95.7% |
| Answers with a parseable ANSWER line (format_ok) | 97.1% |
| Errors (answer key, runner, scoring or loop cut-off) | 1 |
| Stopped on time budget / round limit (counted wrong) | 0 / 1 |
| Questions where a model call filled the context (Ollama) | 2 |

| Template | Correct |
|---|---|
| oee_month | 3/6 |
| availability_month | 5/7 |
| top_reason | 4/9 |
| top_reason_lost | 2/6 |
| mttr_month | 5/6 |
| mtbf_month | 2/5 |
| stop_count | 0/6 |
| repeat_chains | 2/5 |
| note_date | 5/5 |
| compare_availability | 0/5 |
| unanswerable | 10/10 |

| Id | Expected | Extracted | Correct | Cited / supported | Latency s |
|---|---|---|---|---|---|
| oee_month_01 | 39.95% | 39.95 | yes | 0 / 0 | 46.66 |
| oee_month_02 | 43.54% | No data available for the brick line in the specified period | no | 0 / 0 | 177.87 |
| oee_month_03 | 58.05% | OEE metrics for PIADE machine s_1 in June 2020. | no | 0 / 0 | 141.67 |
| oee_month_04 | 38.56% | No data available. | no | 0 / 0 | 145.1 |
| oee_month_05 | 44.38% | 44.38% | yes | 0 / 0 | 149.27 |
| oee_month_06 | 38.69% | 38.69% | yes | 3 / 3 | 31.12 |
| availability_month_01 | 63.75% | 50.39% | no | 1 / 1 | 141.82 |
| availability_month_02 | 70.21% | 70.21 | yes | 0 / 0 | 25.58 |
| availability_month_03 | 66.11% | 66.113% | yes | 0 / 0 | 29.52 |
| availability_month_04 | 47.37% | 47.37% | yes | 0 / 0 | 36.42 |
| availability_month_05 | 65.25% | 65.25% | yes | 0 / 0 | 35.66 |
| availability_month_06 | 34.70% | OEE 26.16% | no | 0 / 0 | 140.9 |
| availability_month_07 | 62.96% | 62.96% | yes | 0 / 0 | 35.91 |
| top_reason_01 | MATERIALS | NOT_AVAILABLE | no | 0 / 0 | 77.96 |
| top_reason_02 | FAILURE | NOT_AVAILABLE | no | 0 / 0 | 21.33 |
| top_reason_03 | FAILURE | NOT_AVAILABLE | no | 0 / 0 | 76.76 |
| top_reason_04 | A_065 |  | no | 0 / 0 | 41.61 |
| top_reason_05 | A_101 | A_101 | yes | 0 / 0 | 27.42 |
| top_reason_06 | A_101 | A_101 | yes | 0 / 0 | 26.72 |
| top_reason_07 | A_065 | A_065 | yes | 0 / 0 | 40.11 |
| top_reason_08 | A_006 | A_006 | yes | 0 / 0 | 25.28 |
| top_reason_09 | A_101 | NOT_AVAILABLE | no | 0 / 0 | 20.4 |
| top_reason_lost_01 | 23.750 h | NOT_AVAILABLE | no | 0 / 0 | 23.42 |
| top_reason_lost_02 | 10.883 h | NOT_AVAILABLE | no | 0 / 0 | 23.5 |
| top_reason_lost_03 | 11.892 h | The stop events for the specified alarm codes are not availa | no | 0 / 0 | 273.16 |
| top_reason_lost_04 | 30.353 h | 28.5 | no | 0 / 0 | 26.71 |
| top_reason_lost_05 | 36.966 h | 36.97 | yes | 0 / 0 | 33.37 |
| top_reason_lost_06 | 19.915 h | 19.716 | yes | 0 / 0 | 26.85 |
| mttr_month_01 | 13.20 min | 13.2 | yes | 0 / 0 | 19.67 |
| mttr_month_02 | 12.56 min | 12.56 | yes | 3 / 3 | 28.73 |
| mttr_month_03 | 1.61 min | 1.677 | no | 0 / 0 | 27.2 |
| mttr_month_04 | 1.31 min | 1.314 | yes | 0 / 0 | 26.79 |
| mttr_month_05 | 1.27 min | 1.26282 | yes | 0 / 0 | 27.14 |
| mttr_month_06 | 1.48 min | 1.48 | yes | 0 / 0 | 28.45 |
| mtbf_month_01 | 179.10 min | Availability 70.76%, Performance 93.95%, Quality 97.66%, Cal | no | 0 / 0 | 161.15 |
| mtbf_month_02 | 69.64 min | NOT_AVAILABLE | no | 0 / 0 | 64.51 |
| mtbf_month_03 | 19.09 min | 19.09 | yes | 0 / 0 | 27.14 |
| mtbf_month_04 | 36.67 min | 36.67 | yes | 0 / 0 | 28.36 |
| mtbf_month_05 | 17.30 min | NOT_AVAILABLE | no | 0 / 0 | 31.22 |
| stop_count_01 | 196 | NOT_AVAILABLE | no | 0 / 0 | 16.1 |
| stop_count_02 | 194 |  | no | 0 / 0 | 194.5 |
| stop_count_03 | 1483 | Varying OEE performance with low availability in October and | no | 0 / 0 | 254.93 |
| stop_count_04 | 1208 | The requested data is not available. | no | 0 / 0 | 222.29 |
| stop_count_05 | 577 | The requested period has no available data. | no | 0 / 0 | 128.25 |
| stop_count_06 | 1315 | The requested data is not available for the specified period | no | 0 / 0 | 102.89 |
| repeat_chains_01 | 4 | NOT_AVAILABLE | no | 0 / 0 | 14.41 |
| repeat_chains_02 | 7 | NOT_AVAILABLE | no | 0 / 0 | 22.71 |
| repeat_chains_03 | 34 | 32 | no | 0 / 0 | 77.56 |
| repeat_chains_04 | 29 | 29 | yes | 0 / 0 | 87.84 |
| repeat_chains_05 | 41 | 41 | yes | 0 / 0 | 85.33 |
| note_date_01 | 2025-10-08 | 2025-10-08 | yes | 0 / 0 | 16.79 |
| note_date_02 | 2026-03-24 | 2026-03-24 | yes | 0 / 0 | 11.49 |
| note_date_03 | 2026-02-25 | 2026-02-25 | yes | 0 / 0 | 11.13 |
| note_date_04 | 2025-11-24 | 2025-11-24 | yes | 0 / 0 | 55.62 |
| note_date_05 | 2026-03-05 | 2026-03-05 | yes | 0 / 0 | 9.96 |
| compare_availability_01 | +2.87 pp | 0.00457085 | no | 0 / 0 | 78.24 |
| compare_availability_02 | +9.61 pp | 17.4 | no | 0 / 0 | 70.47 |
| compare_availability_03 | -6.59 pp | The requested data is not available for the brick line in th | no | 0 / 0 | 229.86 |
| compare_availability_04 | +11.03 pp | NOT_AVAILABLE | no | 0 / 0 | 90.97 |
| compare_availability_05 | +6.48 pp | NOT_AVAILABLE | no | 0 / 0 | 72.67 |
| na_01 | NOT_AVAILABLE | NOT_AVAILABLE | yes | 0 / 0 | 2.83 |
| na_02 | NOT_AVAILABLE | NOT_AVAILABLE | yes | 0 / 0 | 68.96 |
| na_03 | NOT_AVAILABLE | NOT_AVAILABLE | yes | 0 / 0 | 22.73 |
| na_04 | NOT_AVAILABLE | NOT_AVAILABLE | yes | 0 / 0 | 101.54 |
| na_05 | NOT_AVAILABLE | NOT_AVAILABLE | yes | 0 / 0 | 33.89 |
| na_06 | NOT_AVAILABLE | NOT_AVAILABLE | yes | 0 / 0 | 100.84 |
| na_07 | NOT_AVAILABLE | NOT_AVAILABLE | yes | 0 / 0 | 14.39 |
| na_08 | NOT_AVAILABLE | NOT_AVAILABLE | yes | 0 / 0 | 15.33 |
| na_09 | NOT_AVAILABLE | NOT_AVAILABLE | yes | 0 / 0 | 3.38 |
| na_10 | NOT_AVAILABLE | NOT_AVAILABLE | yes | 0 / 0 | 63.9 |
