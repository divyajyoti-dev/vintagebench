"""ALFRED vintage storage and as-of lookups (SPEC §2, §5).

Vintages live in data/vintages/<SERIES>.parquet with columns
series_id, observation_date, vintage_date, value.

Storage is ALFRED-style and sparse: the first vintage that contains an observation
holds its first release, and later vintages only carry rows whose value changed.

Date convention: ``observation_date`` and ``vintage_date`` are always plain
``datetime.date`` objects (object dtype columns), never pandas Timestamps. The index of
``get_as_of`` is likewise ``datetime.date``, and ``vintage_dates`` returns
``list[datetime.date]``. ``as_of`` arguments may be a ``date``, ``datetime``, Timestamp
or ISO string; they are normalised to ``date``.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

DATA_DIR: Path = Path(__file__).resolve().parents[2] / "data" / "vintages"
COLUMNS = ["series_id", "observation_date", "vintage_date", "value"]


def _to_date(value: object) -> date:
    return pd.Timestamp(value).date()


def _path(series_id: str, root: Path | str) -> Path:
    return Path(root) / f"{series_id}.parquet"


def load_vintages(series_id: str, root: Path = DATA_DIR) -> pd.DataFrame:
    """Load all vintages for a series.

    Returns a DataFrame with columns series_id (str), observation_date (datetime.date),
    vintage_date (datetime.date), value (float64), sorted by observation_date then
    vintage_date. Raises FileNotFoundError if the series has not been fetched.
    """
    path = _path(series_id, root)
    if not path.exists():
        raise FileNotFoundError(f"no vintages for {series_id!r} at {path}")
    df = pd.read_parquet(path, columns=COLUMNS)
    df["series_id"] = df["series_id"].astype(str)
    for col in ("observation_date", "vintage_date"):
        df[col] = df[col].map(_to_date).astype(object)
    df["value"] = df["value"].astype("float64")
    return df.sort_values(["observation_date", "vintage_date"], ignore_index=True)


def vintage_dates(series_id: str, root: Path = DATA_DIR) -> list[date]:
    """Return the sorted, distinct vintage dates (datetime.date) available for a series."""
    return sorted(set(load_vintages(series_id, root)["vintage_date"]))


def get_as_of(series_id: str, as_of: date, root: Path = DATA_DIR) -> pd.Series:
    """Return the series as it was known on ``as_of``.

    For each observation, the value from the latest vintage with
    vintage_date <= as_of. Indexed by observation_date (datetime.date, ascending,
    index name "observation_date"); the Series is named ``series_id``. Never returns
    values from vintages after ``as_of``; observations first released after ``as_of``
    are absent. Returns an empty Series if nothing had been released by ``as_of``.
    """
    cutoff = _to_date(as_of)
    df = load_vintages(series_id, root)
    known = df[df["vintage_date"] <= cutoff]
    latest = known.groupby("observation_date", sort=True)["value"].last()
    latest.index = pd.Index(list(latest.index), dtype=object, name="observation_date")
    return latest.astype("float64").rename(series_id)


# --- Summary statistics for data/README.md (SPEC §2) ---------------------------------

UNITS = {
    "PAYEMS": "thousands of persons, SA",
    "GDPC1": "billions of chained dollars, SAAR (base year varies by vintage)",
    "PCEPI": "index, SA (base year varies by vintage)",
    "INDPRO": "index, SA (base year varies by vintage)",
    "UNRATE": "percent, SA",
}


def revision_summary(series_id: str, root: Path = DATA_DIR) -> dict[str, object]:
    """Per-series stats: vintage count and first-release-vs-latest revisions.

    Revisions are computed only for observations first released after the baseline
    (earliest) vintage, so that "first" really is the first release. Absolute revision
    is in the series' units; the percent figure is |latest - first| / |first| * 100.
    ``mean_abs_change_revision_pp`` compares the period-over-period % change as first
    published (both levels from the first-release vintage) with the latest % change;
    unlike level revisions it is unaffected by base-year rebasings.
    """
    df = load_vintages(series_id, root)
    baseline = df["vintage_date"].min()
    grouped = df.groupby("observation_date")
    first, latest = grouped.first(), grouped.last()
    released = first.index[first["vintage_date"] > baseline]
    first_v, latest_v = first.loc[released, "value"], latest.loc[released, "value"]
    abs_rev = (latest_v - first_v).abs()
    change_rev = _first_release_change(df, released) - latest["value"].pct_change() * 100
    change_rev = change_rev.loc[released].abs()
    return {
        "series_id": series_id,
        "observations": int(df["observation_date"].nunique()),
        "obs_range": f"{df['observation_date'].min()} to {df['observation_date'].max()}",
        "vintages": int(df["vintage_date"].nunique()),
        "vintage_range": f"{baseline} to {df['vintage_date'].max()}",
        "rows": len(df),
        "n_revised_obs": len(released),
        "mean_abs_revision": float(abs_rev.mean()),
        "mean_abs_revision_pct": float((abs_rev / first_v.abs()).mean() * 100),
        "share_revised": float((abs_rev > 0).mean()),
        "mean_abs_change_revision_pp": float(change_rev.mean()),
    }


def _first_release_change(df: pd.DataFrame, released: pd.Index) -> pd.Series:
    """% change vs the previous observation, both as known at the first release."""
    out = {}
    for obs in released:
        vintage = df.loc[df["observation_date"] == obs, "vintage_date"].min()
        known = df[df["vintage_date"] <= vintage].groupby("observation_date")["value"].last()
        pos = known.index.get_loc(obs)
        if pos > 0:
            out[obs] = (known.iloc[pos] / known.iloc[pos - 1] - 1) * 100
    return pd.Series(out, dtype="float64")


def readme_table(series_ids: list[str], root: Path = DATA_DIR) -> str:
    """Markdown table of revision_summary for each series that has a parquet file."""
    lines = [
        "| Series | Units | Observations | Vintages (first to last) | Obs. compared "
        "| Mean abs. revision, first release vs latest | Same, % of level "
        "| Mean abs. revision of % change (pp) | Share revised |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for sid in series_ids:
        if not _path(sid, root).exists():
            continue
        s = revision_summary(sid, root)
        lines.append(
            f"| {sid} | {UNITS.get(sid, '')} | {s['observations']} ({s['obs_range']}) "
            f"| {s['vintages']} ({s['vintage_range']}) | {s['n_revised_obs']} "
            f"| {s['mean_abs_revision']:.3f} | {s['mean_abs_revision_pct']:.3f}% "
            f"| {s['mean_abs_change_revision_pp']:.3f} | {s['share_revised']:.0%} |"
        )
    return "\n".join(lines)


def write_readme(series_ids: list[str], root: Path = DATA_DIR) -> Path:
    """Regenerate data/README.md (one level above ``root``) from the parquet files."""
    path = Path(root).parent / "README.md"
    path.write_text(README_TEMPLATE.format(table=readme_table(series_ids, root)))
    return path


README_TEMPLATE = """# VintageBench data

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

{table}

## Regenerate

```bash
export FRED_API_KEY=...            # free key: https://fred.stlouisfed.org/docs/api/api_key.html
python scripts/fetch_data.py         # fetches only series without a parquet file
python scripts/fetch_data.py --force # refetch everything (data will include newer vintages)
python scripts/fetch_data.py --readme  # rewrite this README from the existing files
```
"""
