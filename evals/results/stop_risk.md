# Next-hour stop risk on PIADE

Generated 2026-11-07T05:51:09Z with scikit-learn 1.9.1, feature list hash e28113e96629a2ca. Real PIADE data only.

Long stop: a stop episode of 600 s or more. PR-AUC is average precision; compare it with the base rate (the share of hours with the event), not with 0. Default alert volume: top 3 hours per machine per 8 h shift; top 1 is shown for sensitivity.

Headline metrics use every prediction hour. 1263 hours have nothing logged in the following hour, so their label is not observed; live, nobody knows at t whether the next hour will be logged, so they count as negatives here (an alert on one is a false alarm). They are left out of fitting and model selection, and the observed-only columns drop them.

| Target | Model | Split | PR-AUC | Base rate | Precision top 3 | Recall top 3 | Precision top 1 | Recall top 1 | PR-AUC, observed only | Base rate, observed only |
|---|---|---|---|---|---|---|---|---|---|---|
| long | logistic | validation | 0.137 | 0.051 | 0.059 | 0.490 | 0.055 | 0.157 | 0.137 | 0.052 |
| long | logistic | test | 0.170 | 0.055 | 0.062 | 0.467 | 0.063 | 0.163 | 0.170 | 0.057 |
| long | hist_gb (served) | validation | 0.147 | 0.051 | 0.065 | 0.539 | 0.065 | 0.186 | 0.148 | 0.052 |
| long | hist_gb (served) | test | 0.181 | 0.055 | 0.067 | 0.511 | 0.067 | 0.173 | 0.182 | 0.057 |
| long | persistence | validation | 0.105 | 0.051 | 0.055 | 0.455 | 0.035 | 0.102 | 0.106 | 0.052 |
| long | persistence | test | 0.113 | 0.055 | 0.059 | 0.445 | 0.037 | 0.097 | 0.114 | 0.057 |
| long | hour_of_week | validation | 0.090 | 0.051 | 0.057 | 0.474 | 0.063 | 0.181 | 0.093 | 0.052 |
| long | hour_of_week | test | 0.107 | 0.055 | 0.065 | 0.493 | 0.078 | 0.203 | 0.110 | 0.057 |
| any | logistic | validation | 0.839 | 0.505 | 0.617 | 0.516 | 0.635 | 0.183 | 0.841 | 0.520 |
| any | logistic | test | 0.851 | 0.508 | 0.611 | 0.502 | 0.661 | 0.185 | 0.853 | 0.523 |
| any | hist_gb (served) | validation | 0.869 | 0.505 | 0.626 | 0.523 | 0.655 | 0.189 | 0.871 | 0.520 |
| any | hist_gb (served) | test | 0.870 | 0.508 | 0.620 | 0.509 | 0.663 | 0.186 | 0.871 | 0.523 |
| any | persistence | validation | 0.702 | 0.505 | 0.543 | 0.454 | 0.543 | 0.157 | 0.709 | 0.520 |
| any | persistence | test | 0.712 | 0.508 | 0.546 | 0.448 | 0.540 | 0.152 | 0.721 | 0.523 |
| any | hour_of_week | validation | 0.744 | 0.505 | 0.597 | 0.499 | 0.611 | 0.176 | 0.749 | 0.520 |
| any | hour_of_week | test | 0.723 | 0.508 | 0.561 | 0.461 | 0.592 | 0.166 | 0.730 | 0.523 |

Per machine, test PR-AUC (base rate in brackets):

| long | s_1 | s_2 | s_3 | s_4 | s_5 |
|---|---|---|---|---|---|
| logistic | 0.179 (0.096) | 0.260 (0.118) | 0.050 (0.031) | 0.045 (0.022) | 0.069 (0.037) |
| hist_gb | 0.188 (0.096) | 0.260 (0.118) | 0.060 (0.031) | 0.057 (0.022) | 0.094 (0.037) |
| persistence | 0.157 (0.096) | 0.193 (0.118) | 0.055 (0.031) | 0.042 (0.022) | 0.080 (0.037) |
| hour_of_week | 0.126 (0.096) | 0.159 (0.118) | 0.050 (0.031) | 0.048 (0.022) | 0.039 (0.037) |

| any | s_1 | s_2 | s_3 | s_4 | s_5 |
|---|---|---|---|---|---|
| logistic | 0.861 (0.683) | 0.863 (0.460) | 0.780 (0.387) | 0.908 (0.521) | 0.791 (0.483) |
| hist_gb | 0.884 (0.683) | 0.889 (0.460) | 0.785 (0.387) | 0.921 (0.521) | 0.817 (0.483) |
| persistence | 0.784 (0.683) | 0.660 (0.460) | 0.587 (0.387) | 0.762 (0.521) | 0.720 (0.483) |
| hour_of_week | 0.779 (0.683) | 0.649 (0.460) | 0.663 (0.387) | 0.788 (0.521) | 0.531 (0.483) |

Leakage checks. The real guard: features rebuilt from only the data known at t match the full build on 200 sampled rows (largest difference 0). A structural check: every row's latest source timestamp read is before t (45628 rows). The first test hour is 2021-10-01 00:00:00+00:00, the last train hour 2021-06-30 23:00:00+00:00. Shuffled-label test PR-AUC (mean of 5 gradient boosting models fitted on permuted training labels) next to the test base rate:

| Target | Shuffled-label PR-AUC | Test base rate |
|---|---|---|
| long | 0.059 | 0.055 |
| any | 0.492 | 0.508 |

Stop episode duration quantiles (seconds):

| Machine | p50 | p75 | p90 | p95 | p99 | Episodes | Share long |
|---|---|---|---|---|---|---|---|
| all | 57 | 113 | 249 | 412 | 1183 | 89038 | 0.029 |
| s_1 | 76 | 152 | 330 | 533 | 1661 | 31524 | 0.041 |
| s_2 | 36 | 108 | 254 | 461 | 1370 | 16653 | 0.036 |
| s_3 | 89 | 177 | 307 | 495 | 1040 | 7721 | 0.035 |
| s_4 | 38 | 65 | 128 | 201 | 570 | 17319 | 0.009 |
| s_5 | 38 | 82 | 186 | 291 | 692 | 15821 | 0.014 |

Runtime: 16 s.
