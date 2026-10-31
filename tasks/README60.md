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

| template | eligible flips | eligible controls | in this set |
|---|---|---|---|
| gdpc1-growth-above-2 | 3 | 19 | 5 |
| gdpc1-qoq-shrink | 0 | 5 | 4 |
| indpro-mom-fall | 11 | 58 | 17 |
| payems-avg3m-above-100k | 9 | 12 | 6 |
| payems-avg3m-above-150k | 14 | 29 | 7 |
| payems-weakest-12m | 13 | 15 | 7 |
| pcepi-yoy-above-2.5 | 2 | 28 | 8 |
| unrate-mom-rise | 0 | 101 | 6 |

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
| GDPC1 | 3 | 6 | 9 |
| INDPRO | 11 | 6 | 17 |
| PAYEMS | 14 | 6 | 20 |
| PCEPI | 2 | 6 | 8 |
| UNRATE | 0 | 6 | 6 |

| year | tasks |
|---|---|
| 2016 | 4 |
| 2017 | 6 |
| 2018 | 4 |
| 2019 | 5 |
| 2020 | 4 |
| 2021 | 5 |
| 2022 | 7 |
| 2023 | 7 |
| 2024 | 7 |
| 2025 | 11 |

## Tasks (60)

| id | question | as-of answer | revised answer | flips | set |
|---|---|---|---|---|---|
| gdpc1-growth-above-2-2016-01 | Did real GDP grow faster than 2% (annualized) in Q1 2016, i.e. was the annualized growth rate of real GDP (GDPC1) from Q4 2015 to Q1 2016, 100 * ((level(Q1 2016) / level(Q4 2015))^4 - 1), above 2.0%? | No | No | no | pilot20 |
| gdpc1-growth-above-2-2016-04 | Did real GDP grow faster than 2% (annualized) in Q2 2016, i.e. was the annualized growth rate of real GDP (GDPC1) from Q1 2016 to Q2 2016, 100 * ((level(Q2 2016) / level(Q1 2016))^4 - 1), above 2.0%? | No | Yes | yes | pilot20 |
| gdpc1-growth-above-2-2018-10 | Did real GDP grow faster than 2% (annualized) in Q4 2018, i.e. was the annualized growth rate of real GDP (GDPC1) from Q3 2018 to Q4 2018, 100 * ((level(Q4 2018) / level(Q3 2018))^4 - 1), above 2.0%? | Yes | No | yes | pilot20 |
| gdpc1-growth-above-2-2023-01 | Did real GDP grow faster than 2% (annualized) in Q1 2023, i.e. was the annualized growth rate of real GDP (GDPC1) from Q4 2022 to Q1 2023, 100 * ((level(Q1 2023) / level(Q4 2022))^4 - 1), above 2.0%? | No | Yes | yes | pilot20 |
| gdpc1-growth-above-2-2024-01 | Did real GDP grow faster than 2% (annualized) in Q1 2024, i.e. was the annualized growth rate of real GDP (GDPC1) from Q4 2023 to Q1 2024, 100 * ((level(Q1 2024) / level(Q4 2023))^4 - 1), above 2.0%? | No | No | no | new |
| gdpc1-qoq-shrink-2017-01 | Did real GDP shrink in Q1 2017, i.e. was real GDP (GDPC1) in Q1 2017 lower than in Q4 2016? | No | No | no | new |
| gdpc1-qoq-shrink-2022-04 | Did real GDP shrink in Q2 2022, i.e. was real GDP (GDPC1) in Q2 2022 lower than in Q1 2022? | Yes | Yes | no | new |
| gdpc1-qoq-shrink-2025-01 | Did real GDP shrink in Q1 2025, i.e. was real GDP (GDPC1) in Q1 2025 lower than in Q4 2024? | Yes | Yes | no | pilot20 |
| gdpc1-qoq-shrink-2025-10 | Did real GDP shrink in Q4 2025, i.e. was real GDP (GDPC1) in Q4 2025 lower than in Q3 2025? | No | No | no | new |
| indpro-mom-fall-2016-09 | Did industrial production (INDPRO) fall in September 2016 versus the prior month, i.e. was its level in September 2016 lower than in August 2016? | No | Yes | yes | pilot20 |
| indpro-mom-fall-2017-07 | Did industrial production (INDPRO) fall in July 2017 versus the prior month, i.e. was its level in July 2017 lower than in June 2017? | No | Yes | yes | new |
| indpro-mom-fall-2017-08 | Did industrial production (INDPRO) fall in August 2017 versus the prior month, i.e. was its level in August 2017 lower than in July 2017? | Yes | Yes | no | pilot20 |
| indpro-mom-fall-2019-02 | Did industrial production (INDPRO) fall in February 2019 versus the prior month, i.e. was its level in February 2019 lower than in January 2019? | No | Yes | yes | new |
| indpro-mom-fall-2019-03 | Did industrial production (INDPRO) fall in March 2019 versus the prior month, i.e. was its level in March 2019 lower than in February 2019? | Yes | No | yes | new |
| indpro-mom-fall-2020-01 | Did industrial production (INDPRO) fall in January 2020 versus the prior month, i.e. was its level in January 2020 lower than in December 2019? | Yes | Yes | no | new |
| indpro-mom-fall-2020-02 | Did industrial production (INDPRO) fall in February 2020 versus the prior month, i.e. was its level in February 2020 lower than in January 2020? | No | No | no | pilot20 |
| indpro-mom-fall-2020-09 | Did industrial production (INDPRO) fall in September 2020 versus the prior month, i.e. was its level in September 2020 lower than in August 2020? | Yes | Yes | no | new |
| indpro-mom-fall-2021-12 | Did industrial production (INDPRO) fall in December 2021 versus the prior month, i.e. was its level in December 2021 lower than in November 2021? | Yes | Yes | no | new |
| indpro-mom-fall-2022-04 | Did industrial production (INDPRO) fall in April 2022 versus the prior month, i.e. was its level in April 2022 lower than in March 2022? | No | No | no | new |
| indpro-mom-fall-2022-08 | Did industrial production (INDPRO) fall in August 2022 versus the prior month, i.e. was its level in August 2022 lower than in July 2022? | Yes | No | yes | pilot20 |
| indpro-mom-fall-2023-12 | Did industrial production (INDPRO) fall in December 2023 versus the prior month, i.e. was its level in December 2023 lower than in November 2023? | No | Yes | yes | new |
| indpro-mom-fall-2024-03 | Did industrial production (INDPRO) fall in March 2024 versus the prior month, i.e. was its level in March 2024 lower than in February 2024? | No | Yes | yes | new |
| indpro-mom-fall-2025-01 | Did industrial production (INDPRO) fall in January 2025 versus the prior month, i.e. was its level in January 2025 lower than in December 2024? | No | Yes | yes | new |
| indpro-mom-fall-2025-07 | Did industrial production (INDPRO) fall in July 2025 versus the prior month, i.e. was its level in July 2025 lower than in June 2025? | Yes | No | yes | new |
| indpro-mom-fall-2025-08 | Did industrial production (INDPRO) fall in August 2025 versus the prior month, i.e. was its level in August 2025 lower than in July 2025? | No | Yes | yes | new |
| indpro-mom-fall-2025-11 | Did industrial production (INDPRO) fall in November 2025 versus the prior month, i.e. was its level in November 2025 lower than in October 2025? | No | Yes | yes | new |
| payems-avg3m-above-100k-2019-03 | Was average monthly payroll growth over the 3 months ending March 2019 above 100k, i.e. is (level(March 2019) - level(December 2018)) / 3 above 100, with total nonfarm payrolls (PAYEMS) in thousands of jobs? | Yes | Yes | no | pilot20 |
| payems-avg3m-above-100k-2024-08 | Was average monthly payroll growth over the 3 months ending August 2024 above 100k, i.e. is (level(August 2024) - level(May 2024)) / 3 above 100, with total nonfarm payrolls (PAYEMS) in thousands of jobs? | Yes | No | yes | new |
| payems-avg3m-above-100k-2025-03 | Was average monthly payroll growth over the 3 months ending March 2025 above 100k, i.e. is (level(March 2025) - level(December 2024)) / 3 above 100, with total nonfarm payrolls (PAYEMS) in thousands of jobs? | Yes | No | yes | new |
| payems-avg3m-above-100k-2025-04 | Was average monthly payroll growth over the 3 months ending April 2025 above 100k, i.e. is (level(April 2025) - level(January 2025)) / 3 above 100, with total nonfarm payrolls (PAYEMS) in thousands of jobs? | Yes | No | yes | new |
| payems-avg3m-above-100k-2025-05 | Was average monthly payroll growth over the 3 months ending May 2025 above 100k, i.e. is (level(May 2025) - level(February 2025)) / 3 above 100, with total nonfarm payrolls (PAYEMS) in thousands of jobs? | Yes | No | yes | new |
| payems-avg3m-above-100k-2025-06 | Was average monthly payroll growth over the 3 months ending June 2025 above 100k, i.e. is (level(June 2025) - level(March 2025)) / 3 above 100, with total nonfarm payrolls (PAYEMS) in thousands of jobs? | Yes | No | yes | pilot20 |
| payems-avg3m-above-150k-2016-05 | Was average monthly payroll growth over the 3 months ending May 2016 above 150k, i.e. is (level(May 2016) - level(February 2016)) / 3 above 150, with total nonfarm payrolls (PAYEMS) in thousands of jobs? | No | No | no | new |
| payems-avg3m-above-150k-2017-05 | Was average monthly payroll growth over the 3 months ending May 2017 above 150k, i.e. is (level(May 2017) - level(February 2017)) / 3 above 150, with total nonfarm payrolls (PAYEMS) in thousands of jobs? | No | No | no | new |
| payems-avg3m-above-150k-2017-09 | Was average monthly payroll growth over the 3 months ending September 2017 above 150k, i.e. is (level(September 2017) - level(June 2017)) / 3 above 150, with total nonfarm payrolls (PAYEMS) in thousands of jobs? | No | No | no | new |
| payems-avg3m-above-150k-2019-04 | Was average monthly payroll growth over the 3 months ending April 2019 above 150k, i.e. is (level(April 2019) - level(January 2019)) / 3 above 150, with total nonfarm payrolls (PAYEMS) in thousands of jobs? | Yes | No | yes | new |
| payems-avg3m-above-150k-2019-08 | Was average monthly payroll growth over the 3 months ending August 2019 above 150k, i.e. is (level(August 2019) - level(May 2019)) / 3 above 150, with total nonfarm payrolls (PAYEMS) in thousands of jobs? | Yes | Yes | no | pilot20 |
| payems-avg3m-above-150k-2021-01 | Was average monthly payroll growth over the 3 months ending January 2021 above 150k, i.e. is (level(January 2021) - level(October 2020)) / 3 above 150, with total nonfarm payrolls (PAYEMS) in thousands of jobs? | No | Yes | yes | new |
| payems-avg3m-above-150k-2021-02 | Was average monthly payroll growth over the 3 months ending February 2021 above 150k, i.e. is (level(February 2021) - level(November 2020)) / 3 above 150, with total nonfarm payrolls (PAYEMS) in thousands of jobs? | No | Yes | yes | new |
| payems-weakest-12m-2018-11 | Was November 2018 the weakest of the 12 months ending in November 2018 for payroll growth, i.e. is change(November 2018) lower than each of change(December 2017) through change(October 2018), where change(month) = level(month) - level(previous month), with total nonfarm payrolls (PAYEMS) in thousands of jobs? | No | No | no | new |
| payems-weakest-12m-2021-12 | Was December 2021 the weakest of the 12 months ending in December 2021 for payroll growth, i.e. is change(December 2021) lower than each of change(January 2021) through change(November 2021), where change(month) = level(month) - level(previous month), with total nonfarm payrolls (PAYEMS) in thousands of jobs? | Yes | No | yes | pilot20 |
| payems-weakest-12m-2022-04 | Was April 2022 the weakest of the 12 months ending in April 2022 for payroll growth, i.e. is change(April 2022) lower than each of change(May 2021) through change(March 2022), where change(month) = level(month) - level(previous month), with total nonfarm payrolls (PAYEMS) in thousands of jobs? | No | Yes | yes | new |
| payems-weakest-12m-2022-09 | Was September 2022 the weakest of the 12 months ending in September 2022 for payroll growth, i.e. is change(September 2022) lower than each of change(October 2021) through change(August 2022), where change(month) = level(month) - level(previous month), with total nonfarm payrolls (PAYEMS) in thousands of jobs? | Yes | No | yes | pilot20 |
| payems-weakest-12m-2022-10 | Was October 2022 the weakest of the 12 months ending in October 2022 for payroll growth, i.e. is change(October 2022) lower than each of change(November 2021) through change(September 2022), where change(month) = level(month) - level(previous month), with total nonfarm payrolls (PAYEMS) in thousands of jobs? | Yes | No | yes | new |
| payems-weakest-12m-2022-11 | Was November 2022 the weakest of the 12 months ending in November 2022 for payroll growth, i.e. is change(November 2022) lower than each of change(December 2021) through change(October 2022), where change(month) = level(month) - level(previous month), with total nonfarm payrolls (PAYEMS) in thousands of jobs? | Yes | No | yes | new |
| payems-weakest-12m-2023-03 | Was March 2023 the weakest of the 12 months ending in March 2023 for payroll growth, i.e. is change(March 2023) lower than each of change(April 2022) through change(February 2023), where change(month) = level(month) - level(previous month), with total nonfarm payrolls (PAYEMS) in thousands of jobs? | Yes | No | yes | new |
| pcepi-yoy-above-2.5-2018-10 | Is PCE inflation (year over year) above 2.5% for October 2018, i.e. is the 12-month percent change in the PCE price index (PCEPI) from October 2017 to October 2018, 100 * (level(October 2018) / level(October 2017) - 1), above 2.5? | No | No | no | pilot20 |
| pcepi-yoy-above-2.5-2023-06 | Is PCE inflation (year over year) above 2.5% for June 2023, i.e. is the 12-month percent change in the PCE price index (PCEPI) from June 2022 to June 2023, 100 * (level(June 2023) / level(June 2022) - 1), above 2.5? | Yes | Yes | no | new |
| pcepi-yoy-above-2.5-2023-12 | Is PCE inflation (year over year) above 2.5% for December 2023, i.e. is the 12-month percent change in the PCE price index (PCEPI) from December 2022 to December 2023, 100 * (level(December 2023) / level(December 2022) - 1), above 2.5? | Yes | Yes | no | new |
| pcepi-yoy-above-2.5-2024-01 | Is PCE inflation (year over year) above 2.5% for January 2024, i.e. is the 12-month percent change in the PCE price index (PCEPI) from January 2023 to January 2024, 100 * (level(January 2024) / level(January 2023) - 1), above 2.5? | No | Yes | yes | pilot20 |
| pcepi-yoy-above-2.5-2024-05 | Is PCE inflation (year over year) above 2.5% for May 2024, i.e. is the 12-month percent change in the PCE price index (PCEPI) from May 2023 to May 2024, 100 * (level(May 2024) / level(May 2023) - 1), above 2.5? | Yes | Yes | no | new |
| pcepi-yoy-above-2.5-2024-08 | Is PCE inflation (year over year) above 2.5% for August 2024, i.e. is the 12-month percent change in the PCE price index (PCEPI) from August 2023 to August 2024, 100 * (level(August 2024) / level(August 2023) - 1), above 2.5? | No | No | no | pilot20 |
| pcepi-yoy-above-2.5-2024-11 | Is PCE inflation (year over year) above 2.5% for November 2024, i.e. is the 12-month percent change in the PCE price index (PCEPI) from November 2023 to November 2024, 100 * (level(November 2024) / level(November 2023) - 1), above 2.5? | No | Yes | yes | pilot20 |
| pcepi-yoy-above-2.5-2025-06 | Is PCE inflation (year over year) above 2.5% for June 2025, i.e. is the 12-month percent change in the PCE price index (PCEPI) from June 2024 to June 2025, 100 * (level(June 2025) / level(June 2024) - 1), above 2.5? | Yes | Yes | no | new |
| unrate-mom-rise-2017-01 | Did the unemployment rate (UNRATE) rise in January 2017 versus the prior month, i.e. was it higher than in December 2016 (as published, to one decimal place)? | Yes | Yes | no | new |
| unrate-mom-rise-2018-06 | Did the unemployment rate (UNRATE) rise in June 2018 versus the prior month, i.e. was it higher than in May 2018 (as published, to one decimal place)? | Yes | Yes | no | pilot20 |
| unrate-mom-rise-2020-12 | Did the unemployment rate (UNRATE) rise in December 2020 versus the prior month, i.e. was it higher than in November 2020 (as published, to one decimal place)? | No | No | no | new |
| unrate-mom-rise-2021-03 | Did the unemployment rate (UNRATE) rise in March 2021 versus the prior month, i.e. was it higher than in February 2021 (as published, to one decimal place)? | No | No | no | pilot20 |
| unrate-mom-rise-2023-05 | Did the unemployment rate (UNRATE) rise in May 2023 versus the prior month, i.e. was it higher than in April 2023 (as published, to one decimal place)? | Yes | Yes | no | new |
| unrate-mom-rise-2023-07 | Did the unemployment rate (UNRATE) rise in July 2023 versus the prior month, i.e. was it higher than in June 2023 (as published, to one decimal place)? | No | No | no | new |
