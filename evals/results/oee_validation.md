# Brick OEE validation

## Availability gap (computed minus published, matched shifts)

| Period | Window | Published | Matched | No stops | No published | Mean abs (pts) | Median abs (pts) | Max abs (pts) | Within 2 pts | Within 5 pts |
|---|---|---|---|---|---|---|---|---|---|---|
| before | 2025-09-22 to 2025-12-18 | 62 | 62 | 0 | 0 | 13.36 | 3.44 | 52.09 | 38.7% | 61.3% |
| after | 2026-01-30 to 2026-04-03 | 43 | 43 | 0 | 2 | 1.15 | 0.58 | 24.50 | 97.7% | 97.7% |

## OEE gap (computed minus published, matched shifts)

| Period | Window | Published | Matched | No stops | No published | Mean abs (pts) | Median abs (pts) | Max abs (pts) | Within 2 pts | Within 5 pts |
|---|---|---|---|---|---|---|---|---|---|---|
| before | 2025-09-22 to 2025-12-18 | 62 | 62 | 0 | 0 | 12.09 | 3.20 | 48.98 | 41.9% | 61.3% |
| after | 2026-01-30 to 2026-04-03 | 43 | 43 | 0 | 2 | 1.14 | 0.54 | 26.00 | 97.7% | 97.7% |

## Availability gap by planned-day length (post hoc)

The 9 h threshold was chosen after looking at the gaps. It explains the headline;
it does not replace it.

| Period | Group | Shifts | Mean abs (pts) | Median abs (pts) |
|---|---|---|---|---|
| before | planned over 9 h | 13 | 46.54 | 46.74 |
| before | 9 h or less | 49 | 4.55 | 2.07 |
| after | planned over 9 h | 1 | 0.03 | 0.03 |
| after | 9 h or less | 42 | 1.18 | 0.59 |
