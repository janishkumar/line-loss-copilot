# Next-hour stop risk on PIADE

Generated 2026-11-07T05:43:18Z with scikit-learn 1.9.1, feature list hash e28113e96629a2ca. Real PIADE data only.

Long stop: a stop episode of 600 s or more. PR-AUC is average precision; compare it with the base rate (the share of hours with the event), not with 0. Alert volume: top 3 hours per machine per 8 h shift.

| Target | Model | Split | PR-AUC | Base rate | Precision at top 3 | Recall at top 3 |
|---|---|---|---|---|---|---|
| long | logistic | validation | 0.137 | 0.052 | 0.060 | 0.490 |
| long | logistic | test | 0.170 | 0.057 | 0.062 | 0.467 |
| long | hist_gb (served) | validation | 0.148 | 0.052 | 0.066 | 0.539 |
| long | hist_gb (served) | test | 0.182 | 0.057 | 0.069 | 0.513 |
| long | persistence | validation | 0.106 | 0.052 | 0.056 | 0.455 |
| long | persistence | test | 0.114 | 0.057 | 0.060 | 0.445 |
| long | hour_of_week | validation | 0.093 | 0.052 | 0.059 | 0.482 |
| long | hour_of_week | test | 0.110 | 0.057 | 0.067 | 0.501 |
| any | logistic | validation | 0.841 | 0.520 | 0.633 | 0.518 |
| any | logistic | test | 0.853 | 0.523 | 0.622 | 0.503 |
| any | hist_gb (served) | validation | 0.871 | 0.520 | 0.640 | 0.524 |
| any | hist_gb (served) | test | 0.871 | 0.523 | 0.631 | 0.510 |
| any | persistence | validation | 0.709 | 0.520 | 0.558 | 0.457 |
| any | persistence | test | 0.721 | 0.523 | 0.558 | 0.451 |
| any | hour_of_week | validation | 0.749 | 0.520 | 0.613 | 0.502 |
| any | hour_of_week | test | 0.730 | 0.523 | 0.573 | 0.463 |

Per machine, test PR-AUC (base rate in brackets):

| long | s_1 | s_2 | s_3 | s_4 | s_5 |
|---|---|---|---|---|---|
| logistic | 0.179 (0.098) | 0.260 (0.127) | 0.050 (0.032) | 0.045 (0.023) | 0.070 (0.038) |
| hist_gb | 0.189 (0.098) | 0.260 (0.127) | 0.062 (0.032) | 0.057 (0.023) | 0.095 (0.038) |
| persistence | 0.158 (0.098) | 0.195 (0.127) | 0.057 (0.032) | 0.043 (0.023) | 0.080 (0.038) |
| hour_of_week | 0.129 (0.098) | 0.164 (0.127) | 0.053 (0.032) | 0.050 (0.023) | 0.039 (0.038) |

| any | s_1 | s_2 | s_3 | s_4 | s_5 |
|---|---|---|---|---|---|
| logistic | 0.862 (0.692) | 0.866 (0.495) | 0.784 (0.396) | 0.912 (0.542) | 0.792 (0.489) |
| hist_gb | 0.884 (0.692) | 0.889 (0.495) | 0.789 (0.396) | 0.922 (0.542) | 0.819 (0.489) |
| persistence | 0.788 (0.692) | 0.668 (0.495) | 0.605 (0.396) | 0.778 (0.542) | 0.724 (0.489) |
| hour_of_week | 0.788 (0.692) | 0.656 (0.495) | 0.668 (0.396) | 0.790 (0.542) | 0.542 (0.489) |

Leakage checks: every row's latest source timestamp is before t (45628 rows); features rebuilt from only the data known at t match the full build on 200 sampled rows (largest difference 0); the first test hour is 2021-10-01 00:00:00+00:00, the last train hour 2021-06-30 23:00:00+00:00. Shuffled-label test PR-AUC (mean of 5 gradient boosting models fitted on permuted training labels) next to the test base rate:

| Target | Shuffled-label PR-AUC | Test base rate |
|---|---|---|
| long | 0.061 | 0.057 |
| any | 0.506 | 0.523 |

Stop episode duration quantiles (seconds):

| Machine | p50 | p75 | p90 | p95 | p99 | Episodes | Share long |
|---|---|---|---|---|---|---|---|
| all | 57 | 113 | 249 | 412 | 1183 | 89038 | 0.029 |
| s_1 | 76 | 152 | 330 | 533 | 1661 | 31524 | 0.041 |
| s_2 | 36 | 108 | 254 | 461 | 1370 | 16653 | 0.036 |
| s_3 | 89 | 177 | 307 | 495 | 1040 | 7721 | 0.035 |
| s_4 | 38 | 65 | 128 | 201 | 570 | 17319 | 0.009 |
| s_5 | 38 | 82 | 186 | 291 | 692 | 15821 | 0.014 |

Runtime: 15 s.
