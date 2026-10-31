# VintageBench tasks: 60-task set

Generated from data/vintages/; do not edit by hand. Gold answers are computed
programmatically from two vintages (SPEC §3). Regenerate with:

```
python -m vintagebench.tasks --extend-from tasks/pilot.jsonl --n 60 --out tasks/pilot60.jsonl --readme-out tasks/README60.md --seed 0
```

## Selection

`tasks/pilot60.jsonl`: 60 tasks = the 20 tasks of `tasks/pilot.jsonl`, kept
unchanged, plus 40 new ones from `extend_pilot(existing, candidates, n_total=60, seed=0)`: 30 flips, 30 controls (6 UNRATE).

The new tasks obey the same rules as the pilot (see tasks/README.md: date rule,
materiality margins in both vintages, COVID exclusion and non-trivial caps for
controls, no UNRATE flips, targets 2016-01 to 2025-12, one task per (series,
target period), no duplicate ids) and the same stratified, spread-maximizing
picker, whose usage counters start from the existing tasks. Quotas are those
of a balanced 60-task set, minus what the existing tasks already fill.

Two extra rules apply to the new tasks only (the base tasks are unchanged):

- Revision gap: revision_date - as_of_date >= 365 days. This
  excludes the date rule's "else the latest vintage" fallback, whose revised
  answer could change when newer vintages are fetched.
- Independence: a task's computation window is its target period plus the
  template's lookback (2 months for month-over-month, 2 quarters for GDP, 4
  months for the payroll 3-month average, 13 months for weakest-of-12 and PCE
  YoY). Two tasks in the same series overlap if their windows intersect. The
  picker's first criterion is the number of already chosen tasks a candidate
  overlaps, so an overlapping task is added only when no non-overlapping
  candidate is left in the stratum (or its fallback) being filled.

Row order: the 20 tasks of `tasks/pilot.jsonl` first, in their original
order, then the 40 new tasks sorted by id. The first 20 rows
of `tasks/pilot60.jsonl` are therefore exactly the base set (e.g. `--limit 20`).

## Templates

Counts are candidates after the materiality filter (as in tasks/README.md).

| template | definition | materiality margin (both vintages) | control cap (margins) | candidates | flips | trivial controls excluded |
|---|---|---|---|---|---|---|
| gdpc1-growth-above-2 (GDPC1) | yes iff 100 * ((level(q) / level(q-1 quarter))^4 - 1) > 2.0, unrounded; a tie is no. | \|annualized QoQ growth - 2.0\| >= 0.2 (percentage points; the annualized equivalent of the 0.05 non-annualized GDP margin) | 10 | 33 | 3 | 11 |
| gdpc1-qoq-shrink (GDPC1) | yes iff level(q) < level(q-1 quarter); a tie is no. | \|QoQ % change, non-annualized\| >= 0.05 (about 0.2pp annualized; stricter than half the 0.1 publication unit) | 5 | 40 | 0 | 35 |
| indpro-mom-fall (INDPRO) | yes iff level(t) < level(t-1 month); a tie is no. | \|100 * (level(t) / level(t-1 month) - 1)\| >= 0.05 | 10 | 106 | 11 | 37 |
| payems-avg3m-above-100k (PAYEMS) | PAYEMS in thousands; yes iff (level(t) - level(t-3 months)) / 3 > 100; a tie is no. | \|3-month average - 100\| >= 1 (thousand) | 40 | 120 | 9 | 99 |
| payems-avg3m-above-150k (PAYEMS) | PAYEMS in thousands; yes iff (level(t) - level(t-3 months)) / 3 > 150; a tie is no. | \|3-month average - 150\| >= 1 (thousand) | 40 | 115 | 14 | 72 |
| payems-weakest-12m (PAYEMS) | yes iff change(t) is strictly lower than each of change(t-1) .. change(t-11), where change(m) = level(m) - level(m-1); any tie is no. | \|change(t) - min(change(t-11) .. change(t-1))\| >= 1 (thousand) | 40 | 120 | 13 | 92 |
| pcepi-yoy-above-2.5 (PCEPI) | yes iff 100 * (level(t) / level(t-12 months) - 1) > 2.5, unrounded. | \|12-month % change - 2.5\| >= 0.05 (percentage points) | 10 | 111 | 2 | 81 |
| unrate-mom-rise (UNRATE) | yes iff round(rate(t), 1) > round(rate(t-1 month), 1); equal is no. | none (compared at the published 0.1 precision) | none | 118 | 12 | 0 |

