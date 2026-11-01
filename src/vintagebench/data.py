"""RTDSM vintage storage, parsing and as-of lookups (SPEC §2).

Source: Federal Reserve Bank of Philadelphia, Real-Time Data Set for Macroeconomists
(RTDSM). Raw data are NOT redistributed (data/NOTICE.md): ``scripts/fetch_data.py``
downloads the xlsx workbooks into ``data/raw/`` (gitignored), parses them with
:func:`parse_workbook` and caches one parquet file per series there.

Long-table schema (``load_vintages``):

| column           | type          | meaning                                          |
|------------------|---------------|--------------------------------------------------|
| series_id        | str           | RTDSM variable (EMPLOY, ROUTPUT, IPT, RUC, PCPI)  |
| observation_date | datetime.date | first day of the observed month/quarter          |
| vintage          | str           | RTDSM column label, e.g. "EMPLOY18M11"            |
| vintage_date     | datetime.date | date the vintage is treated as known (see below)  |
| value            | float64       | value as published in that vintage               |

Storage is dense: every vintage (column) holds its full time-series history, so the
data known on date D is the whole column of the latest vintage with vintage_date <= D
(:func:`get_as_of`). Missing cells ("#N/A") are dropped.

Vintage dates. RTDSM labels name only the vintage month (or quarter). Each label is
mapped to a calendar date that is on or after the publication of every value in that
vintage, so serving the vintage on its vintage_date never leaks later data. Rules
(quotes and checks in data/README.md):

- ROUTPUT (monthly vintages of quarterly data): the 15th of the vintage month. RTDSM:
  "Monthly vintages reflect the data available in the middle of the month."
- RUC (quarterly vintages): the 15th of the middle month of the quarter. RTDSM: "we do
  not incorporate the data of any release published after the 15th".
- EMPLOY, IPT, PCPI (monthly vintages): the last calendar day of the vintage month.
  RTDSM gives no fixed day ("depends on the day that the data are released"), and in
  2025 a CPI release on the 24th appears in that month's vintage, so a fixed mid-month
  day would leak; month-end is the conservative choice.

Date convention: ``observation_date`` and ``vintage_date`` are ``datetime.date``
(object dtype), never Timestamps; ``as_of`` arguments may be a date, datetime,
Timestamp or ISO string and are normalised to ``date``.
"""

from __future__ import annotations

import calendar
import hashlib
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
RAW_DIR: Path = REPO_ROOT / "data" / "raw"
DATA_DIR: Path = RAW_DIR  # backwards-compatible alias used by tasks/run/episode
MANIFEST_PATH: Path = REPO_ROOT / "data" / "manifest.json"
CHECKSUMS_PATH: Path = REPO_ROOT / "data" / "checksums.json"

COLUMNS = ["series_id", "observation_date", "vintage", "vintage_date", "value"]
OBS_START = date(2015, 1, 1)
VINTAGE_START = date(2016, 1, 1)
BASE_URL = (
    "https://www.philadelphiafed.org/-/media/FRBP/Assets/Surveys-And-Data/"
    "real-time-data/data-files/xlsx/"
)
FETCH_HINT = "Run `python scripts/fetch_data.py` to download the RTDSM files (data/NOTICE.md)."


@dataclass(frozen=True)
class SeriesInfo:
    """Metadata for one RTDSM variable. ``decimals`` is the publication precision."""

    series_id: str
    title: str
    units: str
    frequency: str  # observation frequency: "monthly" | "quarterly"
    vintage_frequency: str  # "monthly" | "quarterly"
    vintage_rule: str  # "month_end" | "mid_month" | "mid_quarter"
    file: str
    decimals: int
    agency: str

    @property
    def rounding_unit(self) -> float:
        """Smallest published increment (e.g. 0.1 for RUC)."""
        return 10.0**-self.decimals

    @property
    def tolerance(self) -> float:
        """Half a publication unit: matching tolerance for reported values."""
        return 0.5 * self.rounding_unit

    @property
    def url(self) -> str:
        return BASE_URL + self.file


