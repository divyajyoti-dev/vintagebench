"""Tests for vintagebench.data and scripts/fetch_data.py (SPEC §2).

Offline only. All fixtures are synthetic numbers written to tmp_path in the RTDSM
layout (header DATE, <SERIES>yyMmm...; DATE cells like '2018:01' or '2018:Q1';
'#N/A' for missing). No RTDSM values appear here. The single real-data test skips
unless data/raw has been fetched locally.
"""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from vintagebench import data

REPO = Path(__file__).resolve().parents[1]
TOY_ROOT = Path(__file__).parent / "fixtures" / "vintages"


def _load_fetch_script():
    spec = importlib.util.spec_from_file_location("fetch_data", REPO / "scripts" / "fetch_data.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fetch = _load_fetch_script()

# Synthetic EMPLOY-like workbook: 4 monthly vintages, observations 2015:10..2016:02.
# EMPLOY16M2 revises 2015:12 (+7) and adds 2016:01; EMPLOY16M3 adds 2016:02.
HEADER = ("DATE", "EMPLOY15M11", "EMPLOY15M12", "EMPLOY16M1", "EMPLOY16M2", "EMPLOY16M3")
ROWS = [
    ("2015:09", 10.0, 10.0, 10.0, 10.0, 10.0),
    ("2015:10", 11.0, 11.0, 11.0, 12.0, 12.0),
    ("2015:11", "#N/A", 13.0, 13.0, 13.0, 13.0),
    ("2015:12", "#N/A", "#N/A", 15.0, 22.0, 22.0),
    ("2016:01", "#N/A", "#N/A", "#N/A", 17.0, 18.0),
    ("2016:02", "#N/A", "#N/A", "#N/A", "#N/A", 19.0),
]


def _rows():
    return [HEADER, *ROWS]


def _write_xlsx(path: Path, rows: list[tuple]) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "employ"
    for row in rows:
        ws.append(list(row))
    wb.save(path)
    return path


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """data/raw-like directory with EMPLOY.parquet built from the synthetic workbook."""
    xlsx = _write_xlsx(tmp_path / "employMvMd.xlsx", _rows())
    df = data.restrict(data.parse_workbook(xlsx, "EMPLOY"), obs_start=date(2015, 10, 1))
    df.to_parquet(tmp_path / "EMPLOY.parquet", index=False)
    return tmp_path


# --- labels and dates -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("2018:01", date(2018, 1, 1)),
        ("2018:12", date(2018, 12, 1)),
        ("2018:Q1", date(2018, 1, 1)),
        ("2018:Q4", date(2018, 10, 1)),
    ],
)
def test_parse_observation(label: str, expected: date) -> None:
    assert data.parse_observation(label) == expected


@pytest.mark.parametrize("bad", ["2018-01", "2018:13", "2018:Q5", "18:01", ""])
def test_parse_observation_rejects_bad(bad: str) -> None:
    with pytest.raises(ValueError):
        data.parse_observation(bad)


@pytest.mark.parametrize(
    ("label", "rule", "expected"),
    [
        ("EMPLOY18M11", "month_end", date(2018, 11, 30)),
        ("EMPLOY24M2", "month_end", date(2024, 2, 29)),  # leap year
        ("PCPI99M1", "month_end", date(1999, 1, 31)),  # two-digit year >= 60 -> 19xx
        ("ROUTPUT18M11", "mid_month", date(2018, 11, 15)),
        ("RUC18Q1", "mid_quarter", date(2018, 2, 15)),
        ("RUC18Q4", "mid_quarter", date(2018, 11, 15)),
        ("RUC65Q4", "mid_quarter", date(1965, 11, 15)),
    ],
)
def test_vintage_label_to_date(label: str, rule: str, expected: date) -> None:
    assert data.vintage_date(label, rule) == expected


@pytest.mark.parametrize(
    ("label", "rule"),
    [("EMPLOY18M13", "month_end"), ("RUC18Q1", "month_end"), ("EMPLOY18M1", "mid_quarter"),
     ("employ18m1", "month_end")],
)  # fmt: skip
def test_vintage_label_rejects_bad(label: str, rule: str) -> None:
    with pytest.raises(ValueError):
        data.vintage_date(label, rule)


