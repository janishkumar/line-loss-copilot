# Plan eval (synthetic orders on real capacity and real stops)

- Seeds: 7, 8, 9, 10, 11; 8 replay windows of 14 days from 2021-07-01 (40 seed x window cases per algorithm)
- Date (UTC): 2026-11-07T17:07:13+00:00; git commit a1cc2098a7cb; run time 150.2 s
- CP-SAT: 1 worker, seed 0, deterministic limit 60.0, wall cap 120.0 s
- Planning inputs: rates and availability from PIADE rows before 2021-07-01; changeover minutes from the brick line stop log (2025 to 2026, a different process and period, not date-filtered). Replay windows start on or after the PIADE cutoff

Orders, BOMs, stock and receipts are synthetic; capacity and the replayed stops are real PIADE data. `edd_batch` is EDD with family batching (window 1440 min). The numbers say how the schedulers compare on this generator, not what a plant would gain.

Nominal: the plan as the planner sees it (processing at rate x planning availability). Replayed: the same job-to-machine assignment and sequence executed against the real stops of each window, processing at the nominal rate (the stops are explicit). Changeover minutes are work minutes, so the replay leaves them unchanged. Cells are median (q1 to q3).

## Nominal (n = seeds)

| Measure | cpsat | edd_batch | edd | fifo |
|---|---|---|---|---|
| Late orders | 3 (2 to 9) | 11 (8 to 14) | 11 (8 to 13) | 10 (8 to 11) |
| Total tardiness (min) | 4353 (3585 to 12409) | 19171 (11198 to 32687) | 13301 (9468 to 16235) | 18572 (17015 to 19384) |
| Changeover (min) | 315 (301 to 380) | 270 (256 to 320) | 444 (435 to 479) | 456 (416 to 473) |
| Orders finishing after the 14-day horizon | 1 (1 to 1) | 5 (4 to 5) | 3 (2 to 3) | 2 (2 to 4) |

## Replayed (n = seeds x windows)

| Measure | cpsat | edd_batch | edd | fifo |
|---|---|---|---|---|
| Late orders | 4 (3 to 7) | 11 (7 to 13) | 10 (7.8 to 13) | 9 (8 to 11) |
| Total tardiness (min) | 4648 (3440.8 to 12079) | 16720.5 (9564.8 to 29219) | 11867 (8246.5 to 14294.5) | 16993 (15265 to 19699) |
| Changeover (min) | 315 (301 to 380) | 270 (256 to 320) | 444 (435 to 479) | 456 (416 to 473) |
| Orders finishing after the 14-day horizon | 1 (1 to 2) | 4 (3 to 5) | 3 (2 to 3) | 2 (2 to 4.2) |

## CP-SAT solver outcome

feasible: 5 (of 5 instances); stopped by: deterministic_time 5

## Paired: CP-SAT minus baseline

| Comparison | Basis | Measure | n | CP-SAT better | equal | worse | Median diff | Mean diff |
|---|---|---|---|---|---|---|---|---|
| CP-SAT vs EDD_BATCH | nominal | Total tardiness (min) | 5 | 5 (100%) | 0 | 0 | -14818 | -13224.2 |
| CP-SAT vs EDD_BATCH | nominal | Late orders | 5 | 5 (100%) | 0 | 0 | -5 | -6.0 |
| CP-SAT vs EDD_BATCH | replayed | Total tardiness (min) | 40 | 40 (100%) | 0 | 0 | -12421.5 | -11661.4 |
| CP-SAT vs EDD_BATCH | replayed | Late orders | 40 | 40 (100%) | 0 | 0 | -4 | -5.5 |
| CP-SAT vs EDD | nominal | Total tardiness (min) | 5 | 5 (100%) | 0 | 0 | -5115 | -5626.2 |
| CP-SAT vs EDD | nominal | Late orders | 5 | 5 (100%) | 0 | 0 | -5 | -4.8 |
| CP-SAT vs EDD | replayed | Total tardiness (min) | 40 | 39 (98%) | 0 | 1 | -4100 | -4786.6 |
| CP-SAT vs EDD | replayed | Late orders | 40 | 35 (88%) | 5 | 0 | -4 | -4.1 |
| CP-SAT vs FIFO | nominal | Total tardiness (min) | 5 | 5 (100%) | 0 | 0 | -6163 | -9285.6 |
| CP-SAT vs FIFO | nominal | Late orders | 5 | 5 (100%) | 0 | 0 | -5 | -5.0 |
| CP-SAT vs FIFO | replayed | Total tardiness (min) | 40 | 40 (100%) | 0 | 0 | -6899.5 | -8712.9 |
| CP-SAT vs FIFO | replayed | Late orders | 40 | 40 (100%) | 0 | 0 | -5 | -4.7 |

## Real stops by window

Each cell: realised stopped time over time with data (the denominator planning availability uses, so it compares with the last row) / share of the window with no PIADE data at all. A gap is replayed as no stops, so a machine with gaps is stopped less, over the whole window, than the first figure suggests. Last row: the stopped share planning used, over covered time.

| Window start | s_1 stopped of covered / no data | s_2 stopped of covered / no data | s_3 stopped of covered / no data | s_4 stopped of covered / no data | s_5 stopped of covered / no data |
|---|---|---|---|---|---|
| 2021-07-01 | 18.2% / 10.8% | 13.1% / 48.7% | 6.4% / 19.1% | 4.5% / 19.5% | 2.3% / 74.4% |
| 2021-07-15 | 13.9% / 45.8% | 11.5% / 49.2% | 8.0% / 18.4% | 5.1% / 20.3% | n/a / 100.0% |
| 2021-07-29 | 10.1% / 11.0% | 12.7% / 54.3% | 3.3% / 8.8% | 6.9% / 26.1% | n/a / 100.0% |
| 2021-08-12 | 12.2% / 8.4% | 10.9% / 57.5% | 2.9% / 6.8% | 4.7% / 19.4% | n/a / 100.0% |
| 2021-08-26 | 9.9% / 8.2% | 8.6% / 54.3% | 11.2% / 10.9% | 3.8% / 22.1% | 5.4% / 77.9% |
| 2021-09-09 | 8.7% / 10.0% | 11.4% / 47.1% | 4.9% / 10.9% | 4.1% / 15.3% | 3.5% / 8.1% |
| 2021-09-23 | 9.2% / 10.1% | 7.4% / 45.8% | 3.6% / 6.8% | 2.8% / 23.6% | 2.7% / 5.2% |
| 2021-10-07 | 11.0% / 48.0% | 10.4% / 50.4% | 4.6% / 6.0% | 4.4% / 17.0% | 4.7% / 2.6% |
| Median over windows | 10.5% | 11.1% | 4.7% | 4.5% | 3.5% |
| Planning stopped share of covered time (before 2021-07-01) | 10.0% | 9.6% | 6.2% | 4.7% | 3.2% |

## Seeds

| Seed | Orders | Scheduled | Blocked | Load factor | Content sha256 |
|---|---|---|---|---|---|
| 7 | 46 | 42 | 4 | 0.8999 | `4b0b07cf42cb` |
| 8 | 46 | 42 | 4 | 0.9 | `b643aa2bc516` |
| 9 | 46 | 42 | 4 | 0.8999 | `729172676fc2` |
| 10 | 46 | 42 | 4 | 0.8999 | `e41f44b719fc` |
| 11 | 46 | 42 | 4 | 0.9 | `9bbd2fc70bc6` |