## Eligible pool

Candidates the selection may draw from, after every rule (COVID exclusion and
non-trivial cap for controls; UNRATE flips are never drawn). One task per
(series, target period) is enforced at pick time and is not netted here.

Columns "with gap" also apply the 365-day revision gap required of new tasks.

| template | eligible flips | eligible controls | flips with gap | controls with gap | flips in this set | controls in this set |
|---|---|---|---|---|---|---|
| gdpc1-growth-above-2 | 3 | 19 | 3 | 17 | 3 | 4 |
| gdpc1-qoq-shrink | 0 | 5 | 0 | 4 | 0 | 3 |
| indpro-mom-fall | 11 | 58 | 10 | 56 | 10 | 7 |
| payems-avg3m-above-100k | 9 | 12 | 9 | 11 | 6 | 1 |
| payems-avg3m-above-150k | 14 | 29 | 14 | 29 | 5 | 4 |
| payems-weakest-12m | 13 | 15 | 13 | 15 | 4 | 2 |
| pcepi-yoy-above-2.5 | 2 | 28 | 2 | 24 | 2 | 3 |
| unrate-mom-rise | 0 | 101 | 0 | 99 | 0 | 6 |

## Answer balance (60-task set)

| | as-of Yes | as-of No |
|---|---|---|
| flips | 15 | 15 |
| controls | 15 | 15 |

- Share of Yes: as-of 30/60 (50%); revised 30/60 (50%).
- Majority-class baseline (always answer the more common gold): as-of 30/60 (50%), revised 30/60 (50%).

Strata (actual / target):

| stratum | tasks | target |
|---|---|---|
| flip/as-of Yes | 15 | 15 |
| flip/as-of No | 15 | 15 |
| UNRATE control/as-of Yes | 3 | 3 |
| UNRATE control/as-of No | 3 | 3 |
| control/as-of Yes | 12 | 12 |
| control/as-of No | 12 | 12 |

## Spread

| series | flips | controls | total |
|---|---|---|---|
| GDPC1 | 3 | 7 | 10 |
| INDPRO | 10 | 7 | 17 |
| PAYEMS | 15 | 7 | 22 |
| PCEPI | 2 | 3 | 5 |
| UNRATE | 0 | 6 | 6 |

| year | tasks |
|---|---|
| 2016 | 6 |
| 2017 | 7 |
| 2018 | 5 |
| 2019 | 6 |
| 2020 | 4 |
| 2021 | 5 |
| 2022 | 5 |
| 2023 | 5 |
| 2024 | 9 |
| 2025 | 8 |

The year and series spread is limited by the eligible flip pool, which is
exhausted for gdpc1-growth-above-2, indpro-mom-fall, pcepi-yoy-above-2.5, so most new flips are PAYEMS (12) and INDPRO (8) (of 20 new flips) and 11 of them target 2024–2025.

## Clusters

A cluster is a connected component of the overlap graph within one series
(`task_clusters`); a task overlapping no other is its own cluster. Labels are
`<SERIES>:<first month>..<last month>` of the union of the members' windows.
Use clusters, not tasks, as the independent unit when aggregating results.

- Distinct clusters: 18 among the 30 flips, 30 among the 30 controls (44 in all).
- Multi-task clusters (9):

