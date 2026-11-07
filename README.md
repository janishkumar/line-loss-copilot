# line-loss-copilot

Mid-sized plants lose capacity to stops, changeovers, slow running, shortages and defects. The evidence sits in machine logs, spreadsheets and operator notes that nobody can search, so planning reports take hours and the same failures come back. This project turns those sources into one trusted data layer, computes OEE from events, and answers questions with every number traced to source rows. The AI proposes; a person approves.

**Decision it supports:** where a line is losing time, and whether those numbers can be trusted before anyone builds an assistant on top of them. Stage 1 is the trusted layer: both real datasets in Postgres with row-level lineage, OEE computed from events, and a published-versus-recomputed check on the brick line.

Status: stage 1 of 5 (data layer and true OEE). Stages 2 onward (copilot, approved actions, scheduling, visual inspection) are not built yet.

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

Each machine is its own line. Time-weighted: seconds and counts are summed, then ratios computed. Windows are the dates of each machine's first and last assumed shift start (UTC). The ideal rate is estimated from `speed`, so OEE is shown at p90, p95 (headline) and p99. P is count-based; time-based P is the cross-check.

| Machine | Window | Planned h | A | P count (p95) | P time | Q | OEE p90 | OEE p95 | OEE p99 |
|---|---|---|---|---|---|---|---|---|---|
| s_1 | 2020-01-01 to 2021-12-31 | 11,905 | 0.777 | 0.786 | 0.833 | 0.998 | 0.616 | 0.609 | 0.596 |
| s_2 | 2020-06-15 to 2021-12-31 | 4,163 | 0.413 | 0.704 | 0.789 | 0.993 | 0.289 | 0.289 | 0.289 |
| s_3 | 2020-10-07 to 2022-01-01 | 6,759 | 0.492 | 0.777 | 0.908 | 0.997 | 0.381 | 0.381 | 0.358 |
| s_4 | 2019-12-31 to 2022-01-01 | 6,132 | 0.691 | 0.567 | 0.637 | 0.996 | 0.390 | 0.390 | 0.371 |
| s_5 | 2020-01-11 to 2022-01-01 | 8,635 | 0.655 | 0.772 | 0.815 | 0.997 | 0.504 | 0.504 | 0.504 |

Note: s_4's window starts 2019-12-31 because its first interval (2020-01-01 00:05 UTC) falls in the 22:00 UTC shift that began the day before.

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

## Assumptions

- PIADE has no stated ideal rate. Performance rests on an estimate (a percentile of the set `speed` per machine), shown at p90, p95 and p99.
- PIADE shifts are an assumed 3 x 8 h UTC calendar; the data gives no site timezone.
- Brick line planned time is a published input. Brick timestamps are local Europe/Nicosia.
- Brick availability uses the union of in-OEE stop intervals, clipped to the date, so overlapping stops count once. On the real files no stops overlap, so union and plain sum give the same numbers.
- Every metric states its window. Real-data figures are never blended into one headline number.

The full list, with the evidence for each, is in [docs/data-notes.md](docs/data-notes.md).

## Data and credits

All three datasets are licensed CC BY 4.0. Raw files are not in this repository; `make data` downloads them into a gitignored `data/` folder and records a checksum manifest.

| Dataset | Source | Used for |
|---|---|---|
| PIADE: industrial packaging machines (5 machines, 2020 to early 2022) | [Zenodo record 7071747](https://zenodo.org/records/7071747), CC BY 4.0 | Machine state, alarms and counters; OEE per machine |
| Heavy clay brick line: OEE and downtime, before and after a Lean Six Sigma program | [Zenodo record 17855209](https://zenodo.org/records/17855209), CC BY 4.0 | Published per-shift OEE and stop log; validation |
| VisA (Visual Anomaly) | [github.com/amazon-science/spot-diff](https://github.com/amazon-science/spot-diff), CC BY 4.0 | Visual inspection in stage 5; not used yet |

## Real vs synthetic

| Data | Real or synthetic | Stage |
|---|---|---|
| PIADE machine intervals, alarms, counters | Real | 1 |
| Brick line published OEE and stop log | Real | 1 |
| Operator notes (Greek, original text kept) | Real | 1 (loaded; search comes in stage 2) |
| VisA images | Real | 5 |
| Orders, products, BOMs, stock, supplier lead times, changeovers, demo users | Synthetic, generated by a seeded script, own schema, `source` column, badged in the app | 3 to 4 (none exist yet) |

Stage 1 contains no synthetic data.

## What didn't work (and what replaced it)

- **Trusting the download manifest hash.** The manifest records a hash at download time, which says nothing about the file later loaded. The loader now hashes the file it actually reads and keys the load on that, so re-running `make load` replaces the same load instead of duplicating it.
- **Citing (table, row).** Row numbers collided between the before and after brick files. A citation is now (table, file, row).
- **Start-aligned PIADE counters.** Giving each counter delta to the row it starts on put 11 to 31% of output on non-run time and tripped the glitch rule thousands of times. End alignment puts 94 to 98% of counts on run rows.
- **Overlapping PIADE intervals.** On three machine-nights (2020-10-25 and 2021-10-31) intervals overlapped and one hour was counted twice (a shift held 9 h of an 8 h window). The dates match the EU daylight-saving end, but the cause is unexplained. Later intervals are now clipped to the end of the earlier one.
- **Zero-input shifts in the monthly rollup.** Shifts with run time but no counted input dragged count-based performance down. They are now left out of count-based P and Q (A and time-based P keep them) and counted in the notes.
- **The brick availability gap is not closed.** Recomputing availability from the stop log lands within 2 points on 97.7% of after-period shifts but only 38.7% of before-period shifts. The before gap traces to a block of October days where published planned time is far longer than the logged day; the files do not explain why. It is reported as measured, not filtered.

## Run it

Needs Docker, uv, and Node 24 (Node only for local web work).

```
make demo-stage1   # db, api and web up; download data; load; dbt build; validation report
make report        # rewrite the results section above from evals/results/
make lint          # ruff
make test          # offline tests
make test-db       # tests that need Postgres (uses the compose test database)
make down
```

Then open http://localhost:8080 (overview, validation, evidence for a shift). The API is on http://localhost:8000.

More: [docs/data-notes.md](docs/data-notes.md) (data findings and how each number is reproduced), [docs/design.md](docs/design.md) (design for all stages).

Reproduction here uses `PYTHONPATH=src`, which the Makefile exports.
