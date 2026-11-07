# line-loss-copilot

Mid-sized plants lose capacity to stops, changeovers, slow running, shortages and defects. The evidence sits in machine logs, spreadsheets and operator notes that nobody can search, so planning reports take hours and the same failures come back. This project turns those sources into one trusted data layer, computes OEE from events, and answers questions with every number traced to source rows. The AI proposes; a person approves.

## Stage 1 results

<!-- oee:start -->
### Brick line: recomputed availability against published

Availability is recomputed from the stop log (planned time minus the union of in-OEE stop intervals, clipped to the date). Planned time is the one published input. Gap = recomputed minus published, in percentage points, over every shift with both stops and a published row. Nothing is filtered.

| Period | Window | Matched shifts | Mean abs gap | Median abs gap | Max abs gap | Within 2 pts | Within 5 pts | Mean signed |
|---|---|---|---|---|---|---|---|---|
| before | 2025-09-22 to 2025-12-18 | 62 | 13.36 pts | 3.44 pts | 52.09 pts | 38.7% | 61.3% | 6.59 pts |
| after | 2026-01-30 to 2026-04-03 | 43 | 1.15 pts | 0.58 pts | 24.50 pts | 97.7% | 97.7% | -0.01 pts |

- before: 62 published shifts, 62 matched, 0 with no stops, 0 stop-only days with no published row (shown, not dropped).
- after: 43 published shifts, 43 matched, 0 with no stops, 2 stop-only days with no published row (shown, not dropped).

Breakdown chosen after seeing the gaps (the 9 h threshold was picked once the October block stood out, so read it as explanation, not as a better headline):

| Period | Planned-day length | Shifts | Mean abs gap | Median abs gap |
|---|---|---|---|---|
| before | over 9 h | 13 | 46.54 pts | 46.74 pts |
| before | 9 h or less | 49 | 4.55 pts | 2.07 pts |
| after | over 9 h | 1 | 0.03 pts | 0.03 pts |
| after | 9 h or less | 42 | 1.18 pts | 0.59 pts |

### Brick line: full OEE with published performance and quality

Availability is recomputed; performance and quality are the published values (the files hold no event-level counts to recompute them from). The published P and Q enter this comparison as given. Same shifts and windows as above.

| Period | Window | Matched shifts | Mean abs gap | Median abs gap | Max abs gap | Within 2 pts | Within 5 pts |
|---|---|---|---|---|---|---|---|
| before | 2025-09-22 to 2025-12-18 | 62 | 12.09 pts | 3.20 pts | 48.98 pts | 41.9% | 61.3% |
| after | 2026-01-30 to 2026-04-03 | 43 | 1.14 pts | 0.54 pts | 26.00 pts | 97.7% | 97.7% |

### PIADE: OEE per machine over full coverage

Each machine is its own line. Time-weighted: seconds and counts are summed, then ratios computed. Windows are each machine's first to last assumed shift (UTC). The ideal rate is estimated from `speed`, so OEE is shown at p90, p95 (headline) and p99. P is count-based; time-based P is the cross-check.

| Machine | Window | Planned h | A | P count (p95) | P time | Q | OEE p90 | OEE p95 | OEE p99 |
|---|---|---|---|---|---|---|---|---|---|
| s_1 | 2020-01-01 to 2021-12-31 | 11,905 | 0.777 | 0.786 | 0.833 | 0.998 | 0.616 | 0.609 | 0.596 |
| s_2 | 2020-06-15 to 2021-12-31 | 4,163 | 0.413 | 0.704 | 0.789 | 0.993 | 0.289 | 0.289 | 0.289 |
| s_3 | 2020-10-07 to 2022-01-01 | 6,759 | 0.492 | 0.777 | 0.908 | 0.997 | 0.381 | 0.381 | 0.358 |
| s_4 | 2019-12-31 to 2022-01-01 | 6,132 | 0.691 | 0.567 | 0.637 | 0.996 | 0.390 | 0.390 | 0.371 |
| s_5 | 2020-01-11 to 2022-01-01 | 8,635 | 0.655 | 0.772 | 0.815 | 0.997 | 0.504 | 0.504 | 0.504 |

These PIADE figures have no published value to check against; they are computed, not validated. Brick and PIADE numbers are never combined.

Assumptions:

- PIADE shifts are 3 x 8 h in UTC from 06:00, because the data gives no site timezone.
- Idle counts as planned time; scheduled downtime does not.
- P uses total input (`pi`) over ideal rate times run hours, with the ideal rate a percentile of observed set speed.
- Q is output over input, capped at 1 per shift.
- Counters are end-aligned (a reading belongs to the row it ends); resets and glitches are dropped.
- Shifts with a counter glitch on a run row, or run time with no input counted, are left out of count-based P and Q; A and time-based P keep them.
- Brick planned time and, in the OEE comparison, published P and Q are published inputs.

Details and the reasoning behind each choice are in `docs/data-notes.md`. Regenerate with `make validate-oee && make report`.
<!-- oee:end -->