def test_series_rules_and_metadata() -> None:
    assert data.SERIES_IDS == ("EMPLOY", "ROUTPUT", "IPT", "RUC", "PCPI")
    rules = {s: i.vintage_rule for s, i in data.SERIES.items()}
    assert rules == {"EMPLOY": "month_end", "ROUTPUT": "mid_month", "IPT": "month_end",
                     "RUC": "mid_quarter", "PCPI": "month_end"}  # fmt: skip
    assert data.SERIES["RUC"].rounding_unit == pytest.approx(0.1)
    assert data.SERIES["RUC"].tolerance == pytest.approx(0.05)
    assert data.SERIES["EMPLOY"].tolerance == pytest.approx(0.5)
    assert data.SERIES["ROUTPUT"].frequency == "quarterly"
    assert all(i.url.endswith(i.file) for i in data.SERIES.values())


# --- parsing the wide layout ------------------------------------------------------------


def test_wide_to_long_drops_missing_and_maps_dates() -> None:
    df = data.wide_to_long(_rows(), "EMPLOY")
    assert list(df.columns) == data.COLUMNS
    assert len(df) == 6 + 5 + 4 + 3 + 2  # non-#N/A cells
    assert "#N/A" not in set(df["value"].astype(str))
    first = df[df["vintage"] == "EMPLOY15M11"]
    assert set(first["vintage_date"]) == {date(2015, 11, 30)}
    assert first["observation_date"].max() == date(2015, 10, 1)
    assert all(type(d) is date for d in df["observation_date"])
    assert df["value"].dtype == "float64"


def test_wide_to_long_quarterly_layout() -> None:
    rows = [("DATE", "ROUTPUT16M1", "ROUTPUT16M2"), ("2015:Q3", 1.5, 1.5), ("2015:Q4", None, 2.5)]
    df = data.wide_to_long(rows, "ROUTPUT")
    assert sorted(set(df["observation_date"])) == [date(2015, 7, 1), date(2015, 10, 1)]
    assert sorted(set(df["vintage_date"])) == [date(2016, 1, 15), date(2016, 2, 15)]
    assert len(df) == 3


def test_wide_to_long_rejects_foreign_columns() -> None:
    with pytest.raises(ValueError):
        data.wide_to_long([("DATE", "IPT16M1"), ("2015:01", 1.0)], "EMPLOY")
    with pytest.raises(ValueError):
        data.wide_to_long([("OBS", "EMPLOY16M1"), ("2015:01", 1.0)], "EMPLOY")


def test_parse_workbook_reads_xlsx(tmp_path: Path) -> None:
    xlsx = _write_xlsx(tmp_path / "employMvMd.xlsx", _rows())
    pd.testing.assert_frame_equal(
        data.parse_workbook(xlsx, "EMPLOY"), data.wide_to_long(_rows(), "EMPLOY")
    )


def test_restrict_baseline_and_pin() -> None:
    df = data.wide_to_long(_rows(), "EMPLOY")
    out = data.restrict(df, last_vintage="EMPLOY16M2", obs_start=date(2015, 10, 1))
    # Baseline = latest vintage on or before 2016-01-01 (EMPLOY15M12, 2015-12-31).
    assert sorted(set(out["vintage"])) == ["EMPLOY15M12", "EMPLOY16M1", "EMPLOY16M2"]
    assert out["observation_date"].min() == date(2015, 10, 1)
    with pytest.raises(ValueError):
        data.restrict(df, last_vintage="EMPLOY30M1")


# --- loading and as-of ----------------------------------------------------------------


def test_load_vintages_schema(root: Path) -> None:
    df = data.load_vintages("EMPLOY", root)
    assert list(df.columns) == data.COLUMNS
    assert data.vintage_dates("EMPLOY", root) == [
        date(2015, 12, 31), date(2016, 1, 31), date(2016, 2, 29), date(2016, 3, 31)
    ]  # fmt: skip
    assert data.vintage_labels("EMPLOY", root)[date(2016, 2, 29)] == "EMPLOY16M2"


def test_missing_data_raises_helpful_error(tmp_path: Path) -> None:
    with pytest.raises(data.DataNotFetchedError, match="fetch_data.py"):
        data.load_vintages("EMPLOY", tmp_path / "raw")
    with pytest.raises(FileNotFoundError, match="data/raw is missing"):
        data.get_as_of("EMPLOY", date(2020, 1, 1), tmp_path / "raw")


@pytest.mark.parametrize(
    "as_of",
    [date(2015, 12, 31), date(2016, 1, 30), date(2016, 1, 31), date(2016, 2, 28),
     date(2016, 2, 29), "2016-03-15", date(2030, 1, 1)],
)  # fmt: skip
def test_as_of_never_returns_future_vintages(root: Path, as_of: object) -> None:
    df = data.load_vintages("EMPLOY", root)
    cutoff = pd.Timestamp(as_of).date()
    got = data.get_as_of("EMPLOY", as_of, root)
    allowed = df[df["vintage_date"] <= cutoff]
    newest = allowed["vintage_date"].max()
    expected = allowed[allowed["vintage_date"] == newest].set_index("observation_date")["value"]
    assert list(got.index) == list(expected.index)
    assert got.to_list() == expected.to_list()
    # No observation first published after as_of is visible.
    future_only = set(df["observation_date"]) - set(allowed["observation_date"])
    assert future_only.isdisjoint(got.index)


