"""Fetch ALFRED vintages for the SPEC §2 series into data/vintages/<SERIES>.parquet.

Usage (from repo root, FRED_API_KEY in env):
    python scripts/fetch_data.py [--series PAYEMS ...] [--force] [--readme]

API semantics used (FRED/ALFRED API, https://fred.stlouisfed.org/docs/api/fred/):
- series/vintagedates returns the dates on which a series was released or revised
  (default/max limit 10000 per request; we page with offset anyway).
- series/observations with output_type=1 ("observations by real-time period") returns
  one row per (observation date, value) with the realtime_start/realtime_end period
  during which that value was current. Periods are clipped to the requested real-time
  window, and a new row only appears when the value changes, so realtime_start is the
  vintage that first published that value. This is exactly ALFRED's sparse layout.
  Observations default to limit=100000 rows per request; we page with offset.
- Missing values are the string "." and are dropped.

Baseline vintage: SPEC wants vintages from 2016-01-01 onward. To make get_as_of
correct on 2016-01-01 itself, the real-time window starts at the last vintage on or
before 2016-01-01 (e.g. PAYEMS 2015-12-04), so each series has one baseline vintage
holding the data as it stood on 2016-01-01, followed by every vintage in 2016+.

The real-time window is fetched in chunks of --chunk vintage dates (the API caps
vintage-date lists for some output types at 2000; chunking keeps every request small).
A value that spans chunks reappears at the chunk start and is de-duplicated.

The API key is read from FRED_API_KEY and is never printed; it is redacted from errors.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vintagebench.data import COLUMNS, DATA_DIR, write_readme  # noqa: E402

API = "https://api.stlouisfed.org/fred/"
SERIES = ["PAYEMS", "GDPC1", "PCEPI", "INDPRO", "UNRATE"]
OBS_START = "2015-01-01"
VINTAGE_START = date(2016, 1, 1)
REALTIME_END = "9999-12-31"
CHUNK = 500
RETRIES = 4


class FredError(RuntimeError):
    """API failure with the key redacted from the message."""


def _redact(text: str, key: str) -> str:
    return text.replace(key, "***") if key else text


def _get(session: requests.Session, endpoint: str, key: str, **params: object) -> dict:
    query = {**params, "api_key": key, "file_type": "json"}
    last = ""
    for attempt in range(RETRIES):
        try:
            resp = session.get(API + endpoint, params=query, timeout=60)
        except requests.RequestException as exc:
            last = _redact(f"{type(exc).__name__}: {exc}", key)
        else:
            if resp.status_code == 200:
                return resp.json()
            last = _redact(f"HTTP {resp.status_code} on {endpoint}: {resp.text[:300]}", key)
            if resp.status_code not in (429, 500, 502, 503, 504):
                break
        time.sleep(2**attempt)
    raise FredError(last)


def _paged(
    session: requests.Session, endpoint: str, field: str, key: str, **params: object
) -> Iterator[dict | str]:
    offset = 0
    while True:
        payload = _get(session, endpoint, key, offset=offset, **params)
        items = payload[field]
        yield from items
        offset += len(items)
        if not items or offset >= int(payload["count"]):
            return


def fetch_vintage_dates(session: requests.Session, series_id: str, key: str) -> list[date]:
    """All vintages from the baseline (last on/before VINTAGE_START) onward, ascending."""
    start = date(VINTAGE_START.year - 1, 1, 1).isoformat()
    raw = _paged(
        session, "series/vintagedates", "vintage_dates", key,
        series_id=series_id, realtime_start=start, realtime_end=REALTIME_END,
    )  # fmt: skip
    dates = sorted(date.fromisoformat(str(d)) for d in raw)
    baseline = [d for d in dates if d <= VINTAGE_START]
    if not baseline:
        raise FredError(f"{series_id}: no vintage on or before {VINTAGE_START}")
    return [baseline[-1]] + [d for d in dates if d > VINTAGE_START]


def _windows(vintages: list[date], chunk: int) -> Iterator[tuple[str, str]]:
    for i in range(0, len(vintages), chunk):
        start = vintages[i]
        nxt = i + chunk
        end = (
            (pd.Timestamp(vintages[nxt]) - pd.Timedelta(days=1)).date().isoformat()
            if nxt < len(vintages)
            else REALTIME_END
        )
        yield start.isoformat(), end


def to_sparse(rows: list[dict], series_id: str) -> pd.DataFrame:
    """Turn output_type=1 rows into sparse (first-publication) vintage rows."""
    df = pd.DataFrame(rows, columns=["realtime_start", "date", "value"])
    df = df[df["value"] != "."]
    out = pd.DataFrame(
        {
            "series_id": series_id,
            "observation_date": pd.to_datetime(df["date"]).dt.date,
            "vintage_date": pd.to_datetime(df["realtime_start"]).dt.date,
            "value": df["value"].astype("float64"),
        }
    )
    out = out.drop_duplicates(["observation_date", "vintage_date"], keep="last")
    out = out.sort_values(["observation_date", "vintage_date"], ignore_index=True)
    same = out["value"].eq(out.groupby("observation_date")["value"].shift())
    return out.loc[~same, COLUMNS].reset_index(drop=True)


def fetch_series(
    session: requests.Session, series_id: str, key: str, chunk: int = CHUNK
) -> pd.DataFrame:
    vintages = fetch_vintage_dates(session, series_id, key)
    rows: list[dict] = []
    for start, end in _windows(vintages, chunk):
        rows.extend(
            _paged(
                session,
                "series/observations",
                "observations",
                key,
                series_id=series_id,
                observation_start=OBS_START,
                realtime_start=start,
                realtime_end=end,
                output_type=1,
            )  # fmt: skip
        )
    return to_sparse(rows, series_id)


def _fetch_all(series_ids: list[str], key: str, out: Path, chunk: int) -> int:
    with requests.Session() as session:
        for series_id in series_ids:
            try:
                df = fetch_series(session, series_id, key, chunk)
            except FredError as exc:
                print(f"{series_id}: fetch failed: {exc}", file=sys.stderr)
                return 1
            path = out / f"{series_id}.parquet"
            df.to_parquet(path, index=False)
            n_vint = df["vintage_date"].nunique()
            print(f"{series_id}: {len(df)} rows, {n_vint} vintages -> {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--series", nargs="+", default=SERIES)
    parser.add_argument("--force", action="store_true", help="refetch existing files")
    parser.add_argument("--out", type=Path, default=DATA_DIR)
    parser.add_argument("--chunk", type=int, default=CHUNK, help="vintages per request")
    parser.add_argument("--readme", action="store_true", help="only rewrite data/README.md")
    args = parser.parse_args(argv)

    if not args.readme:
        todo = [s for s in args.series if args.force or not (args.out / f"{s}.parquet").exists()]
        key = os.environ.get("FRED_API_KEY", "") if todo else ""
        if todo and not key:
            print("FRED_API_KEY is not set", file=sys.stderr)
            return 1
        args.out.mkdir(parents=True, exist_ok=True)
        for series_id in sorted(set(args.series) - set(todo)):
            print(f"{series_id}: cached in {args.out} (use --force to refetch)")
        if todo and _fetch_all(todo, key, args.out, args.chunk) != 0:
            return 1
    if args.out == DATA_DIR:
        write_readme(SERIES, DATA_DIR)
        print(f"wrote {DATA_DIR.parent / 'README.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
