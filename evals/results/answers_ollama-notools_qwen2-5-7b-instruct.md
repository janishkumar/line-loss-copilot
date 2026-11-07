# Answer eval: ollama-notools / qwen2.5:7b-instruct

- Model: `qwen2.5:7b-instruct` (digest/version: 845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e; ollama 0.40.14; claude cli n/a)
- Date (UTC): 2026-11-07T11:57:04+00:00
- Question set hash: `c32c30730107fd13be361ef1916b58909f2081f8e25ce93f170e186941d88f7c` (70 of 70 questions)

| Measure | Value |
|---|---|
| Accuracy, all | 9/70 (12.9%) |
| Accuracy, answerable | 0/60 (0.0%) |
| Accuracy, unanswerable (says not available) | 9/10 (90.0%) |
| Cited rows that support the answer (micro) | 0/38 (0.0%) |
| Answers fully supported by their citations | 0.0% |
| Answers with no citations | 58.6% |
| Answers with a parseable ANSWER line (format_ok) | 90.0% |
| Errors (answer key, runner, scoring or loop cut-off) | 0 |
| Stopped on time budget / round limit (counted wrong) | 0 / 0 |
| Questions where a model call filled the context (Ollama) | 0 |

| Template | Correct |
|---|---|
| oee_month | 0/6 |
| availability_month | 0/7 |
| top_reason | 0/9 |
| top_reason_lost | 0/6 |
| mttr_month | 0/6 |
| mtbf_month | 0/5 |
| stop_count | 0/6 |
| repeat_chains | 0/5 |
| note_date | 0/5 |
| compare_availability | 0/5 |
| unanswerable | 9/10 |

