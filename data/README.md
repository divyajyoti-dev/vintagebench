# VintageBench data

Real-time (vintage) data for the SPEC §2 series, from ALFRED (ArchivaL Federal Reserve
Economic Data), Federal Reserve Bank of St. Louis: https://alfred.stlouisfed.org/.
Underlying sources: PAYEMS and UNRATE from the U.S. Bureau of Labor Statistics;
GDPC1 and PCEPI from the U.S. Bureau of Economic Analysis; INDPRO from the Board of
Governors of the Federal Reserve System. Retrieved via the FRED API; use is subject to
the FRED terms of use (https://fred.stlouisfed.org/legal/). Some FRED series carry
third-party copyrights; these five are public-domain U.S. government data.

## Files

`vintages/<SERIES>.parquet`, columns:

| Column | Type | Meaning |
|---|---|---|
| series_id | str | FRED series ID |
| observation_date | datetime.date | period the value refers to (first day of month/quarter) |
| vintage_date | datetime.date | ALFRED vintage (release) date on which this value was published |
| value | float64 | value as published in that vintage |

Storage is sparse, like ALFRED: an observation has a row for its first release and one
for each later vintage in which its value changed. The value known on date D is the row
with the latest vintage_date <= D (`vintagebench.data.get_as_of`). Missing values (".")
are dropped. Observations start 2015-01-01. Vintages cover 2016-01-01 onward; the
earliest vintage_date of each series is a baseline (the last release on or before
2016-01-01) holding the data as it stood on 2016-01-01.

## Summary

Generated from the parquet files by `vintagebench.data.write_readme`; do not edit by hand.
"Obs. compared" counts observations first released after the baseline vintage; for
those, the revision is |value in latest vintage - value at first release|. "Vintages"
counts distinct vintage dates in which at least one value from 2015 onward was
released or changed. "Revision of % change" compares the period-over-period percent
change as first published with the latest one (percentage points, not annualized).

Caveat: level revisions for GDPC1, PCEPI and INDPRO are dominated by base-year
changes visible in the vintages (GDPC1/PCEPI: 2009 to 2012 in the 2018-07 vintages and
2012 to 2017 in the 2023-09 vintages; INDPRO: 2012=100 to 2017=100 in the 2021-05-28
vintage), so the %-change column is the better measure of substantive revision for
those series. For UNRATE (a rate) the level revision in percentage points is the
meaningful figure; its %-change column is a relative change of the rate.
UNRATE has no October 2025 observation (not published after the 2025 federal
government shutdown), so it has one fewer observation than the other monthly series.

| Series | Units | Observations | Vintages (first to last) | Obs. compared | Mean abs. revision, first release vs latest | Same, % of level | Mean abs. revision of % change (pp) | Share revised |
|---|---|---|---|---|---|---|---|---|
| PAYEMS | thousands of persons, SA | 141 (2015-01-01 to 2026-09-01) | 131 (2015-12-04 to 2026-10-02) | 130 | 392.138 | 0.254% | 0.058 | 99% |
| GDPC1 | billions of chained dollars, SAAR (base year varies by vintage) | 47 (2015-01-01 to 2026-07-01) | 129 (2015-12-22 to 2026-10-29) | 44 | 1548.326 | 8.417% | 0.222 | 98% |
| PCEPI | index, SA (base year varies by vintage) | 141 (2015-01-01 to 2026-09-01) | 130 (2015-12-23 to 2026-10-29) | 130 | 6.046 | 5.314% | 0.048 | 99% |
| INDPRO | index, SA (base year varies by vintage) | 141 (2015-01-01 to 2026-09-01) | 139 (2015-12-16 to 2026-10-16) | 130 | 4.107 | 3.905% | 0.334 | 99% |
| UNRATE | percent, SA | 140 (2015-01-01 to 2026-09-01) | 131 (2015-12-04 to 2026-10-02) | 129 | 0.041 | 0.951% | 1.316 | 41% |

## Regenerate

```bash
export FRED_API_KEY=...            # free key: https://fred.stlouisfed.org/docs/api/api_key.html
python scripts/fetch_data.py         # fetches only series without a parquet file
python scripts/fetch_data.py --force # refetch everything (data will include newer vintages)
python scripts/fetch_data.py --readme  # rewrite this README from the existing files
```
