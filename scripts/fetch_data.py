"""Download and verify the RTDSM vintages used by VintageBench (SPEC §2.2).

Usage (from the repo root):
    python scripts/fetch_data.py                    # download missing files, verify, cache
    python scripts/fetch_data.py --verify-only      # no network: verify data/raw only
    python scripts/fetch_data.py --refresh          # re-download even if files exist
    python scripts/fetch_data.py --update-checksums # maintainer: pin = latest vintage today

Source: Federal Reserve Bank of Philadelphia, Real-Time Data Set for Macroeconomists.
The data are not redistributed with VintageBench (data/NOTICE.md); this script fetches
the five workbooks into data/raw/ (gitignored), sequentially, with a timeout, a few
retries and a User-Agent identifying the project. Existing files are not re-downloaded,
so reruns make no requests.

Each workbook is parsed to the long table of vintagebench.data (observations from
2015-01-01; vintages from the baseline, i.e. the latest vintage on or before
2016-01-01, up to the pinned last vintage in data/manifest.json) and cached as
data/raw/<SERIES>.parquet. Verification compares the canonical content SHA-256 of that
table (vintagebench.data.canonical_sha256) with data/checksums.json. Because only the
pinned vintages are hashed, the check is unaffected by RTDSM appending new monthly
columns; it fails if any pinned value changed. The SHA-256 of the file as downloaded
on the pin date is recorded for information only (it changes every month).

No API key is needed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vintagebench import data  # noqa: E402

USER_AGENT = (
    "VintageBench/1.0 (non-commercial research benchmark; "
    "https://github.com/divyajyoti-dev/vintagebench)"
)
TIMEOUT = 120
RETRIES = 3
PAUSE = 3.0  # seconds between requests (polite, sequential)
STATS_BEGIN, STATS_END = "<!-- stats:begin -->", "<!-- stats:end -->"


# Known first-publication dates, used to check that no vintage_date precedes the
# publication of a value in its vintage (check_known_releases). Sources:
#   rtdsm: RTDSM "Documentation for first-, second-, and third-release values" (last
#          updated 2026-05-21), shutdown sections; fetched 2026-11-01.
#   bea / bls: the agencies' published release schedules (news-release dates). These
#          were NOT re-fetched: bea.gov/bls.gov are blocked from the build sandbox, so
#          they are entered from the published schedules and should be re-verified.
#          Normal-schedule dates only need to be right to within about two weeks (the
#          vintage containing them is dated the 15th of the following month); the
#          shutdown-affected dates are the ones that matter.
# ROUTPUT: first (advance/initial) estimate of each quarter.
_ROUTPUT_FIRST = {
    "2015-10": "2016-01-29", "2016-01": "2016-04-28", "2016-04": "2016-07-29",
    "2016-07": "2016-10-28", "2016-10": "2017-01-27", "2017-01": "2017-04-28",
    "2017-04": "2017-07-28", "2017-07": "2017-10-27", "2017-10": "2018-01-26",
    "2018-01": "2018-04-27", "2018-04": "2018-07-27", "2018-07": "2018-10-26",
    "2018-10": "2019-02-28",  # rtdsm: delayed by the 2018-19 shutdown
    "2019-01": "2019-04-26", "2019-04": "2019-07-26", "2019-07": "2019-10-30",
    "2019-10": "2020-01-30", "2020-01": "2020-04-29", "2020-04": "2020-07-30",
    "2020-07": "2020-10-29", "2020-10": "2021-01-28", "2021-01": "2021-04-29",
    "2021-04": "2021-07-29", "2021-07": "2021-10-28", "2021-10": "2022-01-27",
    "2022-01": "2022-04-28", "2022-04": "2022-07-28", "2022-07": "2022-10-27",
    "2022-10": "2023-01-26", "2023-01": "2023-04-27", "2023-04": "2023-07-27",
    "2023-07": "2023-10-26", "2023-10": "2024-01-25", "2024-01": "2024-04-25",
    "2024-04": "2024-07-25", "2024-07": "2024-10-30", "2024-10": "2025-01-30",
    "2025-01": "2025-04-30", "2025-04": "2025-07-30",
    "2025-07": "2025-12-23",  # bea: no advance estimate; delayed by the 2025 shutdown
    "2025-10": "2026-02-20",  # bea: delayed (post-shutdown schedule)
    "2026-01": "2026-04-30",  # rtdsm: "the 2026 Q1 observation on April 30, 2026"
}  # fmt: skip
KNOWN_RELEASES: dict[str, dict[date, date]] = {
    "ROUTPUT": {
        date.fromisoformat(o + "-01"): date.fromisoformat(r) for o, r in _ROUTPUT_FIRST.items()
    },
    # bls, 2025 shutdown: September 2025 Employment Situation on 2025-11-20; October
    # (payrolls only) and November on 2025-12-16. CPI: September on 2025-10-24,
    # November on 2025-12-18 (October 2025 CPI and unemployment rate never published).
    "EMPLOY": {
        date(2025, 9, 1): date(2025, 11, 20),
        date(2025, 10, 1): date(2025, 12, 16),
        date(2025, 11, 1): date(2025, 12, 16),
    },
    "RUC": {date(2025, 9, 1): date(2025, 11, 20), date(2025, 11, 1): date(2025, 12, 16)},
    "PCPI": {date(2025, 9, 1): date(2025, 10, 24), date(2025, 11, 1): date(2025, 12, 18)},
}


def check_known_releases(
    df: pd.DataFrame, series_id: str, known: dict[str, dict[date, date]] | None = None
) -> list[str]:
    """Problems where a vintage contains a value dated (vintage_date) before its known
    first publication: a leak. Empty list = OK."""
    table = (KNOWN_RELEASES if known is None else known).get(series_id, {})
    problems = []
    for row in df.itertuples(index=False):
        published = table.get(row.observation_date)
        if published is not None and row.vintage_date < published:
            problems.append(
                f"{row.vintage} (dated {row.vintage_date}) contains {row.observation_date}, "
                f"first published {published}"
            )
    return problems


class VerificationError(RuntimeError):
    """Parsed content differs from data/checksums.json."""


# --- download ---------------------------------------------------------------------------


def download(url: str, dest: Path, session=None) -> None:
    """GET ``url`` to ``dest`` (atomic rename) with retries and backoff."""
    import requests

    sess = session or requests.Session()
    last = ""
    for attempt in range(RETRIES):
        try:
            resp = sess.get(url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
        except requests.RequestException as exc:
            last = f"{type(exc).__name__}: {exc}"
        else:
            if resp.status_code == 200 and resp.content[:2] == b"PK":
                tmp = dest.with_suffix(dest.suffix + ".part")
                tmp.write_bytes(resp.content)
                tmp.replace(dest)
                return
            last = f"HTTP {resp.status_code} (content-type {resp.headers.get('content-type')})"
            if resp.status_code not in (429, 500, 502, 503, 504):
                break
        time.sleep(PAUSE * 2**attempt)
    raise RuntimeError(f"download failed for {url}: {last}")


def ensure_files(series_ids: list[str], raw: Path, refresh: bool) -> None:
    raw.mkdir(parents=True, exist_ok=True)
    first = True
    for sid in series_ids:
        info = data.SERIES[sid]
        dest = raw / info.file
        if dest.exists() and not refresh:
            print(f"{sid}: {dest.name} present (no download)")
            continue
        if not first:
            time.sleep(PAUSE)
        first = False
        print(f"{sid}: downloading {info.url}")
        download(info.url, dest)


# --- parse, check, verify ---------------------------------------------------------------


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _month_index(d: date) -> int:
    return d.year * 12 + d.month - 1


def check_release_lags(df: pd.DataFrame, series_id: str) -> list[str]:
    """Sanity check that no vintage contains an observation that could not have been
    published by its vintage_date (returns problems; empty list = OK).

    Monthly data: the last observation must be for a month before the vintage month
    (RUC: before the middle month). ROUTPUT: the last quarter must have ended at least
    two months before the vintage month (RTDSM Table 4.A: the mid-February vintage
    ends with Q4's advance estimate).
    """
    problems = []
    info = data.SERIES.get(series_id)
    quarterly = info is not None and info.frequency == "quarterly"
    last_obs = df.groupby(["vintage", "vintage_date"])["observation_date"].max()
    for (label, vd), obs in last_obs.items():
        if quarterly:
            end = _month_index(obs) + 2  # last month of the quarter
            ok = _month_index(vd) - end >= 2
        else:
            ok = _month_index(obs) < _month_index(vd)
        if not ok:
            problems.append(f"{label}: last observation {obs} too recent for {vd}")
    return problems


def build_table(series_id: str, raw: Path, pin: str | None) -> tuple[pd.DataFrame, str]:
    """Parse the workbook, restrict to the pinned range; returns (table, pin label)."""
    path = raw / data.SERIES[series_id].file
    if not path.exists():
        raise FileNotFoundError(f"{path} missing. {data.FETCH_HINT}")
    full = data.parse_workbook(path, series_id)
    if pin is None:
        pin = full.sort_values("vintage_date")["vintage"].iloc[-1]
    table = data.restrict(full, last_vintage=pin)
    problems = check_release_lags(table, series_id) + check_known_releases(table, series_id)
    if problems:
        raise VerificationError(f"{series_id}: release-date check failed: {problems[:5]}")
    return table, pin


def verify(series_id: str, table: pd.DataFrame, checksums: dict) -> str:
    """Raise VerificationError if the canonical hash differs; returns the hash."""
    got = data.canonical_sha256(table)
    want = checksums.get(series_id, {}).get("canonical_sha256")
    if want is None:
        raise VerificationError(f"{series_id}: no entry in {data.CHECKSUMS_PATH.name}")
    if got != want:
        raise VerificationError(
            f"{series_id}: content of the pinned vintages differs from checksums.json "
            f"(got {got[:12]}..., expected {want[:12]}...). RTDSM may have corrected past "
            "vintages; results would not be comparable. Maintainers: inspect, then rerun "
            "with --update-checksums."
        )
    return got


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def checksum_entry(series_id: str, table: pd.DataFrame, raw: Path) -> dict:
    path = raw / data.SERIES[series_id].file
    labels = table.drop_duplicates("vintage_date")
    return {
        "canonical_sha256": data.canonical_sha256(table),
        "rows": len(table),
        "vintages": int(table["vintage_date"].nunique()),
        "observations": int(table["observation_date"].nunique()),
        "first_vintage": str(labels["vintage"].iloc[0]),
        "last_vintage": str(labels["vintage"].iloc[-1]),
        "raw_file_sha256_at_pin": file_sha256(path),
        "raw_file_bytes_at_pin": path.stat().st_size,
    }


def manifest_entry(series_id: str, table: pd.DataFrame) -> dict:
    info = data.SERIES[series_id]
    labels = table.drop_duplicates("vintage_date")
    return {
        "file": info.file,
        "url": info.url,
        "vintage_rule": info.vintage_rule,
        "first_vintage": str(labels["vintage"].iloc[0]),
        "first_vintage_date": labels["vintage_date"].iloc[0].isoformat(),
        "last_vintage": str(labels["vintage"].iloc[-1]),
        "last_vintage_date": labels["vintage_date"].iloc[-1].isoformat(),
    }


# --- README statistics --------------------------------------------------------------------


def stats_table(series_ids: list[str], raw: Path) -> str:
    lines = [
        "| Series | Vintages (pinned range) | Observations | Obs. compared "
        "| Mean abs. revision, first release vs latest | Same, % of level "
        "| Mean abs. revision of period % change (pp) | Share revised |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for sid in series_ids:
        s = data.revision_summary(sid, raw)
        unit = data.SERIES[sid].units.split(";")[0].split(",")[0]
        lines.append(
            f"| {sid} | {s['vintages']} ({s['first_vintage']} to {s['last_vintage']}) "
            f"| {s['observations']} ({s['obs_range']}) | {s['n_compared']} "
            f"| {s['mean_abs_revision']:.3f} {unit} | {s['mean_abs_revision_pct']:.3f}% "
            f"| {s['mean_abs_change_revision_pp']:.3f} | {s['share_revised']:.0%} |"
        )
    return "\n".join(lines)


def write_readme_stats(readme: Path, table: str) -> None:
    text = readme.read_text()
    start, end = text.index(STATS_BEGIN) + len(STATS_BEGIN), text.index(STATS_END)
    readme.write_text(text[:start] + "\n" + table + "\n" + text[end:])


# --- main ---------------------------------------------------------------------------------


def run(args: argparse.Namespace) -> int:
    raw: Path = args.raw
    if not args.verify_only:
        ensure_files(args.series, raw, args.refresh)
    manifest = _load_json(args.manifest)
    checksums = _load_json(args.checksums)
    pins = {s: e["last_vintage"] for s, e in manifest.get("series", {}).items()}
    new_manifest, new_sums = dict(manifest.get("series", {})), dict(checksums)
    failed = False
    for sid in args.series:
        pin = None if args.update_checksums else pins.get(sid)
        if pin is None and not args.update_checksums:
            print(f"{sid}: no pinned vintage in {args.manifest}", file=sys.stderr)
            failed = True
            continue
        try:
            table, pin = build_table(sid, raw, pin)
            if args.update_checksums:
                new_sums[sid] = checksum_entry(sid, table, raw)
                new_manifest[sid] = manifest_entry(sid, table)
            else:
                verify(sid, table, checksums)
                info_sha = checksums[sid].get("raw_file_sha256_at_pin")
                same = file_sha256(raw / data.SERIES[sid].file) == info_sha
                note = "" if same else " (raw file differs from pin date: new vintages, OK)"
                print(f"{sid}: OK, {table['vintage_date'].nunique()} vintages to {pin}{note}")
        except (VerificationError, FileNotFoundError, ValueError) as exc:
            print(f"{sid}: FAILED: {exc}", file=sys.stderr)
            failed = True
            continue
        table.to_parquet(raw / f"{sid}.parquet", index=False)
    if failed:
        return 1
    if args.update_checksums:
        _write_json(args.checksums, new_sums)
        _write_json(
            args.manifest,
            {
                "source": "Federal Reserve Bank of Philadelphia, Real-Time Data Set for "
                "Macroeconomists",
                "pinned_on": date.today().isoformat(),
                "obs_start": data.OBS_START.isoformat(),
                "vintage_start": data.VINTAGE_START.isoformat(),
                "series": new_manifest,
            },
        )
        print(f"wrote {args.checksums} and {args.manifest}")
    if args.update_checksums or args.readme:
        readme = args.manifest.parent / "README.md"
        have = [s for s in data.SERIES_IDS if (raw / f"{s}.parquet").exists()]
        write_readme_stats(readme, stats_table(have, raw))
        print(f"updated statistics in {readme}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--series", nargs="+", default=list(data.SERIES_IDS))
    p.add_argument("--raw", type=Path, default=data.RAW_DIR)
    p.add_argument("--manifest", type=Path, default=data.MANIFEST_PATH)
    p.add_argument("--checksums", type=Path, default=data.CHECKSUMS_PATH)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--verify-only", action="store_true", help="no network; verify data/raw")
    g.add_argument("--update-checksums", action="store_true", help="re-pin to latest vintage")
    p.add_argument("--refresh", action="store_true", help="re-download existing files")
    p.add_argument("--readme", action="store_true", help="also rewrite data/README.md stats")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
