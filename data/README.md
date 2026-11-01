# VintageBench data (RTDSM)

Real-time (vintage) data from the Federal Reserve Bank of Philadelphia's Real-Time
Data Set for Macroeconomists (RTDSM). **No data are committed.** Terms and citation are
in [NOTICE.md](NOTICE.md). To get the data:

```bash
python scripts/fetch_data.py                # downloads 5 xlsx to data/raw/, verifies, caches parquet
python scripts/fetch_data.py --verify-only  # no network: re-verify data/raw
```

Committed here: `manifest.json` (the pinned vintage range per series), `checksums.json`
(SHA-256 hashes and counts) and this file. Gitignored: `raw/` (the xlsx downloads and
the parsed `<SERIES>.parquet`).

## Layout and processing

Each RTDSM workbook has one sheet. Rows are observations, with a `DATE` column in the
form `yyyy:mm` (monthly) or `yyyy:Qq` (quarterly). Each further column is one vintage,
labelled `<SERIES>yyMmm` (monthly vintages) or `<SERIES>yyQq` (quarterly vintages), and
holds the full time-series history as published in that vintage. Missing cells are
`#N/A`.

`scripts/fetch_data.py` (using `vintagebench.data.parse_workbook`) turns each workbook
into a long table with columns series_id, observation_date (first day of the period),
vintage (the column label), vintage_date and value. Missing cells are dropped. It keeps:

- observations from 2015-01-01;
- vintages from the **baseline** onward. The baseline is the latest vintage dated on
  or before 2016-01-01, so that `get_as_of` is defined on 2016-01-01. The range ends at
  the pinned last vintage in `manifest.json`.

Verification: `checksums.json` holds the SHA-256 of the canonical text of that table
(rows sorted, values printed as `%.6f`). RTDSM appends a new column each month. The
pinned range does not change when it does, so the check still passes. It fails, with a
nonzero exit, if any pinned value changes. The SHA-256 of each raw file on the pin date
is recorded for information only.

## Vintage dates

An RTDSM label names only a month (or quarter). VintageBench assigns each label a
vintage_date. Every value in the vintage must have been published **on or before** that
date, because tasks serve vintage V to a model told "today is vintage_date(V)". An
earlier date would leak future data. A later date only makes the data look slightly
stale.

| Series | Rule | Documentation (verbatim) |
|---|---|---|
| ROUTPUT | 15th of the vintage month | ROUTPUT specific notes: "Monthly vintages reflect the data available in the middle of the month." General NIPA notes: "We think of the date as being in the middle of the month, before BEA releases its next report at the end of that month. Thus, a vintage dated “January” includes BEA's report released in December, but not in January." |
| RUC | 15th of the quarter's middle month (Q1 Feb 15, Q2 May 15, Q3 Aug 15, Q4 Nov 15) | RUC specific notes: "collected in the middle of the quarter (February 15, May 15, August 15, and November 15)". General non-NIPA notes: "We tried to time the vintages as close as possible to the 15th of the middle month of each quarter, and we do not incorporate the data of any release published after the 15th." |
| EMPLOY | last calendar day of the vintage month (conservative) | EMPLOY notes: "the vintages for nonfarm payrolls are collected each month, and the day corresponding to the monthly vintage date depends on the day that the data are released by BLS." |
| IPT | last calendar day of the vintage month (conservative) | IP notes: "the day corresponding to the monthly vintages depends on the day the data are released"; "Over the period since 1962, the release dates have varied from the 12th to the 18th." |
| PCPI | last calendar day of the vintage month (conservative) | PCPI specific notes: "Monthly vintages reflect the data available shortly after the U.S. Bureau of Labor Statistics (BLS) releases its monthly report on consumer prices." |

Why month-end for EMPLOY, IPT and PCPI:

- RTDSM gives no fixed day for these three series.
- The BLS release-date file linked from the EMPLOY and RUC pages
  (`Release_-Dates-Employment_Situation-BLS.xls`) is titled "Release dates for the
  Employment Situation, 1960-2002". It does not cover 2016 onward, so it cannot date
  these vintages.
- A fixed mid-month day would leak. During the 2025 federal shutdown, PCPI25M10
  already contains the September 2025 CPI. BLS published that CPI late in October
  2025, after any mid-month day. In the same period IPT25M10 and IPT25M11 both end in
  August 2025, and EMPLOY25M10 ends in August 2025.
