# VintageBench v1 tasks

`v1.jsonl` stores task definitions only (id, series_id, template, period,
threshold, as_of_date, revision_date, question, answer_type, kind, notes). Gold
answers, flips and threshold distances are recomputed from the local RTDSM
vintages by `vintagebench.tasks.load_tasks`, which fails if a task's computed
kind disagrees with its stored kind. No data values are stored or quoted here
(SPEC §2.3). Regenerate with `python -m vintagebench.tasks --build`
(seed 0).

## Conventions used to compute gold answers

Questions state the question in plain words and intentionally do not spell out
the formula; the gold answer uses these conventions (SPEC §3). All quantities are
computed within one vintage, unrounded unless stated; ties count as No.

| template | series | example question | thresholds | gold (deciding quantity) | materiality margin | control cap | key observations | computation window |
|---|---|---|---|---|---|---|---|---|
| gdp_shrink | ROUTPUT | Did US real GDP shrink in 2019 Q2? | 0 | annualized quarter-over-quarter % change of the real GDP level; Yes iff below 0 (the level fell) | 0.05 pp (half the 0.1 pp unit of published annualized growth) | 1 pp | q-1, q | q-1..q (2 quarters) |
| gdp_growth_above | ROUTPUT | Did US real GDP grow faster than a 2% annual rate in 2019 Q2? | 2 | annualized quarter-over-quarter % change of the real GDP level; Yes iff above the threshold | 0.05 pp | 1 pp | q-1, q | q-1..q (2 quarters) |
| payroll_weakest_12m | EMPLOY | Was May 2019 the weakest month for US job growth (nonfarm payrolls) in the 12 months through May 2019? | 0 | payroll change in the month (level difference, thousands) minus the smallest change of the 11 preceding months; Yes iff below 0 | 0.5 thousand (half the published 1 thousand unit) | 35 thousand | t-12..t (13 obs) | t-12..t (13 months) |
| payroll_avg3m_above | EMPLOY | Did US employers add more than 150,000 jobs a month on average (nonfarm payrolls) in the three months through May 2019? | 100, 150 | (level(t) - level(t-3)) / 3 in thousands; Yes iff above the threshold | 0.5 thousand | 35 thousand | t-3, t | t-3..t (4 months) |
| ip_fell | IPT | Did US industrial production fall in May 2019? | 0 | month-over-month % change of the IP index; Yes iff below 0 (the level fell) | 0.05 pp (half the published 0.1% unit) | 0.3 pp | t-1, t | t-1..t (2 months) |
| cpi_12m_above | PCPI | Was US consumer price inflation (CPI) above 3% over the 12 months through May 2019? | 2, 2.5, 3 | 12-month % change of the seasonally adjusted CPI index; Yes iff above the threshold | 0.05 pp (half the published 0.1 pp unit) | 0.25 pp | t-12, t | t-12..t (13 months) |
| cpi_1m_above | PCPI | Did US consumer prices (CPI) rise by more than 0.3% in May 2019? | 0.2, 0.3 | month-over-month % change of the seasonally adjusted CPI index; Yes iff above the threshold | 0.05 pp | 0.1 pp | t-1, t | t-1..t (2 months) |
| unemployment_rose | RUC | Did the US unemployment rate rise in May 2019? | 0 | month-over-month change of the rate rounded to its published 0.1 pp; Yes iff it rose (by at least 0.1); unchanged is No. The distance is measured from 0.05, midway between unchanged and +0.1 | 0.05 pp (always met: changes are multiples of 0.1) | 0.15 pp | t-1, t | t-1..t (2 months) |

Key observations are the observations the gold reads (also used by the
memorization probe). The computation window is every observation from the
earliest key observation through the period, inclusive (t = the task's month, q =
its quarter); it is what same-series overlap, the COVID exclusion and the
no_change identity check use.