def test_as_of_before_first_vintage_is_empty(root: Path) -> None:
    got = data.get_as_of("EMPLOY", date(2015, 12, 30), root)
    assert got.empty and got.name == "EMPLOY" and got.index.name == "observation_date"


def test_as_of_index_and_type(root: Path) -> None:
    got = data.get_as_of("EMPLOY", date(2016, 3, 31), root)
    assert got.name == "EMPLOY" and got.index.name == "observation_date"
    assert all(type(d) is date for d in got.index) and got.index.is_monotonic_increasing
    assert got.dtype == "float64"


def test_two_dates_give_different_values_for_shared_observation(root: Path) -> None:
    dec = date(2015, 12, 1)
    before = data.get_as_of("EMPLOY", date(2016, 2, 28), root)  # EMPLOY16M1
    after = data.get_as_of("EMPLOY", date(2016, 2, 29), root)  # EMPLOY16M2
    assert before[dec] == 15.0 and after[dec] == 22.0


def test_first_release_and_latest(root: Path) -> None:
    assert data.first_release("EMPLOY", date(2016, 1, 1), root) == (17.0, date(2016, 2, 29))
    assert data.latest_value("EMPLOY", date(2016, 1, 1), root) == 18.0
    assert data.first_release("EMPLOY", "2015-12-01", root) == (15.0, date(2016, 1, 31))
    # 2015:10 is already in the baseline vintage, so its "first release" is the baseline.
    assert data.first_release("EMPLOY", date(2015, 10, 1), root)[1] == date(2015, 12, 31)
    assert not data.is_first_release_in_range("EMPLOY", date(2015, 10, 1), root)
    assert data.is_first_release_in_range("EMPLOY", date(2016, 1, 1), root)
    with pytest.raises(KeyError):
        data.first_release("EMPLOY", date(2017, 1, 1), root)
    with pytest.raises(KeyError):
        data.latest_value("EMPLOY", date(2017, 1, 1), root)


def test_latest_value_missing_in_latest_vintage(tmp_path: Path) -> None:
    rows = [("DATE", "PCPI15M12", "PCPI16M1"), ("2015:10", 1.0, 1.0), ("2015:11", 2.0, "#N/A")]
    data.restrict(data.wide_to_long(rows, "PCPI")).to_parquet(tmp_path / "PCPI.parquet")
    # Full-column semantics: a value dropped from the latest vintage is not carried over.
    assert date(2015, 11, 1) not in data.get_as_of("PCPI", date(2016, 1, 31), tmp_path).index
    with pytest.raises(KeyError):
        data.latest_value("PCPI", date(2015, 11, 1), tmp_path)


def test_legacy_sparse_fixture_is_densified() -> None:
    """The shared TOY fixture (4-column sparse) still yields the old as-of semantics."""
    raw = pd.read_parquet(TOY_ROOT / "TOY.parquet")
    for as_of in (date(2021, 1, 15), date(2021, 2, 20), date(2021, 3, 15)):
        got = data.get_as_of("TOY", as_of, TOY_ROOT)
        known = raw[raw["vintage_date"] <= as_of].sort_values("vintage_date")
        expected = known.groupby("observation_date")["value"].last()
        assert got.to_dict() == expected.to_dict()


def test_revision_summary_aggregates(root: Path) -> None:
    s = data.revision_summary("EMPLOY", root)
    assert s["vintages"] == 4 and s["n_compared"] == 3  # 2015:12, 2016:01, 2016:02
    assert s["mean_abs_revision"] == pytest.approx((7 + 1 + 0) / 3)


# --- checksums and the fetch script (no network) ------------------------------------------


def test_checksum_detects_change_and_ignores_appended_vintages() -> None:
    base = data.restrict(data.wide_to_long(_rows(), "EMPLOY"), last_vintage="EMPLOY16M2")
    h = data.canonical_sha256(base)
    assert data.canonical_sha256(base.sample(frac=1, random_state=0)) == h  # order-free
    # RTDSM appends a new monthly column: the pinned range hashes the same.
    rows = [(*r, v) for r, v in zip(_rows(), ("EMPLOY16M4", 10, 12, 13, 22, 18, 19), strict=True)]
    appended = data.restrict(data.wide_to_long(rows, "EMPLOY"), last_vintage="EMPLOY16M2")
    assert data.canonical_sha256(appended) == h
    # A corrected past value changes the hash.
    changed = base.copy()
    changed.loc[changed.index[0], "value"] += 0.001
    assert data.canonical_sha256(changed) != h
    with pytest.raises(fetch.VerificationError, match="differs"):
        fetch.verify("EMPLOY", changed, {"EMPLOY": {"canonical_sha256": h}})
    assert fetch.verify("EMPLOY", base, {"EMPLOY": {"canonical_sha256": h}}) == h


