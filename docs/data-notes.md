# Data notes

Findings from the data that shape how it is loaded and measured. Each note gives the
evidence and the query or model that reproduces it. Figures are from the files listed in
`data/checksums.json`.

## Brick line: one OEE row per date

The first look counted 2 duplicate `shiftDate` values in `OEEdataset.csv`. Both come from
the 3 fully blank rows at the end of the file (lines 63 to 65): their shared empty date
counts as 2 duplicates. Those rows are rejected as `empty_row`.

After that, every date appears once:

| File | Rows accepted | Distinct dates | Dates also in the other file |
|---|---|---|---|
| `OEEdataset.csv` (before) | 62 | 62 | 0 |
| `OEEdataset_afterLSS.csv` (after) | 43 | 43 | 0 |

So there is no second shift on any date to separate, and no `-2` shift suffix is needed.
The loader keeps the one-shift-per-date rule as a contract: if a later row repeats a date
already accepted from the same file, it is rejected as `duplicate_shift` (first row kept)
and lands in `raw.rejected` with its full text. It never fires on the current files; the
test fixture carries a planted repeat to exercise it.

## Brick line: dates with stops but no OEE row

Two after-period dates, 2026-03-25 and 2026-04-01, have stop-log rows but no OEE row.
Each holds one `NO PRODUCTION SCHEDULE` stop of type `Planned - Not included in OEE`
(480 and 330 minutes). They are days the line did not run. `mart.brick_shift_oee` keeps
them as `no_published` with zero in-OEE stop time instead of dropping them.

## Brick line: recomputed availability against published

`mart.brick_shift_oee` recomputes availability as

    1 - (union of in-OEE stop intervals, clipped to the local date) / published planned time

where in-OEE means every stop type except `Planned - Not included in OEE`. Planned time
is the only published input. The published availability equals
`(good + slow production seconds) / planned seconds` on all 105 rows (within 0.0001), so
the published figure comes from production-time totals, not from the stop log.

Results on the full files (all matched shifts, nothing excluded):

| Period | Matched shifts | Mean abs gap | Median abs gap | Max abs gap | Within 2 pts | Within 5 pts | Mean signed gap |
|---|---|---|---|---|---|---|---|
| Before | 62 | 13.36 pts | 3.44 pts | 52.09 pts | 38.7% | 61.3% | +6.59 pts |
| After | 43 | 1.15 pts | 0.58 pts | 24.50 pts | 97.7% | 97.7% | -0.01 pts |

Gap = recomputed minus published. No published date lacks stops, and the 2 stop-only
dates above are `no_published`.

### Overlaps, clipping and the shift window

- No two in-OEE stops overlap on any date in either period, so the union and the plain sum
  of stop time are identical and the mean gap is the same both ways. Overlap handling is
  tested on fixtures, but it does not move the real-data result.
- No stop crosses midnight, so clipping to the date removes nothing.
- One in-OEE stop (2026-03-31, 480 s) falls outside the nominal 07:15 to 16:00 window.
  It is counted, not excluded.
- Stop seconds come from start and end timestamps, which have minute resolution. The
  `StopDuration` column is 3.4% higher in total before (542,166 s against 523,800 s) and
  1.9% higher after. Spread over the shifts, that is about 1 point of planned time or less
  per shift, too small to explain the before-period gap.

### What drives the before-period gap

**Long planned days in October.** 13 before-period dates, 2025-10-14 to 2025-10-31, carry
planned time of 38,269 to 59,400 s (10.6 to 16.5 hours). Every other date in both periods
is at most 33,857 s. On those 13 dates the stop log still runs only from about 07:15 to
15:30, and logged stops are a small share of the day, so the recomputed availability is
high. The published run time on those days leaves 6.7 to 8.1 hours (2.9 on 2025-10-31) of planned time with
neither production nor a stop in the file's own stop totals, so the published availability
is low.