SERIES: dict[str, SeriesInfo] = {
    s.series_id: s
    for s in (
        SeriesInfo(
            "EMPLOY", "Nonfarm payroll employment", "thousands of employees, SA",
            "monthly", "monthly", "month_end", "employMvMd.xlsx", 0,
            "U.S. Bureau of Labor Statistics",
        ),
        SeriesInfo(
            "ROUTPUT", "Real GDP", "billions of real (chained) dollars, SAAR; base year "
            "varies by vintage", "quarterly", "monthly", "mid_month", "routputMvQd.xlsx", 1,
            "U.S. Bureau of Economic Analysis",
        ),
        SeriesInfo(
            "IPT", "Industrial production index, total", "index, SA; base period varies "
            "by vintage", "monthly", "monthly", "month_end", "iptMvMd.xlsx", 1,
            "Board of Governors of the Federal Reserve System",
        ),
        SeriesInfo(
            "RUC", "Civilian unemployment rate", "percent, SA", "monthly", "quarterly",
            "mid_quarter", "rucQvMd.xlsx", 1, "U.S. Bureau of Labor Statistics",
        ),
        SeriesInfo(
            "PCPI", "Consumer price index (headline)", "index (base value 100), SA",
            "monthly", "monthly", "month_end", "pcpiMvMd.xlsx", 3,
            "U.S. Bureau of Labor Statistics",
        ),
    )
}  # fmt: skip
SERIES_IDS: tuple[str, ...] = tuple(SERIES)

_LABEL = re.compile(r"^([A-Z]+)(\d{2})([MQ])(\d{1,2})$")
_OBS = re.compile(r"^(\d{4}):(Q?)(\d{1,2})$")


class DataNotFetchedError(FileNotFoundError):
    """data/raw (or a series file in it) is missing."""


def _to_date(value: object) -> date:
    return pd.Timestamp(value).date()


# --- labels and dates -----------------------------------------------------------------


def parse_observation(label: str) -> date:
    """'2018:01' -> 2018-01-01; '2018:Q1' -> 2018-01-01 (first day of the period)."""
    m = _OBS.match(str(label).strip())
    if not m:
        raise ValueError(f"unrecognised RTDSM observation date {label!r}")
    year, quarterly, num = int(m[1]), bool(m[2]), int(m[3])
    if quarterly:
        if not 1 <= num <= 4:
            raise ValueError(f"bad quarter in {label!r}")
        return date(year, 3 * num - 2, 1)
    if not 1 <= num <= 12:
        raise ValueError(f"bad month in {label!r}")
    return date(year, num, 1)


def vintage_date(label: str, rule: str) -> date:
    """Map an RTDSM vintage label (e.g. 'EMPLOY18M11', 'RUC18Q4') to its vintage_date.

    Two-digit years >= 60 are 19xx (RTDSM starts in the 1960s), else 20xx.
    Rules: "month_end" (last day of the vintage month), "mid_month" (15th of the
    vintage month), "mid_quarter" (15th of the quarter's middle month).
    """
    m = _LABEL.match(label.strip())
    if not m:
        raise ValueError(f"unrecognised RTDSM vintage label {label!r}")
    yy, kind, num = int(m[2]), m[3], int(m[4])
    year = 1900 + yy if yy >= 60 else 2000 + yy
    if kind == "Q":
        if rule != "mid_quarter" or not 1 <= num <= 4:
            raise ValueError(f"{label!r}: quarterly label needs rule mid_quarter")
        return date(year, 3 * num - 1, 15)
    if not 1 <= num <= 12:
        raise ValueError(f"bad month in {label!r}")
    if rule == "month_end":
        return date(year, num, calendar.monthrange(year, num)[1])
    if rule == "mid_month":
        return date(year, num, 15)
    raise ValueError(f"{label!r}: monthly label cannot use rule {rule!r}")


# --- parsing the RTDSM workbook ---------------------------------------------------------


