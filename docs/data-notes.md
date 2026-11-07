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
| Planned time over 9 h (Oct 14 to 31) | 13 | 46.54 pts | 46.74 pts |
| Planned time 9 h or less | 49 | 4.55 pts | 2.07 pts |

The 5 worst shifts, all in that block:

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
time, so the two published measures disagree there too. The dataset notes that published
availability is taken at the bottleneck, while the stop log covers every location on the
line; that may explain part of this, but the stop log does not tag the bottleneck, so it
cannot be tested.

**After period.** Planned time minus published run time matches logged in-OEE stop time
closely (mean abs gap 1.15 pts). The one large gap, 2026-04-03 (-24.5 pts), is a short day
(9,143 s planned) whose logged stops (5,640 s) exceed planned time minus published run
time (3,400 s).

The method is fixed as above and is not adjusted per period or per day. The headline is
the full-period figure; the split by planned-day length is the explanation, not a
replacement.

Reproduce: `make dbt`, then query `mart.brick_shift_oee` joined to
`core.brick_shift_published` on `shift_id`.