- In normal months the next release comes after month-end (payrolls on the first Friday
  of the next month, CPI and IP around the middle of the next month). So month-end
  falls after the vintage's own release and before the next one.

Tradeoff: the as-of date can be up to about four weeks later than the actual release.
Payrolls are usually out in the first week of the month, so for EMPLOY the as-of date
lags most. A model told "today is <month-end>" sees exactly what had been published by
then, and nothing published later.

Sanity checks run on every fetch (`check_release_lags`):

- In every pinned vintage of the monthly series, the last observation is for a month
  before the vintage month (RUC: before the quarter's middle month).
- In every ROUTPUT vintage, the last quarter ended at least two months before the
  vintage month. This follows RTDSM Table 4.A: the mid-February vintage ends with the
  advance estimate for Q4.
- All five series passed at the pin.
- Shutdown-delayed releases appear where expected. RUC25Q4 ends in August 2025: the
  September report came out on November 20, after the 15th. ROUTPUT25M11 and
  ROUTPUT25M12 end in 2025 Q2. 2025 Q3 first appears in ROUTPUT26M1.

## Variable mapping

Variable pages: `https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/<variable>`
(employ, routput, ipt, ruc, pcpi). Files:
`https://www.philadelphiafed.org/-/media/FRBP/Assets/Surveys-And-Data/real-time-data/data-files/xlsx/<file>`.
Documentation: `.../data-files/documentation/gen_doc_NIPA.pdf`, `gen_doc_nonNIPA.pdf`,
`doc_ip.pdf`, and `.../data-files/<VAR>/specific_documentation_<var>.pdf`
(`PCPI/Specific_Documentation_PCPI.pdf`). All accessed 2026-11-01.

| Series | RTDSM variable / file | Units | SA | Obs. freq. | Vintage freq. | First (baseline) vintage | Pinned last vintage | Publication decimals |
|---|---|---|---|---|---|---|---|---|
| EMPLOY | Nonfarm Payroll Employment, `employMvMd.xlsx` | thousands of employees | yes | monthly | monthly | EMPLOY15M12 (2015-12-31) | EMPLOY26M9 (2026-09-30) | 0 |
| ROUTPUT | Real GNP/GDP, monthly vintages, `routputMvQd.xlsx` | billions of real (chained) dollars, annual rate; base year varies by vintage | yes | quarterly | monthly | ROUTPUT15M12 (2015-12-15) | ROUTPUT26M10 (2026-10-15) | 1 |
| IPT | Industrial Production Index: Total, `iptMvMd.xlsx` | index; base period varies by vintage | yes | monthly | monthly | IPT15M12 (2015-12-31) | IPT26M9 (2026-09-30) | 1 |
| RUC | Unemployment Rate, `rucQvMd.xlsx` | percent | yes | monthly | quarterly (mid-quarter) | RUC15Q4 (2015-11-15) | RUC26Q3 (2026-08-15) | 1 |
| PCPI | Consumer Price Index, Monthly Vintages, `pcpiMvMd.xlsx` | index (base value 100) | yes | monthly | monthly | PCPI15M12 (2015-12-31) | PCPI26M9 (2026-09-30) | 3 |

"Publication decimals" is the maximum number of decimal places found in the pinned
range. Half a unit in that place is the matching tolerance (`SeriesInfo.tolerance`).

How each variable was checked against the intended concept (quotes are verbatim):

- **EMPLOY.**
  - Variable page: "Nonfarm Payroll Employment (EMPLOY) ... Monthly Vintages
    (Thousands of employees, seasonally adjusted)".
  - Notes: "the total number of employees on nonagricultural payrolls, sometimes
    called “nonfarm payroll employment.”" and "All data are monthly, seasonally
    adjusted, and expressed in thousands of employees."
  - The source is BLS's establishment survey (CES). The notes say, "The CES includes
    such variables as nonfarm payroll employment".
- **ROUTPUT.**
  - Specific notes: "Expressed in billions of real dollars, seasonally adjusted,
    annual rate." and "real, chain-weight GDP in vintages starting with that of
    1996:M1".
  - The high-frequency source is "Bureau of Economic Analysis's (BEA) Survey of
    Current Business".
  - We use the monthly-vintage file, not `ROUTPUTQvQd.xlsx`, so that the advance,
    second and third estimates are all visible.
- **IPT.**
  - IP notes: "the Federal Reserve Board's index of industrial production. Two series
    are available: total industrial production and industrial production in the
    manufacturing sector."
  - Also: "starting in April 1990, the official report is the Fed's G.17 release" and
    "All data are monthly and seasonally adjusted. The base year for the indexes
    varies over vintages (but not over time within a vintage)."
  - Because the base year varies, level revisions across vintages mix in rebasing.
    Compare growth rates instead.
- **RUC.**
  - Specific notes: "RUC--Civilian Rate of Unemployment" and "Expressed in percentage
    points. Seasonally adjusted. Quarterly vintages. Monthly observations."
  - Also: "revisions to the rate of unemployment are small and confined to changes in
    seasonal factors". This is why RUC is the low-revision control series.
- **PCPI.**
  - Specific notes: "This series is the consumer price index, seasonally adjusted,
    with a base-year value of 100." and "The U.S. Bureau of Labor Statistics revises
    the seasonally adjusted data on consumer prices annually after it recalculates
    seasonal adjustment factors. The revised data are incorporated into our February
    vintages."
  - Also: three decimal places "beginning with the time-series observation for 2007M1".

### Substitution: PCPI (CPI) instead of the PCE price index

RTDSM has no monthly-vintage total PCE price index:

- The only total PCE price index is "Price Index for Personal Consumption Expenditures,
  Constructed (PCON)". Its page lists only "Quarterly Vintages" (`pconQvQd.xlsx`) and
  says it is "Constructed as the ratio of nominal PCE to real PCE, multiplied by 100".
- The full-history page lists monthly-observation PCE price indexes only for
  components (PCONGM, PCONSHHM, PCONSNPM, PCONHHM), not for the total.
- Core PCE (PCONX) is quarterly.

PCPI, the consumer price index with monthly vintages, is therefore the inflation
series. Its revisions come only from the annual seasonal-factor update, so they are
smaller than PCE revisions.

### Known gaps

- PCPI and RUC have no October 2025 observation. It was never published, because of the
  2025 federal shutdown. That is why each has one fewer observation than EMPLOY and IPT.
- `get_as_of` returns the full column of a vintage, so missing cells stay missing; they
  are never filled from an older vintage.

## Summary statistics

Generated by `python scripts/fetch_data.py --update-checksums` (or `--readme`) from the
local files. This section contains aggregate statistics only, never individual values.

- **Obs. compared:** observations first released after the baseline vintage that are
  present in the pinned last vintage.
- **Mean abs. revision:** |value in the last vintage - value at first release|, in
  series units. The next column gives the same figure as a percent of the
  first-release level.
- **Revision of period % change:** the period-over-period percent change at first
  release (both levels from the first-release vintage) compared with the latest
  change, in percentage points, not annualized. This measure is unaffected by
  base-year changes.
  - Level revisions for ROUTPUT (2012 to 2017 chained dollars, comprehensive update of
    2023) and IPT (index rebased in 2021) are dominated by rebasing. For those series
    the %-change column is the meaningful one.
  - For RUC, a rate, the level column in percentage points is the meaningful one.

<!-- stats:begin -->
| Series | Vintages (pinned range) | Observations | Obs. compared | Mean abs. revision, first release vs latest | Same, % of level | Mean abs. revision of period % change (pp) | Share revised |
|---|---|---|---|---|---|---|---|
| EMPLOY | 130 (EMPLOY15M12 (2015-12-31) to EMPLOY26M9 (2026-09-30)) | 140 (2015-01-01 to 2026-08-01) | 129 | 394.953 thousands of employees | 0.256% | 0.059 | 99% |
| ROUTPUT | 131 (ROUTPUT15M12 (2015-12-15) to ROUTPUT26M10 (2026-10-15)) | 46 (2015-01-01 to 2026-04-01) | 43 | 1584.340 billions of real (chained) dollars | 8.613% | 0.227 | 100% |
| IPT | 130 (IPT15M12 (2015-12-31) to IPT26M9 (2026-09-30)) | 140 (2015-01-01 to 2026-08-01) | 129 | 4.134 index | 3.930% | 0.342 | 97% |
| RUC | 44 (RUC15Q4 (2015-11-15) to RUC26Q3 (2026-08-15)) | 138 (2015-01-01 to 2026-07-01) | 128 | 0.041 percent | 0.936% | 1.370 | 41% |
| PCPI | 130 (PCPI15M12 (2015-12-31) to PCPI26M9 (2026-09-30)) | 139 (2015-01-01 to 2026-08-01) | 128 | 0.180 index (base value 100) | 0.067% | 0.056 | 94% |
<!-- stats:end -->