| Before-period shifts | n | Mean abs gap | Median abs gap |
|---|---|---|---|
| Planned time over 9 h (Oct 14 to 31; threshold chosen after looking at the gaps) | 13 | 46.54 pts | 46.74 pts |
| Planned time 9 h or less | 49 | 4.55 pts | 2.07 pts |

The 9 h cut-off was chosen after looking at the gaps, to isolate the October block, so this
split explains the headline and is not a filtered replacement for it. The 5 worst shifts, all
in that block:

| Shift | Gap | In-OEE stop union | Planned - published run time | Planned (published) |
|---|---|---|---|---|
| 2025-10-16 | +52.1 pts | 6,300 s | 35,869 s | 56,760 s |
| 2025-10-17 | +52.0 pts | 4,440 s | 32,042 s | 53,100 s |
| 2025-10-15 | +50.6 pts | 18,600 s | 46,846 s | 55,800 s |
| 2025-10-14 | +49.4 pts | 5,460 s | 34,813 s | 59,400 s |
| 2025-10-24 | +48.8 pts | 8,460 s | 35,292 s | 55,020 s |

The published file agrees with the stop log here. Its own stop columns
(`plannedStopsTimeSec + unplannedStopsTimeSec`) match the logged stop time, including
not-included stops, within 0.5 points of planned time on average across these 13 days.
The mismatch is inside the published file: on those days planned time is much larger than
production time plus the file's own stop totals. The data does not say why. A second
shift that logged no stops, or planned time recorded for a longer window than the line ran,
would both fit; neither can be confirmed from the files.

**Normal-length before days.** On the other 49 before dates the gap is smaller and runs the
other way (mean signed -4.0 pts): logged stop time exceeds planned time minus published
run time, so the recomputed availability is lower. The worst cases (2025-12-03 at -28.6,
2025-11-26 at -27.1) have published run time plus published stop totals above planned
time, so the two published measures disagree there too. The dataset's published formulas
use the bottleneck for availability and performance, while the stop log covers every
location on the line; that may explain part of this, but the stop log does not tag the
bottleneck, so it cannot be tested.

**After period.** Planned time minus published run time matches logged in-OEE stop time
closely (mean abs gap 1.15 pts). The one large gap, 2026-04-03 (-24.5 pts), is a short day
(9,143 s planned) whose logged stops (5,640 s) exceed planned time minus published run
time (3,400 s).

The method is fixed as above and is not adjusted per period or per day. The headline is
the full-period figure; the split by planned-day length is the explanation, not a
replacement.

Reproduce: `make dbt`, then query `mart.brick_shift_oee` joined to
`core.brick_shift_published` on `shift_id`.

## PIADE: counter alignment and the unit of `speed`

`pi` and `po` are running counters, so a per-interval count is a difference of consecutive
readings. The file does not say which interval that difference belongs to.
`scripts/probe_piade_counts.py` compares two alignments on `raw_data.csv`, with the same
reset and glitch rule as the mart (negative delta = reset; delta above
3 × max production speed × row hours = glitch; both dropped):

- start: `x[i+1] - x[i]` belongs to row i
- end: `x[i] - x[i-1]` belongs to row i

Share of valid `po` counts that land on run rows (production, performance_loss):

| Machine | Start alignment | End alignment | Glitches, start | Glitches, end |
|---|---|---|---|---|
| s_1 | 68.7% | 96.5% | 19,139 | 233 |
| s_2 | 74.2% | 93.9% | 8,241 | 4 |
| s_3 | 78.7% | 97.4% | 5,146 | 77 |
| s_4 | 89.4% | 95.0% | 10,550 | 14 |
| s_5 | 74.0% | 98.1% | 13,049 | 114 |

`pi` gives the same picture (end: 94.1% to 98.1%). End alignment puts at least 80% of counts
in run states on every machine, so it is used and count-based performance stays the headline.
Start alignment also trips the glitch rule thousands of times, because it hands a run's
counts to the short stop row that follows it. Under end alignment, under 0.4% of counts
span a gap of more than 60 s between rows; they are attributed to the later row like any
other delta.