def _read_rows(path: Path) -> list[tuple]:
    """All rows of the first worksheet (values only)."""
    from openpyxl.reader.excel import ExcelReader

    class _Reader(ExcelReader):
        def read_properties(self) -> None:
            # Some RTDSM workbooks carry malformed docProps dates that openpyxl rejects;
            # document properties are irrelevant to the data.
            try:
                super().read_properties()
            except (TypeError, ValueError):
                pass

    reader = _Reader(str(path), read_only=True, data_only=True)
    reader.read()
    wb = reader.wb
    try:
        return list(wb.worksheets[0].iter_rows(values_only=True))
    finally:
        wb.close()


def wide_to_long(rows: list[tuple], series_id: str, rule: str | None = None) -> pd.DataFrame:
    """Convert RTDSM wide rows (header DATE, <SERIES>yyMmm...) to the long schema.

    Non-numeric cells (e.g. '#N/A') and empty cells are dropped. No range filtering.
    """
    if not rows or str(rows[0][0]).strip().upper() != "DATE":
        raise ValueError(f"{series_id}: first header cell must be DATE")
    rule = rule or SERIES[series_id].vintage_rule
    labels = [str(h).strip() for h in rows[0][1:]]
    for lab in labels:
        m = _LABEL.match(lab)
        if not m or m[1] != series_id:
            raise ValueError(f"{series_id}: unexpected vintage column {lab!r}")
    vdates = [vintage_date(lab, rule) for lab in labels]
    out: list[tuple] = []
    for row in rows[1:]:
        if row[0] is None or str(row[0]).strip() == "":
            continue
        obs = parse_observation(str(row[0]))
        for lab, vd, cell in zip(labels, vdates, row[1:], strict=False):
            if isinstance(cell, bool) or not isinstance(cell, int | float):
                continue
            if cell != cell:  # NaN
                continue
            out.append((series_id, obs, lab, vd, float(cell)))
    df = pd.DataFrame(out, columns=COLUMNS)
    df["value"] = df["value"].astype("float64")
    return _sorted(df)


def parse_workbook(path: Path | str, series_id: str) -> pd.DataFrame:
    """Parse an RTDSM xlsx (e.g. employMvMd.xlsx) into the long schema (all vintages)."""
    return wide_to_long(_read_rows(Path(path)), series_id)