| cluster | tasks | members (flips marked *) |
|---|---|---|
| GDPC1:2015-10..2016-04 | 2 | gdpc1-growth-above-2-2016-01, gdpc1-growth-above-2-2016-04* |
| INDPRO:2017-06..2017-08 | 2 | indpro-mom-fall-2017-07*, indpro-mom-fall-2017-08 |
| INDPRO:2019-01..2019-03 | 2 | indpro-mom-fall-2019-02*, indpro-mom-fall-2019-03* |
| INDPRO:2025-06..2025-08 | 2 | indpro-mom-fall-2025-07*, indpro-mom-fall-2025-08* |
| PAYEMS:2018-12..2019-04 | 2 | payems-avg3m-above-100k-2019-03, payems-avg3m-above-150k-2019-04* |
| PAYEMS:2020-10..2023-03 | 4 | payems-avg3m-above-100k-2021-01*, payems-weakest-12m-2021-12*, payems-weakest-12m-2022-09*, payems-weakest-12m-2023-03* |
| PAYEMS:2023-04..2024-08 | 3 | payems-avg3m-above-100k-2024-08*, payems-avg3m-above-150k-2024-06*, payems-weakest-12m-2024-04* |
| PAYEMS:2024-09..2025-06 | 5 | payems-avg3m-above-100k-2025-04*, payems-avg3m-above-100k-2025-05*, payems-avg3m-above-100k-2025-06*, payems-avg3m-above-150k-2024-12*, payems-avg3m-above-150k-2025-01* |
| PCEPI:2023-01..2024-11 | 3 | pcepi-yoy-above-2.5-2024-01*, pcepi-yoy-above-2.5-2024-08, pcepi-yoy-above-2.5-2024-11* |

## Controls easy on one side

The non-trivial cap excludes a control only if min(as-of, revised) distance
exceeds the cap, so a kept control can still be far from the threshold as of
its first release. Controls whose as-of distance is more than 2x
the cap or more than 20 margins (7):

| id | as-of distance (margins) | revised distance (margins) | cap |
|---|---|---|---|
| payems-avg3m-above-100k-2019-03 | 80.3 | 39.0 | 40 |
| indpro-mom-fall-2022-04 | 21.5 | 6.2 | 10 |
| payems-avg3m-above-150k-2016-11 | 26.0 | 29.0 | 40 |
| payems-avg3m-above-150k-2017-05 | 29.3 | 15.7 | 40 |
| payems-avg3m-above-150k-2019-12 | 34.3 | 46.7 | 40 |
| payems-weakest-12m-2016-01 | 67.0 | 40.0 | 40 |
| payems-weakest-12m-2018-11 | 36.0 | 88.0 | 40 |

## Tasks (60)