**Speed unit.** Valid `po` counts on run rows per run hour, divided by the
elapsed-weighted mean `speed` on run rows:

| Machine | `po` per run hour | Weighted mean speed | Ratio |
|---|---|---|---|
| s_1 | 3,564 | 4,011 | 0.89 |
| s_2 | 4,530 | 6,180 | 0.73 |
| s_3 | 3,485 | 3,986 | 0.87 |
| s_4 | 3,463 | 5,551 | 0.62 |
| s_5 | 4,986 | 5,982 | 0.83 |

Ratios of 0.6 to 0.9 fit packages per hour (packages per minute would give ratios near 60).
`speed` is read as packages per hour.

`speed` takes a few discrete values per machine (s_1 runs at 4,500 on 35,113 of its
production rows), so it reads as a set speed rather than a measured one, and the
p90/p95/p99 ideal rates often coincide. s_1 has 4,422 production rows with speed 0, s_4 667
and s_5 215; they are left out of the percentiles.

## PIADE: OEE per machine

Built by `mart.piade_interval_counts`, `mart.piade_shift_oee` and `mart.piade_machine_oee`;
the table below is printed by `scripts/piade_oee_summary.py`. Window: each machine's full
coverage, first to last interval (s_1 2020-01-01 to 2021-12-31, s_2 2020-06-15 to
2021-12-31, s_3 2020-10-07 to 2022-01-02, s_4 2020-01-01 to 2022-01-02, s_5 2020-01-12 to
2022-01-02, UTC). Time-weighted: seconds and counts are summed, then the ratios computed.

| Machine | Planned h | A | P count (p95) | P count (p90) | P count (p99) | P time | Q | OEE (p95) | OEE (p90) | OEE (p99) |
|---|---|---|---|---|---|---|---|---|---|---|
| s_1 | 11,905 | 0.777 | 0.786 | 0.795 | 0.769 | 0.833 | 0.998 | 0.609 | 0.616 | 0.596 |
| s_2 | 4,163 | 0.413 | 0.704 | 0.704 | 0.704 | 0.789 | 0.993 | 0.289 | 0.289 | 0.289 |
| s_3 | 6,759 | 0.492 | 0.777 | 0.777 | 0.729 | 0.908 | 0.997 | 0.381 | 0.381 | 0.358 |
| s_4 | 6,132 | 0.691 | 0.567 | 0.567 | 0.539 | 0.637 | 0.996 | 0.390 | 0.390 | 0.371 |
| s_5 | 8,635 | 0.655 | 0.772 | 0.772 | 0.772 | 0.815 | 0.997 | 0.504 | 0.504 | 0.504 |

Ideal rates (packages per hour, p90 / p95 / p99): s_1 4,500 / 4,550 / 4,650; s_2 6,500 for
all three; s_3 4,500 / 4,500 / 4,800; s_4 6,176 / 6,176 / 6,500; s_5 6,500 for all three.

Counter handling and caps over the same window:

| Machine | Shifts | pi resets | pi glitches (on run rows) | Glitch shifts excluded (run h) | Ran, zero input: shifts excluded (run h) | Run time excluded | P capped (p95) | Q capped | Overlap clipped |
|---|---|---|---|---|---|---|---|---|---|
| s_1 | 1,821 | 1 | 234 (62) | 62 (339.2) | 32 (1.8) | 3.7% | 2 | 262 | 18 rows, 2.0 h |
| s_2 | 1,167 | 3 | 4 (1) | 1 (0.6) | 86 (6.0) | 0.39% | 0 | 3 | none |
| s_3 | 1,059 | 1 | 77 (21) | 21 (83.0) | 14 (0.4) | 2.5% | 6 | 9 | 12 rows, 1.0 h |
| s_4 | 1,079 | 79 | 15 (7) | 8 (40.1) | 46 (31.8) | 1.7% | 0 | 212 | none |
| s_5 | 1,405 | 1 | 116 (47) | 48 (240.7) | 86 (21.8) | 4.6% | 2 | 26 | none |

