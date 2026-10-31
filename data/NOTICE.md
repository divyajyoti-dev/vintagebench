# Data notice

The files in `data/vintages/` hold real-time (vintage) observations of five US economic
series. Data values from these files also appear in `tasks/` (in task questions and
notes), in `runs/` (in tool responses inside the cached model prompts and in
`values_used`), and in `results/PILOT.md`.

The MIT License in [LICENSE](../LICENSE) covers the VintageBench code only. It does not
cover these data. The data remain subject to the terms of FRED®/ALFRED® and of the
original source agencies, described below.

## Series

The copyright status is the FRED® copyright tag of each series, checked through the
FRED® API (`fred/series/tags`) on 2026-10-31. None of the five series mentions a
copyright in its FRED® notes.

| Series | Title | Source agency | FRED® copyright tag |
|---|---|---|---|
| PAYEMS | All Employees, Total Nonfarm | U.S. Bureau of Labor Statistics (Current Employment Statistics) | Public Domain: Citation Requested |
| UNRATE | Unemployment Rate | U.S. Bureau of Labor Statistics (Current Population Survey) | Public Domain: Citation Requested |
| GDPC1 | Real Gross Domestic Product | U.S. Bureau of Economic Analysis | Public Domain: Citation Requested |
| PCEPI | Personal Consumption Expenditures: Chain-type Price Index | U.S. Bureau of Economic Analysis | Public Domain: Citation Requested |
| INDPRO | Industrial Production: Total Index | Board of Governors of the Federal Reserve System (US) | Public Domain: Citation Requested |

Some FRED® series are copyrighted by third parties. Before adding a series, check its
copyright tag and notes.

## Retrieval

- **Source:** ALFRED® (ArchivaL Federal Reserve Economic Data), Federal Reserve Bank of
  St. Louis, https://alfred.stlouisfed.org/, accessed through the FRED® API
  (`fred/series/vintagedates` and `fred/series/observations` with `realtime_start` /
  `realtime_end`) by `scripts/fetch_data.py`.
- **Retrieved:** 2026-10-30 (the date `data/vintages/` was committed; the files have not been refetched since).
- **Coverage:** observations from 2015-01-01. Vintages from the baseline release on or
  before 2016-01-01 through the latest release available at retrieval:

  | Series | First vintage | Last vintage |
  |---|---|---|
  | PAYEMS | 2015-12-04 | 2026-10-02 |
  | UNRATE | 2015-12-04 | 2026-10-02 |
  | GDPC1 | 2015-12-22 | 2026-10-29 |
  | PCEPI | 2015-12-23 | 2026-10-29 |
  | INDPRO | 2015-12-16 | 2026-10-16 |

- **Processing:** stored sparsely, like ALFRED®: one row for an observation's first
  release and one for each later vintage in which its value changed. Missing values
  (".") are dropped. Values are otherwise as published. See [README.md](README.md) for
  the schema and summary statistics.

## FRED® notice and terms

This product uses the FRED® API but is not endorsed or certified by the Federal Reserve
Bank of St. Louis.

Use of these data is subject to the FRED® API Terms of Use,
https://fred.stlouisfed.org/docs/api/terms_of_use.html, and the FRED® terms of use on
the legal page, https://fred.stlouisfed.org/legal. By using the data you agree to those
terms.

Neither the Federal Reserve Bank of St. Louis nor the U.S. Bureau of Labor Statistics,
the U.S. Bureau of Economic Analysis or the Board of Governors of the Federal Reserve
System sponsors, endorses or is affiliated with VintageBench. The data are provided as
retrieved, without warranty of any kind, including as to accuracy, completeness or
timeliness. Later vintages may differ from the ones stored here.

## Open question before public release

**Not yet resolved.** The FRED® API Terms of Use reportedly prohibit using the API "in
connection with storing, caching, or archiving" any portion of FRED® content, and
providing such stored content to third parties. This repository commits API-retrieved
vintages in `data/vintages/*.parquet`, and data values derived from them in `tasks/`
and `runs/`. The wording above comes from secondary sources. It was not verified against
the primary terms page, which could not be reached when this notice was written. Before
the repository is made public, the maintainer should either confirm from the current
FRED® API Terms of Use (or with the Federal Reserve Bank of St. Louis) that publishing
these files is permitted, or obtain the vintages from the original agencies (BLS, BEA
and the Federal Reserve Board), whose data are in the public domain, and publish those
instead of the committed parquet files.

A second clause should be checked at the same time. Secondary sources report that the
FRED® terms (as updated in 2024) restrict use of FRED® content "in connection with the
development or training of any software program or system or machine learning".
VintageBench evaluates models and does not train them, but this has not been confirmed
against the primary terms either.

## Suggested citations

Following FRED®'s citation style (source, title, series ID, "retrieved from", link,
access date), adapted for ALFRED® vintages:

- U.S. Bureau of Labor Statistics, All Employees, Total Nonfarm [PAYEMS], vintages
  2015-12-04 to 2026-10-02, retrieved from ALFRED, Federal Reserve Bank of St. Louis;
  https://alfred.stlouisfed.org/series?seid=PAYEMS, October 30, 2026.
- U.S. Bureau of Labor Statistics, Unemployment Rate [UNRATE], vintages 2015-12-04 to
  2026-10-02, retrieved from ALFRED, Federal Reserve Bank of St. Louis;
  https://alfred.stlouisfed.org/series?seid=UNRATE, October 30, 2026.
- U.S. Bureau of Economic Analysis, Real Gross Domestic Product [GDPC1], vintages
  2015-12-22 to 2026-10-29, retrieved from ALFRED, Federal Reserve Bank of St. Louis;
  https://alfred.stlouisfed.org/series?seid=GDPC1, October 30, 2026.
- U.S. Bureau of Economic Analysis, Personal Consumption Expenditures: Chain-type Price
  Index [PCEPI], vintages 2015-12-23 to 2026-10-29, retrieved from ALFRED, Federal
  Reserve Bank of St. Louis; https://alfred.stlouisfed.org/series?seid=PCEPI,
  October 30, 2026.
- Board of Governors of the Federal Reserve System (US), Industrial Production: Total
  Index [INDPRO], vintages 2015-12-16 to 2026-10-16, retrieved from ALFRED, Federal
  Reserve Bank of St. Louis; https://alfred.stlouisfed.org/series?seid=INDPRO,
  October 30, 2026.

The vintage-range form is an adaptation; ALFRED® publishes no specific citation format.
