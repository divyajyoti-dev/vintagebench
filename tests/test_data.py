"""Tests for vintagebench.data and scripts/fetch_data.py. Offline only."""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from vintagebench import data

FIXTURES = Path(__file__).parent / "fixtures" / "vintages"
REPO = Path(__file__).resolve().parents[1]
REAL_SERIES = ["PAYEMS", "GDPC1", "PCEPI", "INDPRO", "UNRATE"]


def _load_fetch_script():
    spec = importlib.util.spec_from_file_location("fetch_data", REPO / "scripts" / "fetch_data.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- fixture: TOY ---------------------------------------------------------------------


def test_load_vintages_schema_and_dtypes() -> None:
    df = data.load_vintages("TOY", root=FIXTURES)
    assert list(df.columns) == data.COLUMNS
    assert len(df) == 16
    assert all(type(d) is date for d in df["observation_date"])
    assert all(type(d) is date for d in df["vintage_date"])
    assert df["value"].dtype == "float64"


def test_vintage_dates_sorted_distinct() -> None:
    assert data.vintage_dates("TOY", root=FIXTURES) == [
        date(2021, 1, 15),
        date(2021, 2, 15),
        date(2021, 3, 15),
    ]


def test_missing_series_raises() -> None:
    with pytest.raises(FileNotFoundError):
        data.load_vintages("NOPE", root=FIXTURES)


@pytest.mark.parametrize(
    "as_of",
    [date(2021, 1, 15), date(2021, 2, 14), date(2021, 2, 15), date(2021, 3, 1), date(2030, 1, 1)],
)
def test_as_of_never_returns_future_vintages(as_of: date) -> None:
    df = data.load_vintages("TOY", root=FIXTURES)
    got = data.get_as_of("TOY", as_of, root=FIXTURES)
    for obs, value in got.items():
        rows = df[df["observation_date"] == obs]
        allowed = rows[rows["vintage_date"] <= as_of]
        # The value must come from the latest allowed vintage, never a later one.
        assert value == allowed.sort_values("vintage_date")["value"].iloc[-1]


def test_as_of_index_and_name() -> None:
    got = data.get_as_of("TOY", date(2021, 3, 15), root=FIXTURES)
    assert got.name == "TOY"
    assert got.index.name == "observation_date"
    assert all(type(d) is date for d in got.index)
    assert got.index.is_monotonic_increasing
    assert len(got) == 12
    assert got[date(2020, 11, 1)] == 102.7
    assert got[date(2020, 12, 1)] == 103.1


def test_as_of_before_first_release_is_empty() -> None:
    got = data.get_as_of("TOY", date(2021, 1, 14), root=FIXTURES)
    assert got.empty


def test_as_of_accepts_strings_and_timestamps() -> None:
    a = data.get_as_of("TOY", date(2021, 2, 15), root=FIXTURES)
    pd.testing.assert_series_equal(a, data.get_as_of("TOY", "2021-02-15", root=FIXTURES))
    pd.testing.assert_series_equal(
        a, data.get_as_of("TOY", pd.Timestamp("2021-02-15 13:00"), root=FIXTURES)
    )


def test_two_dates_differ_for_shared_observation() -> None:
    june = date(2020, 6, 1)
    first = data.get_as_of("TOY", date(2021, 1, 31), root=FIXTURES)
    revised = data.get_as_of("TOY", date(2021, 2, 28), root=FIXTURES)
    assert first[june] == 101.5
    assert revised[june] == 100.8
    # Unrevised observations stay identical.
    assert first[date(2020, 7, 1)] == revised[date(2020, 7, 1)]


# --- real ALFRED data committed in data/vintages ------------------------------------


@pytest.mark.parametrize("series_id", REAL_SERIES)
def test_real_data_schema_and_no_future(series_id: str) -> None:
    df = data.load_vintages(series_id)
    assert list(df.columns) == data.COLUMNS
    assert (df["series_id"] == series_id).all()
    assert df["observation_date"].min() == date(2015, 1, 1)
    assert not df.duplicated(["observation_date", "vintage_date"]).any()
    assert df["value"].notna().all()
    vintages = data.vintage_dates(series_id)
    assert vintages[0] <= date(2016, 1, 1) < vintages[1]
    for as_of in (date(2016, 1, 1), date(2019, 6, 30), date(2023, 1, 1)):
        got = data.get_as_of(series_id, as_of)
        released = df.groupby("observation_date")["vintage_date"].min()
        assert (released[got.index] <= as_of).all()
        assert set(got.index) == set(released[released <= as_of].index)


def test_payems_2019_benchmark_revision() -> None:
    # Documented revision: the annual CES benchmark released with the January 2020
    # Employment Situation (2020-02-07) revised the seasonally adjusted March 2019 total
    # nonfarm level down by 514,000 (-505,000 not seasonally adjusted).
    # Source: BLS, "The Employment Situation - January 2020", benchmark revision note,
    # https://www.bls.gov/news.release/archives/empsit_02072020.htm
    # and BLS CES benchmark article https://www.bls.gov/web/empsit/cesbmart.htm ;
    # vintages viewable at https://alfred.stlouisfed.org/series?seid=PAYEMS
    march_2019 = date(2019, 3, 1)
    before = data.get_as_of("PAYEMS", date(2020, 2, 6))[march_2019]
    after = data.get_as_of("PAYEMS", date(2020, 2, 7))[march_2019]
    assert before == 150796.0
    assert after == 150282.0
    assert after - before == -514.0  # thousands of persons


def test_readme_table_in_sync_with_data() -> None:
    readme = (REPO / "data" / "README.md").read_text()
    assert data.readme_table(REAL_SERIES) in readme


def test_revision_summary_toy() -> None:
    s = data.revision_summary("TOY", root=FIXTURES)
    assert s["vintages"] == 3
    # All TOY observations are first released in the baseline vintage.
    assert s["n_revised_obs"] == 0


# --- fetch script (HTTP mocked) -----------------------------------------------------


class _Resp:
    def __init__(self, payload: dict, status: int = 200, text: str = "") -> None:
        self._payload, self.status_code, self.text = payload, status, text

    def json(self) -> dict:
        return self._payload


class _FakeSession:
    """Serves series/vintagedates and output_type=1 observations from a fixed history."""

    # (observation date, value, realtime_start, realtime_end)
    HISTORY = [
        ("2015-11-01", "10", "2015-12-04", "2016-01-07"),
        ("2015-11-01", "11", "2016-01-08", "9999-12-31"),
        ("2015-12-01", "20", "2016-01-08", "2016-02-04"),
        ("2015-12-01", ".", "2016-02-05", "2016-03-03"),
        ("2015-12-01", "21", "2016-03-04", "9999-12-31"),
    ]
    VINTAGES = ["2015-11-06", "2015-12-04", "2016-01-08", "2016-02-05", "2016-03-04"]

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def get(self, url: str, params: dict, timeout: int) -> _Resp:
        self.calls.append(params)
        if url.endswith("series/vintagedates"):
            return _Resp({"count": len(self.VINTAGES), "vintage_dates": self.VINTAGES})
        lo, hi = params["realtime_start"], params["realtime_end"]
        rows = [
            {"date": d, "value": v, "realtime_start": max(s, lo), "realtime_end": min(e, hi)}
            for d, v, s, e in self.HISTORY
            if s <= hi and e >= lo
        ]
        return _Resp({"count": len(rows), "observations": rows[params["offset"] :]})


@pytest.mark.parametrize("chunk", [1, 2, 500])
def test_fetch_series_sparse_and_chunk_invariant(chunk: int) -> None:
    fetch = _load_fetch_script()
    session = _FakeSession()
    df = fetch.fetch_series(session, "X", "SECRETKEY", chunk=chunk)
    got = [
        (str(o), str(v), x) for o, v, x in df[["observation_date", "vintage_date", "value"]].values
    ]
    assert got == [
        ("2015-11-01", "2015-12-04", 10.0),  # baseline: last vintage <= 2016-01-01
        ("2015-11-01", "2016-01-08", 11.0),
        ("2015-12-01", "2016-01-08", 20.0),
        ("2015-12-01", "2016-03-04", 21.0),  # the "." vintage is dropped
    ]
    assert all(c["api_key"] == "SECRETKEY" for c in session.calls)
    obs_calls = [c for c in session.calls if "output_type" in c]
    assert all(c["output_type"] == 1 and c["observation_start"] == "2015-01-01" for c in obs_calls)


def test_fetch_error_redacts_key(monkeypatch: pytest.MonkeyPatch) -> None:
    fetch = _load_fetch_script()
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)

    class Bad:
        def get(self, url: str, params: dict, timeout: int) -> _Resp:
            return _Resp({}, 400, f"Bad Request: api_key={params['api_key']} is invalid")

    with pytest.raises(fetch.FredError) as err:
        fetch.fetch_series(Bad(), "X", "SECRETKEY")
    assert "SECRETKEY" not in str(err.value)
    assert "***" in str(err.value)


def test_main_skips_cached_series(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fetch = _load_fetch_script()
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    (tmp_path / "TOY.parquet").write_bytes((FIXTURES / "TOY.parquet").read_bytes())
    monkeypatch.setattr(fetch.requests, "Session", lambda: pytest.fail("network used"))
    assert fetch.main(["--series", "TOY", "--out", str(tmp_path)]) == 0