def _sorted(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values(["vintage_date", "observation_date"], ignore_index=True)


def baseline_vintage_date(vdates: list[date], start: date = VINTAGE_START) -> date:
    """Latest vintage date on or before ``start`` (the as-of-start baseline)."""
    before = [d for d in vdates if d <= start]
    if not before:
        raise ValueError(f"no vintage on or before {start}")
    return max(before)


def restrict(
    df: pd.DataFrame,
    last_vintage: str | None = None,
    obs_start: date = OBS_START,
    vintage_start: date = VINTAGE_START,
) -> pd.DataFrame:
    """Keep observations >= obs_start and vintages from the baseline (latest on or
    before vintage_start) up to and including ``last_vintage`` (label; None = all)."""
    vdates = sorted(set(df["vintage_date"]))
    lo = baseline_vintage_date(vdates, vintage_start)
    keep = (df["vintage_date"] >= lo) & (df["observation_date"] >= obs_start)
    if last_vintage is not None:
        hits = df.loc[df["vintage"] == last_vintage, "vintage_date"]
        if hits.empty:
            raise ValueError(f"pinned vintage {last_vintage!r} not in the file")
        keep &= df["vintage_date"] <= hits.iloc[0]
    return _sorted(df.loc[keep, COLUMNS])


# --- canonical checksum -----------------------------------------------------------------


def canonical_sha256(df: pd.DataFrame) -> str:
    """SHA-256 of the long table in a canonical text form.

    Rows sorted by (vintage_date, observation_date); one line per row:
    ``series_id,observation_date,vintage,vintage_date,value`` with value formatted
    ``%.6f``. Independent of row order, dtypes and parquet/xlsx encoding.
    """
    d = df[COLUMNS].copy()
    d["observation_date"] = d["observation_date"].map(lambda x: _to_date(x).isoformat())
    d["vintage_date"] = d["vintage_date"].map(lambda x: _to_date(x).isoformat())
    d = d.sort_values(["vintage_date", "observation_date", "vintage"], ignore_index=True)
    h = hashlib.sha256()
    for row in d.itertuples(index=False):
        h.update(
            f"{row.series_id},{row.observation_date},{row.vintage},{row.vintage_date},"
            f"{row.value:.6f}\n".encode()
        )
    return h.hexdigest()


# --- loading and as-of lookups ----------------------------------------------------------


def _path(series_id: str, root: Path | str) -> Path:
    return Path(root) / f"{series_id}.parquet"


def _densify(df: pd.DataFrame) -> pd.DataFrame:
    """Expand a legacy sparse table (no ``vintage`` column; later vintages carry only
    changed rows) to dense full columns by carrying values forward."""
    df = df.sort_values(["observation_date", "vintage_date"])
    rows = []
    for vd in sorted(set(df["vintage_date"])):
        known = df[df["vintage_date"] <= vd].groupby("observation_date")["value"].last()
        sid = str(df["series_id"].iloc[0])
        rows += [(sid, obs, vd.isoformat(), vd, v) for obs, v in known.items()]
    return pd.DataFrame(rows, columns=COLUMNS)


def load_vintages(series_id: str, root: Path | str = RAW_DIR) -> pd.DataFrame:
    """Load all (pinned) vintages for a series as the long table in the module docstring,
    sorted by vintage_date then observation_date.

    Raises :class:`DataNotFetchedError` (a FileNotFoundError) with instructions if the
    parquet file is missing. Tables written by scripts/fetch_data.py are already
    restricted to the pinned vintage range. Legacy 4-column sparse tables (test
    fixtures) are densified.
    """
    path = _path(series_id, root)
    if not path.exists():
        where = "data/raw is missing" if not Path(root).exists() else f"{path} not found"
        raise DataNotFetchedError(f"no vintages for {series_id!r}: {where}. {FETCH_HINT}")
    df = pd.read_parquet(path)
    df["series_id"] = df["series_id"].astype(str)
    for col in ("observation_date", "vintage_date"):
        df[col] = df[col].map(_to_date).astype(object)
    df["value"] = df["value"].astype("float64")
    if "vintage" not in df.columns:
        df = _densify(df)
    df["vintage"] = df["vintage"].astype(str)
    return _sorted(df[COLUMNS])


def vintage_dates(series_id: str, root: Path | str = RAW_DIR) -> list[date]:
    """Sorted distinct vintage dates (datetime.date) in the pinned range."""
    return sorted(set(load_vintages(series_id, root)["vintage_date"]))


def vintage_labels(series_id: str, root: Path | str = RAW_DIR) -> dict[date, str]:
    """vintage_date -> RTDSM label (e.g. date(2018, 11, 30) -> 'EMPLOY18M11')."""
    df = load_vintages(series_id, root)
    return dict(zip(df["vintage_date"], df["vintage"], strict=True))


def _column(df: pd.DataFrame, vd: date, series_id: str) -> pd.Series:
    col = df[df["vintage_date"] == vd].sort_values("observation_date")
    out = pd.Series(
        col["value"].to_numpy(dtype="float64"),
        index=pd.Index(list(col["observation_date"]), dtype=object, name="observation_date"),
        name=series_id,
    )
    return out


def get_as_of(series_id: str, as_of: object, root: Path | str = RAW_DIR) -> pd.Series:
    """The series as known on ``as_of``: the full column of the latest vintage with
    vintage_date <= as_of.

    Indexed by observation_date (datetime.date, ascending, name "observation_date"),
    named ``series_id``, float64. Never uses a vintage dated after ``as_of``. Returns
    an empty Series if ``as_of`` precedes the first vintage.
    """
    cutoff = _to_date(as_of)
    df = load_vintages(series_id, root)
    known = [d for d in set(df["vintage_date"]) if d <= cutoff]
    if not known:
        empty = pd.Index([], dtype=object, name="observation_date")
        return pd.Series([], index=empty, dtype="float64", name=series_id)
    return _column(df, max(known), series_id)


def first_release(series_id: str, obs: object, root: Path | str = RAW_DIR) -> tuple[float, date]:
    """(value, vintage_date) from the earliest pinned vintage containing ``obs``.

    Caveat: for observations already published in the baseline vintage (e.g. 2015
    months), this is the baseline value, not the true first release; see
    :func:`is_first_release_in_range`. Raises KeyError if ``obs`` is never published.
    """
    d = _to_date(obs)
    df = load_vintages(series_id, root)
    rows = df[df["observation_date"] == d]
    if rows.empty:
        raise KeyError(f"{series_id}: no value for {d} in any vintage")
    first = rows.iloc[0]  # sorted by vintage_date
    return float(first["value"]), first["vintage_date"]


def is_first_release_in_range(series_id: str, obs: object, root: Path | str = RAW_DIR) -> bool:
    """True if ``obs`` first appears after the baseline vintage (a genuine first release)."""
    _, vd = first_release(series_id, obs, root)
    return vd > vintage_dates(series_id, root)[0]


def latest_value(series_id: str, obs: object, root: Path | str = RAW_DIR) -> float:
    """Value of ``obs`` in the latest pinned vintage. KeyError if missing there."""
    d = _to_date(obs)
    df = load_vintages(series_id, root)
    latest = _column(df, max(df["vintage_date"]), series_id)
    if d not in latest.index:
        raise KeyError(f"{series_id}: no value for {d} in the latest vintage")
    return float(latest[d])


# --- aggregate statistics for data/README.md --------------------------------------------


def revision_summary(series_id: str, root: Path | str = RAW_DIR) -> dict[str, object]:
    """Aggregate revision statistics (no individual values).

    Only observations first released after the baseline vintage and present in the
    latest vintage are compared. ``mean_abs_revision`` is |latest - first| in series
    units; ``mean_abs_revision_pct`` is that relative to |first| (percent);
    ``mean_abs_change_revision_pp`` compares the period-over-period percent change at
    first release (both levels from the first-release vintage) with the latest one,
    which is unaffected by base-year changes.
    """
    df = load_vintages(series_id, root)
    vds = sorted(set(df["vintage_date"]))
    baseline, last = vds[0], vds[-1]
    latest = _column(df, last, series_id)
    by_obs = df.groupby("observation_date")
    first_vd = by_obs["vintage_date"].min()
    first_val = by_obs["value"].first()
    released = [o for o in first_vd.index if first_vd[o] > baseline and o in latest.index]
    abs_rev = pd.Series({o: abs(latest[o] - first_val[o]) for o in released}, dtype="float64")
    pct_rev = pd.Series(
        {o: abs(latest[o] - first_val[o]) / abs(first_val[o]) * 100 for o in released},
        dtype="float64",
    )
    latest_chg = latest.pct_change() * 100
    chg_rev = {}
    for o in released:
        col = _column(df, first_vd[o], series_id)
        pos = col.index.get_loc(o)
        if pos > 0 and o in latest_chg.index:
            first_chg = (col.iloc[pos] / col.iloc[pos - 1] - 1) * 100
            if latest_chg[o] == latest_chg[o]:
                chg_rev[o] = abs(first_chg - latest_chg[o])
    labels = df.drop_duplicates("vintage_date")
    return {
        "series_id": series_id,
        "vintages": len(vds),
        "first_vintage": f"{labels['vintage'].iloc[0]} ({baseline})",
        "last_vintage": f"{labels['vintage'].iloc[-1]} ({last})",
        "observations": int(df["observation_date"].nunique()),
        "obs_range": f"{df['observation_date'].min()} to {df['observation_date'].max()}",
        "rows": len(df),
        "n_compared": len(released),
        "mean_abs_revision": float(abs_rev.mean()) if len(abs_rev) else float("nan"),
        "mean_abs_revision_pct": float(pct_rev.mean()) if len(pct_rev) else float("nan"),
        "share_revised": float((abs_rev > 0).mean()) if len(abs_rev) else float("nan"),
        "mean_abs_change_revision_pp": (
            float(pd.Series(chg_rev).mean()) if chg_rev else float("nan")
        ),
    }