| Id | Expected | Extracted | Correct | Cited / supported | Latency s |
|---|---|---|---|---|---|
| oee_month_01 | 39.95% | NOT_AVAILABLE | no | 1 / 0 | 1.44 |
| oee_month_02 | 43.54% | NOT_AVAILABLE | no | 0 / 0 | 0.81 |
| oee_month_03 | 58.05% | NOT_AVAILABLE | no | 1 / 0 | 1.15 |
| oee_month_04 | 38.56% | NOT_AVAILABLE | no | 1 / 0 | 1.16 |
| oee_month_05 | 44.38% | NOT_AVAILABLE | no | 1 / 0 | 1.18 |
| oee_month_06 | 38.69% | NOT_AVAILABLE | no | 1 / 0 | 1.14 |
| availability_month_01 | 63.75% | 95% | no | 1 / 0 | 3.73 |
| availability_month_02 | 70.21% | 95% | no | 1 / 0 | 3.94 |
| availability_month_03 | 66.11% | 95% | no | 0 / 0 | 2.0 |
| availability_month_04 | 47.37% | 95% | no | 0 / 0 | 2.0 |
| availability_month_05 | 65.25% | NOT_AVAILABLE | no | 0 / 0 | 3.53 |
| availability_month_06 | 34.70% | 95% | no | 0 / 0 | 2.04 |
| availability_month_07 | 62.96% | NOT_AVAILABLE | no | 0 / 0 | 3.51 |
| top_reason_01 | MATERIALS | material supply [event:12345, event:12346, event:12347] | no | 3 / 0 | 4.2 |
| top_reason_02 | FAILURE | material supply | no | 3 / 0 | 2.97 |
| top_reason_03 | FAILURE | material supply | no | 3 / 0 | 2.93 |
| top_reason_04 | A_065 | NOT_AVAILABLE | no | 0 / 0 | 4.34 |
| top_reason_05 | A_101 | 004 | no | 1 / 0 | 2.37 |
| top_reason_06 | A_101 | 004 | no | 1 / 0 | 2.35 |
| top_reason_07 | A_065 | 004 | no | 1 / 0 | 2.35 |
| top_reason_08 | A_006 | 004 | no | 1 / 0 | 2.36 |
| top_reason_09 | A_101 | 004 | no | 1 / 0 | 2.36 |
| top_reason_lost_01 | 23.750 h | 2 | no | 2 / 0 | 4.97 |
| top_reason_lost_02 | 10.883 h | 2 | no | 2 / 0 | 4.97 |
| top_reason_lost_03 | 11.892 h | NOT_AVAILABLE | no | 0 / 0 | 0.8 |
| top_reason_lost_04 | 30.353 h | NOT_AVAILABLE | no | 0 / 0 | 0.8 |
| top_reason_lost_05 | 36.966 h | NOT_AVAILABLE | no | 0 / 0 | 0.8 |
| top_reason_lost_06 | 19.915 h | NOT_AVAILABLE | no | 0 / 0 | 0.8 |
| mttr_month_01 | 13.20 min | NOT_AVAILABLE | no | 0 / 0 | 0.86 |
| mttr_month_02 | 12.56 min | NOT_AVAILABLE | no | 0 / 0 | 0.85 |
| mttr_month_03 | 1.61 min | NOT_AVAILABLE | no | 0 / 0 | 0.85 |
| mttr_month_04 | 1.31 min | NOT_AVAILABLE | no | 0 / 0 | 0.85 |
| mttr_month_05 | 1.27 min | NOT_AVAILABLE | no | 1 / 0 | 1.14 |
| mttr_month_06 | 1.48 min | NOT_AVAILABLE | no | 0 / 0 | 0.84 |
| mtbf_month_01 | 179.10 min | NOT_AVAILABLE | no | 0 / 0 | 0.85 |
| mtbf_month_02 | 69.64 min | NOT_AVAILABLE | no | 0 / 0 | 0.84 |
| mtbf_month_03 | 19.09 min | NOT_AVAILABLE | no | 0 / 0 | 0.85 |
| mtbf_month_04 | 36.67 min | NOT_AVAILABLE | no | 0 / 0 | 0.86 |
| mtbf_month_05 | 17.30 min | NOT_AVAILABLE | no | 0 / 0 | 0.85 |
| stop_count_01 | 196 | NOT_AVAILABLE | no | 1 / 0 | 3.83 |
| stop_count_02 | 194 | NOT_AVAILABLE | no | 1 / 0 | 4.02 |
| stop_count_03 | 1483 | NOT_AVAILABLE | no | 0 / 0 | 0.85 |
| stop_count_04 | 1208 | NOT_AVAILABLE | no | 0 / 0 | 0.8 |
| stop_count_05 | 577 | NOT_AVAILABLE | no | 0 / 0 | 0.84 |
| stop_count_06 | 1315 | NOT_AVAILABLE | no | 0 / 0 | 0.85 |
| repeat_chains_01 | 4 | NOT_AVAILABLE | no | 0 / 0 | 0.95 |
| repeat_chains_02 | 7 |  | no | 0 / 0 | 50.84 |
| repeat_chains_03 | 34 | NOT_AVAILABLE | no | 0 / 0 | 0.97 |
| repeat_chains_04 | 29 | NOT_AVAILABLE | no | 0 / 0 | 0.95 |
| repeat_chains_05 | 41 | NOT_AVAILABLE | no | 0 / 0 | 0.95 |
| note_date_01 | 2025-10-08 | 2022-03-01 | no | 1 / 0 | 3.18 |
| note_date_02 | 2026-03-24 | 2022-03-01 | no | 1 / 0 | 3.25 |
| note_date_03 | 2026-02-25 | NOT_AVAILABLE | no | 0 / 0 | 3.37 |
| note_date_04 | 2025-11-24 | 2022-03-01 | no | 1 / 0 | 3.15 |
| note_date_05 | 2026-03-05 | 2025-10-02 | no | 2 / 0 | 4.85 |
| compare_availability_01 | +2.87 pp |  | no | 0 / 0 | 50.87 |
| compare_availability_02 | +9.61 pp |  | no | 0 / 0 | 50.77 |
| compare_availability_03 | -6.59 pp |  | no | 0 / 0 | 50.78 |
| compare_availability_04 | +11.03 pp |  | no | 0 / 0 | 50.85 |
| compare_availability_05 | +6.48 pp |  | no | 0 / 0 | 50.93 |
| na_01 | NOT_AVAILABLE | NOT_AVAILABLE | yes | 1 / 0 | 1.18 |
| na_02 | NOT_AVAILABLE | NOT_AVAILABLE | yes | 1 / 0 | 1.15 |
| na_03 | NOT_AVAILABLE | NOT_AVAILABLE | yes | 0 / 0 | 3.12 |
| na_04 | NOT_AVAILABLE | NOT_AVAILABLE | yes | 0 / 0 | 0.91 |
| na_05 | NOT_AVAILABLE | NOT_AVAILABLE | yes | 0 / 0 | 0.86 |
| na_06 | NOT_AVAILABLE | NOT_AVAILABLE | yes | 1 / 0 | 1.15 |
| na_07 | NOT_AVAILABLE | NOT_AVAILABLE | yes | 1 / 0 | 1.15 |
| na_08 | NOT_AVAILABLE |  | no | 0 / 0 | 51.34 |
| na_09 | NOT_AVAILABLE | NOT_AVAILABLE | yes | 1 / 0 | 1.33 |
| na_10 | NOT_AVAILABLE | NOT_AVAILABLE | yes | 0 / 0 | 0.86 |