def test_release_lag_check_flags_too_recent_observations() -> None:
    ok = data.wide_to_long(_rows(), "EMPLOY")
    assert fetch.check_release_lags(ok, "EMPLOY") == []
    bad = data.wide_to_long([("DATE", "EMPLOY16M1"), ("2016:01", 1.0)], "EMPLOY")
    assert fetch.check_release_lags(bad, "EMPLOY")
    q_ok = data.wide_to_long([("DATE", "ROUTPUT16M2"), ("2015:Q4", 1.0)], "ROUTPUT")
    q_bad = data.wide_to_long([("DATE", "ROUTPUT16M1"), ("2015:Q4", 1.0)], "ROUTPUT")
    assert fetch.check_release_lags(q_ok, "ROUTPUT") == []
    assert fetch.check_release_lags(q_bad, "ROUTPUT")


def test_fetch_script_pin_then_verify_offline(tmp_path: Path, monkeypatch) -> None:
    def no_network(*args, **kwargs):
        raise AssertionError("network used")

    monkeypatch.setattr(fetch, "download", no_network)
    raw, meta = tmp_path / "raw", tmp_path / "meta"
    raw.mkdir()
    meta.mkdir()
    _write_xlsx(raw / "employMvMd.xlsx", _rows())
    (meta / "README.md").write_text(f"x\n{fetch.STATS_BEGIN}\n{fetch.STATS_END}\ny\n")
    paths = ["--series", "EMPLOY", "--raw", str(raw), "--manifest", str(meta / "manifest.json"),
             "--checksums", str(meta / "checksums.json")]  # fmt: skip
    assert fetch.main([*paths, "--update-checksums"]) == 0
    assert (raw / "EMPLOY.parquet").exists()
    assert "| EMPLOY |" in (meta / "README.md").read_text()
    assert fetch.main([*paths, "--verify-only"]) == 0
    assert fetch.main(paths) == 0  # file present: no download
    # Appending a vintage keeps verification green (pin unchanged).
    rows = [(*r, v) for r, v in zip(_rows(), ("EMPLOY16M4", 10, 12, 13, 22, 18, 19), strict=True)]
    _write_xlsx(raw / "employMvMd.xlsx", rows)
    assert fetch.main([*paths, "--verify-only"]) == 0
    assert data.vintage_dates("EMPLOY", raw)[-1] == date(2016, 3, 31)
    # Changing a pinned value fails with a nonzero exit.
    rows[2] = ("2015:10", 11.0, 11.5, 11.0, 12.0, 12.0, 12.0)
    _write_xlsx(raw / "employMvMd.xlsx", rows)
    assert fetch.main([*paths, "--verify-only"]) == 1


# --- real data (only if fetched locally) ---------------------------------------------------

HAVE_EMPLOY = (data.RAW_DIR / "EMPLOY.parquet").exists()


@pytest.mark.skipif(not HAVE_EMPLOY, reason="RTDSM data not fetched (scripts/fetch_data.py)")
def test_real_2019_payroll_benchmark_revision_was_downward() -> None:
    """BLS's 2019 benchmark revision, published with the January 2020 Employment
    Situation on 2020-02-07 (BLS news release USDL-20-0174, "The Employment Situation -
    January 2020", benchmark section: March 2019 total nonfarm employment revised
    down by 505,000 on a seasonally adjusted basis), must appear as a downward revision
    of March 2019 between RTDSM vintages EMPLOY20M1 and EMPLOY20M2. Only the sign and
    a broad magnitude band are asserted; no data values are stored here.
    """
    march_2019 = date(2019, 3, 1)
    labels = data.vintage_labels("EMPLOY")
    jan, feb = date(2020, 1, 31), date(2020, 2, 29)
    assert labels[jan] == "EMPLOY20M1" and labels[feb] == "EMPLOY20M2"
    before = data.get_as_of("EMPLOY", jan)[march_2019]
    after = data.get_as_of("EMPLOY", feb)[march_2019]
    assert after < before
    assert 300 < before - after < 700  # thousands; documented figure is about 500
