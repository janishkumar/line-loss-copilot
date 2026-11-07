# Plan eval (synthetic orders on real capacity and real stops)

- Seeds: 7, 8, 9, 10, 11; 8 replay windows of 14 days from 2021-07-01 (40 seed x window cases per algorithm)
- Date (UTC): 2026-11-07T16:57:41+00:00; git commit 4f9c91294f4e; run time 150.2 s
- CP-SAT: 1 worker, seed 0, deterministic limit 60.0, wall cap 120 s
- Planning inputs (rate, availability, changeover) only from before 2021-07-01; replay windows start on or after it

Orders, BOMs, stock and receipts are synthetic; capacity and the replayed stops are real PIADE data. The numbers say how the schedulers compare on this generator, not what a plant would gain.

Nominal: the plan as the planner sees it (processing at rate x planning availability). Replayed: the same job-to-machine assignment and sequence executed against the real stops of each window, processing at the nominal rate (the stops are explicit). Changeover minutes are work minutes, so the replay leaves them unchanged. Cells are median (q1 to q3).

## Nominal (n = seeds)

| Measure | cpsat | edd | fifo |
|---|---|---|---|
| Late orders | 3 (2 to 9) | 11 (8 to 13) | 10 (8 to 11) |
| Total tardiness (min) | 4353 (3585 to 12409) | 13301 (9468 to 16235) | 18572 (17015 to 19384) |
| Changeover (min) | 315 (301 to 380) | 444 (435 to 479) | 456 (416 to 473) |
| Orders finishing after the 14-day horizon | 1 (1 to 1) | 3 (2 to 3) | 2 (2 to 4) |

## Replayed (n = seeds x windows)

| Measure | cpsat | edd | fifo |
|---|---|---|---|
| Late orders | 4 (3 to 7) | 10 (7.8 to 13) | 9 (8 to 11) |
| Total tardiness (min) | 4648 (3440.8 to 12079) | 11867 (8246.5 to 14294.5) | 16993 (15265 to 19699) |
| Changeover (min) | 315 (301 to 380) | 444 (435 to 479) | 456 (416 to 473) |
| Orders finishing after the 14-day horizon | 1 (1 to 2) | 3 (2 to 3) | 2 (2 to 4.2) |

## CP-SAT solver outcome

feasible: 5 (of 5 instances); stopped by: deterministic_time 5

## Paired: CP-SAT minus baseline

| Comparison | Basis | Measure | n | CP-SAT better | equal | worse | Median diff | Mean diff |
|---|---|---|---|---|---|---|---|---|
| CP-SAT vs EDD | nominal | Total tardiness (min) | 5 | 5 (100%) | 0 | 0 | -5115 | -5626.2 |
| CP-SAT vs EDD | nominal | Late orders | 5 | 5 (100%) | 0 | 0 | -5 | -4.8 |
| CP-SAT vs EDD | replayed | Total tardiness (min) | 40 | 39 (98%) | 0 | 1 | -4100 | -4786.6 |
| CP-SAT vs EDD | replayed | Late orders | 40 | 35 (88%) | 5 | 0 | -4 | -4.1 |
| CP-SAT vs FIFO | nominal | Total tardiness (min) | 5 | 5 (100%) | 0 | 0 | -6163 | -9285.6 |
| CP-SAT vs FIFO | nominal | Late orders | 5 | 5 (100%) | 0 | 0 | -5 | -5.0 |
| CP-SAT vs FIFO | replayed | Total tardiness (min) | 40 | 40 (100%) | 0 | 0 | -6899.5 | -8712.9 |
| CP-SAT vs FIFO | replayed | Late orders | 40 | 40 (100%) | 0 | 0 | -5 | -4.7 |

## Real stops by window

Each cell: realised stopped share of the window / share of the window with no PIADE data at all. A machine with data gaps looks more reliable than it was, because a gap is replayed as no stops. Last row: the stopped share planning used.

| Window start | s_1 stopped / no data | s_2 stopped / no data | s_3 stopped / no data | s_4 stopped / no data | s_5 stopped / no data |
|---|---|---|---|---|---|
| 2021-07-01 | 16.2% / 10.8% | 6.7% / 48.7% | 5.2% / 19.1% | 3.6% / 19.5% | 0.6% / 74.4% |
| 2021-07-15 | 7.5% / 45.8% | 5.8% / 49.2% | 6.5% / 18.4% | 4.1% / 20.3% | 0.0% / 100.0% |
| 2021-07-29 | 9.0% / 11.0% | 5.8% / 54.3% | 3.0% / 8.8% | 5.1% / 26.1% | 0.0% / 100.0% |
| 2021-08-12 | 11.1% / 8.4% | 4.6% / 57.5% | 2.7% / 6.8% | 3.8% / 19.4% | 0.0% / 100.0% |
| 2021-08-26 | 9.1% / 8.2% | 3.9% / 54.3% | 10.0% / 10.9% | 2.9% / 22.1% | 1.2% / 77.9% |
| 2021-09-09 | 7.9% / 10.0% | 6.0% / 47.1% | 4.3% / 10.9% | 3.5% / 15.3% | 3.2% / 8.1% |
| 2021-09-23 | 8.2% / 10.1% | 4.0% / 45.8% | 3.4% / 6.8% | 2.2% / 23.6% | 2.6% / 5.2% |
| 2021-10-07 | 5.7% / 48.0% | 5.2% / 50.4% | 4.3% / 6.0% | 3.7% / 17.0% | 4.5% / 2.6% |
| Planning stopped share (before 2021-07-01) | 10.0% | 9.6% | 6.2% | 4.7% | 3.2% |

## Seeds

| Seed | Orders | Scheduled | Blocked | Load factor | Content sha256 |
|---|---|---|---|---|---|
| 7 | 46 | 42 | 4 | 0.8999 | `4b0b07cf42cb` |
| 8 | 46 | 42 | 4 | 0.9 | `b643aa2bc516` |
| 9 | 46 | 42 | 4 | 0.8999 | `729172676fc2` |
| 10 | 46 | 42 | 4 | 0.8999 | `e41f44b719fc` |
| 11 | 46 | 42 | 4 | 0.9 | `9bbd2fc70bc6` |