| id | question | as-of answer | revised answer | flips | set | cluster |
|---|---|---|---|---|---|---|
| gdpc1-growth-above-2-2016-01 | Did real GDP grow faster than 2% (annualized) in Q1 2016, i.e. was the annualized growth rate of real GDP (GDPC1) from Q4 2015 to Q1 2016, 100 * ((level(Q1 2016) / level(Q4 2015))^4 - 1), above 2.0%? | No | No | no | pilot20 | GDPC1:2015-10..2016-04 |
| gdpc1-growth-above-2-2016-04 | Did real GDP grow faster than 2% (annualized) in Q2 2016, i.e. was the annualized growth rate of real GDP (GDPC1) from Q1 2016 to Q2 2016, 100 * ((level(Q2 2016) / level(Q1 2016))^4 - 1), above 2.0%? | No | Yes | yes | pilot20 | GDPC1:2015-10..2016-04 |
| gdpc1-growth-above-2-2018-10 | Did real GDP grow faster than 2% (annualized) in Q4 2018, i.e. was the annualized growth rate of real GDP (GDPC1) from Q3 2018 to Q4 2018, 100 * ((level(Q4 2018) / level(Q3 2018))^4 - 1), above 2.0%? | Yes | No | yes | pilot20 | GDPC1:2018-07..2018-10 |
| gdpc1-growth-above-2-2023-01 | Did real GDP grow faster than 2% (annualized) in Q1 2023, i.e. was the annualized growth rate of real GDP (GDPC1) from Q4 2022 to Q1 2023, 100 * ((level(Q1 2023) / level(Q4 2022))^4 - 1), above 2.0%? | No | Yes | yes | pilot20 | GDPC1:2022-10..2023-01 |
| gdpc1-qoq-shrink-2025-01 | Did real GDP shrink in Q1 2025, i.e. was real GDP (GDPC1) in Q1 2025 lower than in Q4 2024? | Yes | Yes | no | pilot20 | GDPC1:2024-10..2025-01 |
| indpro-mom-fall-2016-09 | Did industrial production (INDPRO) fall in September 2016 versus the prior month, i.e. was its level in September 2016 lower than in August 2016? | No | Yes | yes | pilot20 | INDPRO:2016-08..2016-09 |
| indpro-mom-fall-2017-08 | Did industrial production (INDPRO) fall in August 2017 versus the prior month, i.e. was its level in August 2017 lower than in July 2017? | Yes | Yes | no | pilot20 | INDPRO:2017-06..2017-08 |
| indpro-mom-fall-2020-02 | Did industrial production (INDPRO) fall in February 2020 versus the prior month, i.e. was its level in February 2020 lower than in January 2020? | No | No | no | pilot20 | INDPRO:2020-01..2020-02 |
| indpro-mom-fall-2022-08 | Did industrial production (INDPRO) fall in August 2022 versus the prior month, i.e. was its level in August 2022 lower than in July 2022? | Yes | No | yes | pilot20 | INDPRO:2022-07..2022-08 |
| payems-avg3m-above-100k-2019-03 | Was average monthly payroll growth over the 3 months ending March 2019 above 100k, i.e. is (level(March 2019) - level(December 2018)) / 3 above 100, with total nonfarm payrolls (PAYEMS) in thousands of jobs? | Yes | Yes | no | pilot20 | PAYEMS:2018-12..2019-04 |
| payems-avg3m-above-100k-2025-06 | Was average monthly payroll growth over the 3 months ending June 2025 above 100k, i.e. is (level(June 2025) - level(March 2025)) / 3 above 100, with total nonfarm payrolls (PAYEMS) in thousands of jobs? | Yes | No | yes | pilot20 | PAYEMS:2024-09..2025-06 |
| payems-avg3m-above-150k-2019-08 | Was average monthly payroll growth over the 3 months ending August 2019 above 150k, i.e. is (level(August 2019) - level(May 2019)) / 3 above 150, with total nonfarm payrolls (PAYEMS) in thousands of jobs? | Yes | Yes | no | pilot20 | PAYEMS:2019-05..2019-08 |
| payems-weakest-12m-2021-12 | Was December 2021 the weakest of the 12 months ending in December 2021 for payroll growth, i.e. is change(December 2021) lower than each of change(January 2021) through change(November 2021), where change(month) = level(month) - level(previous month), with total nonfarm payrolls (PAYEMS) in thousands of jobs? | Yes | No | yes | pilot20 | PAYEMS:2020-10..2023-03 |
| payems-weakest-12m-2022-09 | Was September 2022 the weakest of the 12 months ending in September 2022 for payroll growth, i.e. is change(September 2022) lower than each of change(October 2021) through change(August 2022), where change(month) = level(month) - level(previous month), with total nonfarm payrolls (PAYEMS) in thousands of jobs? | Yes | No | yes | pilot20 | PAYEMS:2020-10..2023-03 |
| pcepi-yoy-above-2.5-2018-10 | Is PCE inflation (year over year) above 2.5% for October 2018, i.e. is the 12-month percent change in the PCE price index (PCEPI) from October 2017 to October 2018, 100 * (level(October 2018) / level(October 2017) - 1), above 2.5? | No | No | no | pilot20 | PCEPI:2017-10..2018-10 |
| pcepi-yoy-above-2.5-2024-01 | Is PCE inflation (year over year) above 2.5% for January 2024, i.e. is the 12-month percent change in the PCE price index (PCEPI) from January 2023 to January 2024, 100 * (level(January 2024) / level(January 2023) - 1), above 2.5? | No | Yes | yes | pilot20 | PCEPI:2023-01..2024-11 |
| pcepi-yoy-above-2.5-2024-08 | Is PCE inflation (year over year) above 2.5% for August 2024, i.e. is the 12-month percent change in the PCE price index (PCEPI) from August 2023 to August 2024, 100 * (level(August 2024) / level(August 2023) - 1), above 2.5? | No | No | no | pilot20 | PCEPI:2023-01..2024-11 |
| pcepi-yoy-above-2.5-2024-11 | Is PCE inflation (year over year) above 2.5% for November 2024, i.e. is the 12-month percent change in the PCE price index (PCEPI) from November 2023 to November 2024, 100 * (level(November 2024) / level(November 2023) - 1), above 2.5? | No | Yes | yes | pilot20 | PCEPI:2023-01..2024-11 |
| unrate-mom-rise-2018-06 | Did the unemployment rate (UNRATE) rise in June 2018 versus the prior month, i.e. was it higher than in May 2018 (as published, to one decimal place)? | Yes | Yes | no | pilot20 | UNRATE:2018-05..2018-06 |
| unrate-mom-rise-2021-03 | Did the unemployment rate (UNRATE) rise in March 2021 versus the prior month, i.e. was it higher than in February 2021 (as published, to one decimal place)? | No | No | no | pilot20 | UNRATE:2021-02..2021-03 |
| gdpc1-growth-above-2-2017-10 | Did real GDP grow faster than 2% (annualized) in Q4 2017, i.e. was the annualized growth rate of real GDP (GDPC1) from Q3 2017 to Q4 2017, 100 * ((level(Q4 2017) / level(Q3 2017))^4 - 1), above 2.0%? | Yes | Yes | no | new | GDPC1:2017-07..2017-10 |
| gdpc1-growth-above-2-2018-04 | Did real GDP grow faster than 2% (annualized) in Q2 2018, i.e. was the annualized growth rate of real GDP (GDPC1) from Q1 2018 to Q2 2018, 100 * ((level(Q2 2018) / level(Q1 2018))^4 - 1), above 2.0%? | Yes | Yes | no | new | GDPC1:2018-01..2018-04 |
| gdpc1-growth-above-2-2024-01 | Did real GDP grow faster than 2% (annualized) in Q1 2024, i.e. was the annualized growth rate of real GDP (GDPC1) from Q4 2023 to Q1 2024, 100 * ((level(Q1 2024) / level(Q4 2023))^4 - 1), above 2.0%? | No | No | no | new | GDPC1:2023-10..2024-01 |
| gdpc1-qoq-shrink-2017-01 | Did real GDP shrink in Q1 2017, i.e. was real GDP (GDPC1) in Q1 2017 lower than in Q4 2016? | No | No | no | new | GDPC1:2016-10..2017-01 |
| gdpc1-qoq-shrink-2022-04 | Did real GDP shrink in Q2 2022, i.e. was real GDP (GDPC1) in Q2 2022 lower than in Q1 2022? | Yes | Yes | no | new | GDPC1:2022-01..2022-04 |
| indpro-mom-fall-2017-07 | Did industrial production (INDPRO) fall in July 2017 versus the prior month, i.e. was its level in July 2017 lower than in June 2017? | No | Yes | yes | new | INDPRO:2017-06..2017-08 |
| indpro-mom-fall-2019-02 | Did industrial production (INDPRO) fall in February 2019 versus the prior month, i.e. was its level in February 2019 lower than in January 2019? | No | Yes | yes | new | INDPRO:2019-01..2019-03 |
| indpro-mom-fall-2019-03 | Did industrial production (INDPRO) fall in March 2019 versus the prior month, i.e. was its level in March 2019 lower than in February 2019? | Yes | No | yes | new | INDPRO:2019-01..2019-03 |
| indpro-mom-fall-2020-09 | Did industrial production (INDPRO) fall in September 2020 versus the prior month, i.e. was its level in September 2020 lower than in August 2020? | Yes | Yes | no | new | INDPRO:2020-08..2020-09 |
| indpro-mom-fall-2020-11 | Did industrial production (INDPRO) fall in November 2020 versus the prior month, i.e. was its level in November 2020 lower than in October 2020? | No | No | no | new | INDPRO:2020-10..2020-11 |
| indpro-mom-fall-2021-12 | Did industrial production (INDPRO) fall in December 2021 versus the prior month, i.e. was its level in December 2021 lower than in November 2021? | Yes | Yes | no | new | INDPRO:2021-11..2021-12 |
| indpro-mom-fall-2022-04 | Did industrial production (INDPRO) fall in April 2022 versus the prior month, i.e. was its level in April 2022 lower than in March 2022? | No | No | no | new | INDPRO:2022-03..2022-04 |
| indpro-mom-fall-2022-11 | Did industrial production (INDPRO) fall in November 2022 versus the prior month, i.e. was its level in November 2022 lower than in October 2022? | Yes | Yes | no | new | INDPRO:2022-10..2022-11 |
| indpro-mom-fall-2023-12 | Did industrial production (INDPRO) fall in December 2023 versus the prior month, i.e. was its level in December 2023 lower than in November 2023? | No | Yes | yes | new | INDPRO:2023-11..2023-12 |
| indpro-mom-fall-2024-03 | Did industrial production (INDPRO) fall in March 2024 versus the prior month, i.e. was its level in March 2024 lower than in February 2024? | No | Yes | yes | new | INDPRO:2024-02..2024-03 |
| indpro-mom-fall-2025-01 | Did industrial production (INDPRO) fall in January 2025 versus the prior month, i.e. was its level in January 2025 lower than in December 2024? | No | Yes | yes | new | INDPRO:2024-12..2025-01 |
| indpro-mom-fall-2025-07 | Did industrial production (INDPRO) fall in July 2025 versus the prior month, i.e. was its level in July 2025 lower than in June 2025? | Yes | No | yes | new | INDPRO:2025-06..2025-08 |
| indpro-mom-fall-2025-08 | Did industrial production (INDPRO) fall in August 2025 versus the prior month, i.e. was its level in August 2025 lower than in July 2025? | No | Yes | yes | new | INDPRO:2025-06..2025-08 |
| payems-avg3m-above-100k-2017-09 | Was average monthly payroll growth over the 3 months ending September 2017 above 100k, i.e. is (level(September 2017) - level(June 2017)) / 3 above 100, with total nonfarm payrolls (PAYEMS) in thousands of jobs? | No | Yes | yes | new | PAYEMS:2017-06..2017-09 |
| payems-avg3m-above-100k-2021-01 | Was average monthly payroll growth over the 3 months ending January 2021 above 100k, i.e. is (level(January 2021) - level(October 2020)) / 3 above 100, with total nonfarm payrolls (PAYEMS) in thousands of jobs? | No | Yes | yes | new | PAYEMS:2020-10..2023-03 |
| payems-avg3m-above-100k-2024-08 | Was average monthly payroll growth over the 3 months ending August 2024 above 100k, i.e. is (level(August 2024) - level(May 2024)) / 3 above 100, with total nonfarm payrolls (PAYEMS) in thousands of jobs? | Yes | No | yes | new | PAYEMS:2023-04..2024-08 |
| payems-avg3m-above-100k-2025-04 | Was average monthly payroll growth over the 3 months ending April 2025 above 100k, i.e. is (level(April 2025) - level(January 2025)) / 3 above 100, with total nonfarm payrolls (PAYEMS) in thousands of jobs? | Yes | No | yes | new | PAYEMS:2024-09..2025-06 |
| payems-avg3m-above-100k-2025-05 | Was average monthly payroll growth over the 3 months ending May 2025 above 100k, i.e. is (level(May 2025) - level(February 2025)) / 3 above 100, with total nonfarm payrolls (PAYEMS) in thousands of jobs? | Yes | No | yes | new | PAYEMS:2024-09..2025-06 |
| payems-avg3m-above-150k-2016-06 | Was average monthly payroll growth over the 3 months ending June 2016 above 150k, i.e. is (level(June 2016) - level(March 2016)) / 3 above 150, with total nonfarm payrolls (PAYEMS) in thousands of jobs? | No | Yes | yes | new | PAYEMS:2016-03..2016-06 |
| payems-avg3m-above-150k-2016-11 | Was average monthly payroll growth over the 3 months ending November 2016 above 150k, i.e. is (level(November 2016) - level(August 2016)) / 3 above 150, with total nonfarm payrolls (PAYEMS) in thousands of jobs? | Yes | Yes | no | new | PAYEMS:2016-08..2016-11 |
| payems-avg3m-above-150k-2017-05 | Was average monthly payroll growth over the 3 months ending May 2017 above 150k, i.e. is (level(May 2017) - level(February 2017)) / 3 above 150, with total nonfarm payrolls (PAYEMS) in thousands of jobs? | No | No | no | new | PAYEMS:2017-02..2017-05 |
| payems-avg3m-above-150k-2019-04 | Was average monthly payroll growth over the 3 months ending April 2019 above 150k, i.e. is (level(April 2019) - level(January 2019)) / 3 above 150, with total nonfarm payrolls (PAYEMS) in thousands of jobs? | Yes | No | yes | new | PAYEMS:2018-12..2019-04 |
| payems-avg3m-above-150k-2019-12 | Was average monthly payroll growth over the 3 months ending December 2019 above 150k, i.e. is (level(December 2019) - level(September 2019)) / 3 above 150, with total nonfarm payrolls (PAYEMS) in thousands of jobs? | Yes | Yes | no | new | PAYEMS:2019-09..2019-12 |
| payems-avg3m-above-150k-2024-06 | Was average monthly payroll growth over the 3 months ending June 2024 above 150k, i.e. is (level(June 2024) - level(March 2024)) / 3 above 150, with total nonfarm payrolls (PAYEMS) in thousands of jobs? | Yes | No | yes | new | PAYEMS:2023-04..2024-08 |
| payems-avg3m-above-150k-2024-12 | Was average monthly payroll growth over the 3 months ending December 2024 above 150k, i.e. is (level(December 2024) - level(September 2024)) / 3 above 150, with total nonfarm payrolls (PAYEMS) in thousands of jobs? | Yes | No | yes | new | PAYEMS:2024-09..2025-06 |
| payems-avg3m-above-150k-2025-01 | Was average monthly payroll growth over the 3 months ending January 2025 above 150k, i.e. is (level(January 2025) - level(October 2024)) / 3 above 150, with total nonfarm payrolls (PAYEMS) in thousands of jobs? | Yes | No | yes | new | PAYEMS:2024-09..2025-06 |
| payems-weakest-12m-2016-01 | Was January 2016 the weakest of the 12 months ending in January 2016 for payroll growth, i.e. is change(January 2016) lower than each of change(February 2015) through change(December 2015), where change(month) = level(month) - level(previous month), with total nonfarm payrolls (PAYEMS) in thousands of jobs? | No | No | no | new | PAYEMS:2015-01..2016-01 |
| payems-weakest-12m-2018-11 | Was November 2018 the weakest of the 12 months ending in November 2018 for payroll growth, i.e. is change(November 2018) lower than each of change(December 2017) through change(October 2018), where change(month) = level(month) - level(previous month), with total nonfarm payrolls (PAYEMS) in thousands of jobs? | No | No | no | new | PAYEMS:2017-11..2018-11 |
| payems-weakest-12m-2023-03 | Was March 2023 the weakest of the 12 months ending in March 2023 for payroll growth, i.e. is change(March 2023) lower than each of change(April 2022) through change(February 2023), where change(month) = level(month) - level(previous month), with total nonfarm payrolls (PAYEMS) in thousands of jobs? | Yes | No | yes | new | PAYEMS:2020-10..2023-03 |
| payems-weakest-12m-2024-04 | Was April 2024 the weakest of the 12 months ending in April 2024 for payroll growth, i.e. is change(April 2024) lower than each of change(May 2023) through change(March 2024), where change(month) = level(month) - level(previous month), with total nonfarm payrolls (PAYEMS) in thousands of jobs? | No | Yes | yes | new | PAYEMS:2023-04..2024-08 |
| pcepi-yoy-above-2.5-2017-01 | Is PCE inflation (year over year) above 2.5% for January 2017, i.e. is the 12-month percent change in the PCE price index (PCEPI) from January 2016 to January 2017, 100 * (level(January 2017) / level(January 2016) - 1), above 2.5? | No | No | no | new | PCEPI:2016-01..2017-01 |
| unrate-mom-rise-2020-12 | Did the unemployment rate (UNRATE) rise in December 2020 versus the prior month, i.e. was it higher than in November 2020 (as published, to one decimal place)? | No | No | no | new | UNRATE:2020-11..2020-12 |
| unrate-mom-rise-2021-12 | Did the unemployment rate (UNRATE) rise in December 2021 versus the prior month, i.e. was it higher than in November 2021 (as published, to one decimal place)? | No | No | no | new | UNRATE:2021-11..2021-12 |
| unrate-mom-rise-2023-02 | Did the unemployment rate (UNRATE) rise in February 2023 versus the prior month, i.e. was it higher than in January 2023 (as published, to one decimal place)? | Yes | Yes | no | new | UNRATE:2023-01..2023-02 |
| unrate-mom-rise-2023-05 | Did the unemployment rate (UNRATE) rise in May 2023 versus the prior month, i.e. was it higher than in April 2023 (as published, to one decimal place)? | Yes | Yes | no | new | UNRATE:2023-04..2023-05 |