Count-based performance and quality leave out every shift with incomplete counts: a glitch
on a run row, or run time with no input counted at all (264 shifts, 61.9 run hours over the
five machines; e.g. `piade:s_4:2021-05-02T06`, 6.5 h of performance_loss with the counter
standing still). Before this rule those shifts entered the monthly rollup with zero input
and pulled count-based performance down (s_4 0.563 to 0.567, s_5 0.769 to 0.772).
Availability and time-based performance still use all run time.

Points to read with it:

- **Count-based performance sits below time-based on every machine**, and is rarely capped
  (at most 6 shifts per machine at p95). Nothing suggests counts running above the ideal
  rate; the main caveat is that the ideal rate is a set speed, not a demonstrated one.
- **Availability counts idle time as planned.** Idle is 45% of planned time on s_2 and 44%
  on s_3, which is what drives their low availability. If idle means "no order", those two
  machines' availability is understated; the data does not say.
- **Quality is close to 1** (0.993 to 0.998). Within a shift, output can exceed input when
  packages counted in late in one shift come out in the next; 512 of 6,531 shifts have
  output above input, by a median of 0.07%. Shift quality is capped at 1 and the capped
  shifts are counted. Over a machine's full window output stays below input.
- **Glitches mostly sit on stop rows.** Of 446 `pi` glitches, 138 fall on run rows; those
  shifts get null quality and null count-based performance (`quality_reason = 'pi_glitch'`),
  and their run time is left out of the count-based ratios. s_2's 3.4e8 jump is one of them.
- **s_4 has 79 `pi` resets**, 36 shifts with a reset on a run row. A reset drops that row's
  count; on s_4, 78 of the 79 `pi` resets fall on the same row as a `po` reset, so input
  and output lose the same row. Quality stays computed for those shifts.
- **Shift calendar is assumed** (3 × 8 h UTC from 06:00). s_4's first interval starts
  2020-01-01 00:05 UTC, inside the shift that began 2019-12-31 22:00, so its monthly rollup
  has a December 2019 row.

- **Overlapping intervals are clipped.** An interval that starts before an earlier interval
  of the same machine has ended has its start moved to that end, so no second counts twice
  (`clipped_s` records the cut; the counter delta stays on the row). Before clipping, three
  shifts held 32,400 s in an 8 h (28,800 s) shift. All clipped time is exactly one hour per
  machine-night, on 2020-10-25 (s_1) and 2021-10-31 (s_1, s_3): the European daylight-saving
  end dates. The dates coincide with the EU daylight-saving end dates, but the in-day timing
  (21:00 to 23:00 UTC) does not match a plain transition, so the cause is unexplained. The
  overlapping time is counted once.

### Assumptions behind the PIADE figures

- Shift calendar is 3 × 8 h in UTC from 06:00. PIADE gives no site timezone, so the design's
  "local" calendar cannot be known; the DST-date overlaps above are unexplained and do not
  identify a timezone.
- Months are assigned by shift start (UTC), so a shift starting 22:00 on the last day of a
  month belongs to that month.
- Counters are end-aligned. Counts that land on non-run rows (2 to 6% per machine) are left
  out of input and output, which lowers count-based performance by about that much. A delta
  spanning a gap between rows is credited to the next row (under 0.4% of counts).
- A counter reset on a run row drops that row's count but keeps its run time, so
  count-based performance on that shift is slightly low.
- Ideal-rate percentiles are row-weighted (each production row counts once, whatever its
  length), over production rows with speed above 0.
- Idle counts as planned time; scheduled_downtime does not.

Reproduce: `make dbt`, then `PYTHONPATH=src uv run python scripts/probe_piade_counts.py` and
`PYTHONPATH=src uv run python scripts/piade_oee_summary.py`.