Notes: GDP growth is the annualized quarter-over-quarter change of the real GDP
level; payroll changes are level differences in thousands; IP 'fell' is a
month-over-month level decline; CPI inflation uses the seasonally adjusted CPI
index in RTDSM (BLS's headline 12-month figure uses the unadjusted index);
'unemployment rose' compares the published rates (0.1 pp precision).

## Date rules and filters

- as_of_date: the first RTDSM vintage containing the period (first release);
  periods 2016-2025, first released after the baseline vintage.
- flip / control: revision_date = pinned latest vintage, >= 365 days after
  as_of_date. flip: Yes/No differs; control: same answer, and |distance| <= the
  control cap in both vintages (tighter than v0's 10 margins / 40k).
- no_change: revision_date = last vintage of the unbroken run after the as-of
  vintage in which every computation-window observation is identical (>= 1
  vintage later; >= 90 days preferred); within the control cap.
- Materiality (all kinds): |distance| >= margin in both vintages.
- COVID exclusion (all kinds): computation window touching 2020-02..2021-03
  (2020 Q1..2021 Q1 for GDP).

Candidate counts per filter stage (instances = every series/template/period/
threshold computable at first release):

| series | instances | gap >= 365d | material | material, no COVID | flip | control (uncapped) | control (capped) | no-change identical | no_change |
|---|---|---|---|---|---|---|---|---|---|
| EMPLOY | 360 | 348 | 344 | 284 | 44 | 240 | 15 | 3 | 1 |
| IPT | 120 | 116 | 103 | 89 | 12 | 77 | 14 | 7 | 4 |
| PCPI | 593 | 580 | 505 | 403 | 3 | 400 | 47 | 438 | 69 |
| ROUTPUT | 80 | 76 | 74 | 62 | 7 | 55 | 9 | 2 | 1 |
| RUC | 118 | 115 | 115 | 100 | 16 | 84 | 58 | 93 | 75 |
| all | 1271 | 1235 | 1141 | 938 | 82 | 856 | 143 | 543 | 150 |

## Selection

`select_v1(candidates, seed=0)`: 20 flips, 20 controls, 5 no_change; as-of
answers balanced Yes/No within each kind (10/10, 10/10, 3/2). Greedy and seeded:
each slot takes the eligible candidate that overlaps the fewest already-selected
same-series computation windows, then spreads series, each series' Yes/No
answers, years and templates, then the seeded rank. Overlap is allowed only
when a slot cannot otherwise be filled.

Unfilled slots: 0 (flip 0, control 0, no_change 0). Overlapping same-series pairs: 0; clusters: 45 for 45 tasks.

| kind | series | as-of Yes | as-of No |
|---|---|---|---|
| flip | EMPLOY | 2 | 2 |
| flip | IPT | 2 | 2 |
| flip | PCPI | 1 | 2 |
| flip | ROUTPUT | 2 | 2 |
| flip | RUC | 3 | 2 |
| control | EMPLOY | 2 | 1 |
| control | IPT | 2 | 2 |
| control | PCPI | 2 | 3 |
| control | ROUTPUT | 2 | 2 |
| control | RUC | 2 | 2 |
| no_change | PCPI | 2 | 1 |
| no_change | RUC | 1 | 1 |

Tasks per period year: 2016: 6, 2017: 5, 2018: 5, 2019: 5, 2020: 1, 2021: 4, 2022: 5, 2023: 4, 2024: 5, 2025: 5.

Unemployment-rate flips: 5 of 5 are rounding-boundary flips (the published
month-over-month change is unchanged in one vintage and +0.1 pp in the other),
i.e. the smallest revision that can change the answer. Computed by
`rounding_boundary_flips` at build time.

## Tasks

| id | question | kind | as-of answer | revised answer | cluster |
|---|---|---|---|---|---|
| employ-payroll_avg3m_above-150k-2017-05 | Did US employers add more than 150,000 jobs a month on average (nonfarm payrolls) in the three months through May 2017? | flip | No | Yes | EMPLOY-1 |
| employ-payroll_weakest_12m-2018-07 | Was July 2018 the weakest month for US job growth (nonfarm payrolls) in the 12 months through July 2018? | flip | No | Yes | EMPLOY-2 |
| employ-payroll_avg3m_above-150k-2023-11 | Did US employers add more than 150,000 jobs a month on average (nonfarm payrolls) in the three months through November 2023? | flip | Yes | No | EMPLOY-6 |
| employ-payroll_avg3m_above-150k-2024-05 | Did US employers add more than 150,000 jobs a month on average (nonfarm payrolls) in the three months through May 2024? | flip | Yes | No | EMPLOY-7 |
| ipt-ip_fell-2019-03 | Did US industrial production fall in March 2019? | flip | Yes | No | IPT-3 |
| ipt-ip_fell-2021-08 | Did US industrial production fall in August 2021? | flip | No | Yes | IPT-4 |
| ipt-ip_fell-2023-12 | Did US industrial production fall in December 2023? | flip | No | Yes | IPT-7 |
| ipt-ip_fell-2025-07 | Did US industrial production fall in July 2025? | flip | Yes | No | IPT-8 |
| pcpi-cpi_1m_above-0.2pct-2016-03 | Did US consumer prices (CPI) rise by more than 0.2% in March 2016? | flip | No | Yes | PCPI-1 |
| pcpi-cpi_1m_above-0.3pct-2016-10 | Did US consumer prices (CPI) rise by more than 0.3% in October 2016? | flip | Yes | No | PCPI-2 |
| pcpi-cpi_1m_above-0.2pct-2022-11 | Did US consumer prices (CPI) rise by more than 0.2% in November 2022? | flip | No | Yes | PCPI-8 |
| routput-gdp_growth_above-2016q4 | Did US real GDP grow faster than a 2% annual rate in 2016 Q4? | flip | No | Yes | ROUTPUT-2 |
| routput-gdp_growth_above-2018q4 | Did US real GDP grow faster than a 2% annual rate in 2018 Q4? | flip | Yes | No | ROUTPUT-4 |
| routput-gdp_growth_above-2019q3 | Did US real GDP grow faster than a 2% annual rate in 2019 Q3? | flip | No | Yes | ROUTPUT-5 |
| routput-gdp_shrink-2022q2 | Did US real GDP shrink in 2022 Q2? | flip | Yes | No | ROUTPUT-6 |
| ruc-unemployment_rose-2016-04 | Did the US unemployment rate rise in April 2016? | flip | No | Yes | RUC-1 |
| ruc-unemployment_rose-2017-01 | Did the US unemployment rate rise in January 2017? | flip | Yes | No | RUC-3 |
| ruc-unemployment_rose-2020-01 | Did the US unemployment rate rise in January 2020? | flip | Yes | No | RUC-5 |
| ruc-unemployment_rose-2025-03 | Did the US unemployment rate rise in March 2025? | flip | Yes | No | RUC-10 |
| ruc-unemployment_rose-2025-05 | Did the US unemployment rate rise in May 2025? | flip | No | Yes | RUC-11 |
| employ-payroll_avg3m_above-150k-2019-03 | Did US employers add more than 150,000 jobs a month on average (nonfarm payrolls) in the three months through March 2019? | control | Yes | Yes | EMPLOY-3 |
| employ-payroll_avg3m_above-150k-2019-07 | Did US employers add more than 150,000 jobs a month on average (nonfarm payrolls) in the three months through July 2019? | control | No | No | EMPLOY-4 |
| employ-payroll_weakest_12m-2023-03 | Was March 2023 the weakest month for US job growth (nonfarm payrolls) in the 12 months through March 2023? | control | Yes | Yes | EMPLOY-5 |
| ipt-ip_fell-2017-09 | Did US industrial production fall in September 2017? | control | No | No | IPT-1 |
| ipt-ip_fell-2018-09 | Did US industrial production fall in September 2018? | control | No | No | IPT-2 |
| ipt-ip_fell-2021-12 | Did US industrial production fall in December 2021? | control | Yes | Yes | IPT-5 |
| ipt-ip_fell-2022-08 | Did US industrial production fall in August 2022? | control | Yes | Yes | IPT-6 |
| pcpi-cpi_1m_above-0.3pct-2018-05 | Did US consumer prices (CPI) rise by more than 0.3% in May 2018? | control | No | No | PCPI-4 |
| pcpi-cpi_12m_above-2.5pct-2019-12 | Was US consumer price inflation (CPI) above 2.5% over the 12 months through December 2019? | control | No | No | PCPI-5 |
| pcpi-cpi_12m_above-2.5pct-2024-11 | Was US consumer price inflation (CPI) above 2.5% over the 12 months through November 2024? | control | Yes | Yes | PCPI-9 |
| pcpi-cpi_1m_above-0.3pct-2025-02 | Did US consumer prices (CPI) rise by more than 0.3% in February 2025? | control | No | No | PCPI-10 |
| pcpi-cpi_1m_above-0.2pct-2025-06 | Did US consumer prices (CPI) rise by more than 0.2% in June 2025? | control | Yes | Yes | PCPI-11 |
| routput-gdp_growth_above-2016q2 | Did US real GDP grow faster than a 2% annual rate in 2016 Q2? | control | No | No | ROUTPUT-1 |
| routput-gdp_growth_above-2017q2 | Did US real GDP grow faster than a 2% annual rate in 2017 Q2? | control | Yes | Yes | ROUTPUT-3 |
| routput-gdp_growth_above-2024q1 | Did US real GDP grow faster than a 2% annual rate in 2024 Q1? | control | No | No | ROUTPUT-7 |
| routput-gdp_growth_above-2024q4 | Did US real GDP grow faster than a 2% annual rate in 2024 Q4? | control | Yes | Yes | ROUTPUT-8 |
| ruc-unemployment_rose-2016-07 | Did the US unemployment rate rise in July 2016? | control | No | No | RUC-2 |
| ruc-unemployment_rose-2021-06 | Did the US unemployment rate rise in June 2021? | control | Yes | Yes | RUC-6 |
| ruc-unemployment_rose-2022-12 | Did the US unemployment rate rise in December 2022? | control | No | No | RUC-7 |
| ruc-unemployment_rose-2023-10 | Did the US unemployment rate rise in October 2023? | control | Yes | Yes | RUC-8 |
| pcpi-cpi_12m_above-2.5pct-2018-02 | Was US consumer price inflation (CPI) above 2.5% over the 12 months through February 2018? | no_change | No | No | PCPI-3 |
| pcpi-cpi_1m_above-0.2pct-2021-08 | Did US consumer prices (CPI) rise by more than 0.2% in August 2021? | no_change | Yes | Yes | PCPI-6 |
| pcpi-cpi_1m_above-0.3pct-2022-09 | Did US consumer prices (CPI) rise by more than 0.3% in September 2022? | no_change | Yes | Yes | PCPI-7 |
| ruc-unemployment_rose-2017-08 | Did the US unemployment rate rise in August 2017? | no_change | Yes | Yes | RUC-4 |
| ruc-unemployment_rose-2024-12 | Did the US unemployment rate rise in December 2024? | no_change | No | No | RUC-9 |
