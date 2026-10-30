"""Tests for task generation (SPEC §3, §5). Offline: hand-built series and fixtures only."""

from __future__ import annotations

import dataclasses
import warnings
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from vintagebench import data, tasks
from vintagebench.tasks import Task

FIXTURES = Path(__file__).parent / "fixtures"
TOY_ROOT = FIXTURES / "vintages"


def monthly(values: list[float], start: str = "2020-01-01") -> pd.Series:
    idx = [d.date() for d in pd.date_range(start, periods=len(values), freq="MS")]
    return pd.Series(values, index=idx, dtype=float)


def quarterly(values: list[float], start: str = "2020-01-01") -> pd.Series:
    idx = [d.date() for d in pd.date_range(start, periods=len(values), freq="QS")]
    return pd.Series(values, index=idx, dtype=float)


T = pd.Timestamp


# --- helpers -----------------------------------------------------------------


def test_change_avg_yoy() -> None:
    s = monthly([100, 101, 103, 106])
    assert tasks.change(s, T("2020-04-01")) == 3
    assert tasks.change(s, T("2020-04-01"), months=3) == 6
    assert tasks.avg_change_3m(s, T("2020-04-01")) == 2
    assert tasks.change(s, T("2020-01-01")) is None  # no prior month
    y = monthly([100.0] + [0.0] * 11 + [102.5])
    assert tasks.yoy_pct(y, T("2021-01-01")) == pytest.approx(2.5)


# --- GDPC1 ------------------------------------------------------------------


def test_real_gdp_shrank() -> None:
    s = quarterly([100.0, 99.9, 99.9, 100.1])
    assert tasks.real_gdp_shrank(s, T("2020-04-01")) is True
    assert tasks.real_gdp_shrank(s, T("2020-07-01")) is False  # tie -> no
    assert tasks.real_gdp_shrank(s, T("2020-10-01")) is False
    assert tasks.real_gdp_shrank(s, T("2020-01-01")) is None  # missing prior quarter


def test_real_gdp_sign_flip() -> None:
    first, revised = quarterly([100.0, 100.1]), quarterly([100.0, 99.95])
    q = T("2020-04-01")
    assert tasks.real_gdp_shrank(first, q) is False
    assert tasks.real_gdp_shrank(revised, q) is True


# --- PAYEMS weakest in 12 months --------------------------------------------


def _levels_from_changes(changes: list[float], start_level: float = 150_000.0) -> pd.Series:
    levels = [start_level]
    for c in changes:
        levels.append(levels[-1] + c)
    return monthly(levels, start="2019-01-01")  # target month = 2020-01


def test_payrolls_weakest_in_12m() -> None:
    target = T("2020-01-01")
    base = [200, 180, 250, 90, 300, 210, 160, 220, 150, 175, 205]  # 11 earlier months
    assert tasks.payrolls_weakest_in_12m(_levels_from_changes(base + [89]), target) is True
    assert tasks.payrolls_weakest_in_12m(_levels_from_changes(base + [90]), target) is False
    assert tasks.payrolls_weakest_in_12m(_levels_from_changes(base + [91]), target) is False


def test_payrolls_weakest_window_includes_t_minus_11() -> None:
    # A lower change 11 months earlier (inside the window) means "no".
    changes = [-500] + [100] * 10 + [50]  # 12 changes: t-11 .. t
    s = _levels_from_changes(changes)
    assert tasks.payrolls_weakest_in_12m(s, T("2020-01-01")) is False
    # Drop one month from the window: missing data -> None.
    assert tasks.payrolls_weakest_in_12m(s.drop(s.index[5]), T("2020-01-01")) is None


def test_payrolls_weakest_ignores_older_months() -> None:
    # 13 changes: the oldest (-500, t-12) is outside the window.
    levels = [150_000.0]
    for c in [-500] + [100] * 11 + [50]:
        levels.append(levels[-1] + c)
    s = monthly(levels, start="2018-12-01")  # target 2020-01
    assert tasks.payrolls_weakest_in_12m(s, T("2020-01-01")) is True


def test_payrolls_weakest_sign_flip() -> None:
    base = [200, 180, 250, 90, 300, 210, 160, 220, 150, 175, 205]
    first, revised = _levels_from_changes(base + [95]), _levels_from_changes(base + [70])
    assert tasks.payrolls_weakest_in_12m(first, T("2020-01-01")) is False
    assert tasks.payrolls_weakest_in_12m(revised, T("2020-01-01")) is True


# --- PAYEMS 3-month average -------------------------------------------------


@pytest.mark.parametrize(
    ("total_change", "threshold", "expected"),
    [(450, 150, False), (451, 150, True), (449, 150, False), (300, 100, False), (301, 100, True)],
)
def test_payrolls_3m_avg_above_edges(total_change: float, threshold: int, expected: bool) -> None:
    s = monthly([150_000, 150_000 + total_change / 3, 150_000, 150_000 + total_change])
    assert tasks.payrolls_3m_avg_above(s, T("2020-04-01"), threshold) is expected


def test_payrolls_3m_avg_missing_and_flip() -> None:
    s = monthly([150_000, 150_100, 150_300, 150_480])  # avg 160
    assert tasks.payrolls_3m_avg_above(s, T("2020-04-01"), 150) is True
    revised = monthly([150_000, 150_100, 150_300, 150_420])  # avg 140
    assert tasks.payrolls_3m_avg_above(revised, T("2020-04-01"), 150) is False
    assert tasks.payrolls_3m_avg_above(s.iloc[1:], T("2020-04-01"), 150) is None


# --- INDPRO -----------------------------------------------------------------


def test_industrial_production_fell() -> None:
    s = monthly([101.1, 101.0, 101.0, 101.2])
    assert tasks.industrial_production_fell(s, T("2020-02-01")) is True
    assert tasks.industrial_production_fell(s, T("2020-03-01")) is False  # tie -> no
    assert tasks.industrial_production_fell(s, T("2020-04-01")) is False
    s_nan = s.copy()
    s_nan.iloc[0] = float("nan")
    assert tasks.industrial_production_fell(s_nan, T("2020-02-01")) is None


def test_industrial_production_sign_flip_toy() -> None:
    df = pd.read_parquet(TOY_ROOT / "TOY.parquet")
    first = df[df["vintage_date"] == date(2021, 1, 15)].set_index("observation_date")["value"]
    revised = first.copy()
    revised[date(2020, 6, 1)] = 100.8
    june = T("2020-06-01")
    assert tasks.industrial_production_fell(first, june) is False
    assert tasks.industrial_production_fell(revised, june) is True


# --- PCEPI ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("latest", "expected"),
    [(102.5, False), (102.51, True), (102.49, False), (97.0, False), (103.0, True)],
)
def test_pce_yoy_above_edges(latest: float, expected: bool) -> None:
    s = monthly([100.0] + [100.0] * 11 + [latest])
    assert tasks.pce_yoy_above(s, T("2021-01-01"), 2.5) is expected


def test_pce_yoy_flip_and_missing() -> None:
    first = monthly([110.0] + [111.0] * 11 + [112.70])  # 2.4545%
    revised = monthly([110.0] + [111.0] * 11 + [112.80])  # 2.5455%
    assert tasks.pce_yoy_above(first, T("2021-01-01")) is False
    assert tasks.pce_yoy_above(revised, T("2021-01-01")) is True
    assert tasks.pce_yoy_above(first.iloc[1:], T("2021-01-01")) is None


# --- UNRATE -----------------------------------------------------------------


def test_unrate_rose_rounding() -> None:
    s = monthly([3.5, 3.6, 3.6, 3.5, 3.5000000001, 3.54])
    assert tasks.unrate_rose(s, T("2020-02-01")) is True
    assert tasks.unrate_rose(s, T("2020-03-01")) is False  # equal -> no
    assert tasks.unrate_rose(s, T("2020-04-01")) is False  # fell
    assert tasks.unrate_rose(s, T("2020-05-01")) is False  # float noise is not a rise
    assert tasks.unrate_rose(s, T("2020-06-01")) is False  # 3.54 rounds to 3.5
    assert tasks.unrate_rose(s, T("2020-01-01")) is None


def test_unrate_sign_flip() -> None:
    first, revised = monthly([3.5, 3.6]), monthly([3.6, 3.6])
    assert tasks.unrate_rose(first, T("2020-02-01")) is True
    assert tasks.unrate_rose(revised, T("2020-02-01")) is False


# --- templates and dates ----------------------------------------------------


def test_templates_cover_spec_series_with_round_thresholds() -> None:
    assert set(tasks.TEMPLATES) == {"GDPC1", "PAYEMS", "INDPRO", "PCEPI", "UNRATE"}
    t = T("2020-03-01")
    q = tasks.TEMPLATES["PAYEMS"][1].question(t)
    assert "3 months ending March 2020 above 100k" in q and "January 2020" in q
    assert "above 150k" in tasks.TEMPLATES["PAYEMS"][2].question(t)
    assert "Q2 2020" in tasks.TEMPLATES["GDPC1"][0].question(T("2020-04-01"))
    assert "Q1 2020" in tasks.TEMPLATES["GDPC1"][0].question(T("2020-04-01"))
    assert "March 2019 to March 2020 above 2.5%" in tasks.TEMPLATES["PCEPI"][0].question(t)


def test_revision_date_rule() -> None:
    vs = [date(2020, 1, 10), date(2020, 6, 1), date(2021, 1, 9), date(2021, 1, 12)]
    assert tasks.revision_date_for(date(2020, 1, 10), vs) == date(2021, 1, 12)
    assert tasks.revision_date_for(date(2020, 6, 1), vs) == date(2021, 1, 12)  # latest
    assert tasks.revision_date_for(date(2021, 1, 12), vs) is None


# --- build_candidates on the TOY fixture ------------------------------------


def _fixture_as_of(series_id: str, as_of: date, root: Path = TOY_ROOT) -> pd.Series:
    df = pd.read_parquet(Path(root) / f"{series_id}.parquet")
    known = df[df["vintage_date"] <= as_of]
    return known.sort_values("vintage_date").groupby("observation_date")["value"].last()


def _data_implemented() -> bool:
    try:
        data.get_as_of("TOY", date(2021, 1, 15), TOY_ROOT)
    except NotImplementedError:
        return False
    return True


@pytest.fixture
def toy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Map TOY to the 'fell vs prior month' template; use data.py if it is implemented."""
    monkeypatch.setitem(tasks.TEMPLATES, "TOY", (tasks.fell_vs_prior_month_template("TOY"),))
    if not _data_implemented():
        monkeypatch.setattr(
            data, "load_vintages", lambda s, root=TOY_ROOT: pd.read_parquet(root / f"{s}.parquet")
        )
        monkeypatch.setattr(
            data,
            "vintage_dates",
            lambda s, root=TOY_ROOT: sorted(
                set(pd.read_parquet(root / f"{s}.parquet")["vintage_date"])
            ),
        )
        monkeypatch.setattr(data, "get_as_of", _fixture_as_of)


@pytest.mark.usefixtures("toy")
def test_build_candidates_toy() -> None:
    cands = tasks.build_candidates(["TOY"], TOY_ROOT)
    by_id = {c.id: c for c in cands}
    assert len(cands) == 11  # Feb..Dec 2020; Jan has no prior month
    assert all(c.as_of_date == "2021-01-15" for c in cands)
    assert all(c.revision_date == "2021-03-15" for c in cands)  # no vintage 1y later

    june = by_id["toy-mom-fall-2020-06"]
    assert (june.gold_as_of, june.gold_revised, june.flips) == (False, True, True)
    assert "June 2020" in june.question and "May 2020" in june.question
    may = by_id["toy-mom-fall-2020-05"]
    assert (may.gold_as_of, may.gold_revised, may.flips) == (True, True, False)
    assert [c.id for c in cands if c.flips] == ["toy-mom-fall-2020-06"]

    # Gold answers agree with an independent recomputation from the fixture.
    for c in cands:
        t = T(c.id[-7:] + "-01")
        for d, gold in ((c.as_of_date, c.gold_as_of), (c.revision_date, c.gold_revised)):
            s = _fixture_as_of("TOY", date.fromisoformat(d)).diff()
            assert gold == bool(s[t.date()] < 0)


def test_build_candidates_unknown_series() -> None:
    with pytest.raises(ValueError):
        tasks.build_candidates(["NOPE"], TOY_ROOT)


# --- select_pilot -----------------------------------------------------------


def _fake(series: str, key: str, ym: str, flips: bool) -> Task:
    return Task(
        id=f"{series.lower()}-{key}-{ym}",
        series_id=series,
        as_of_date=f"{ym}-28",
        question=f"{series} {key} {ym}?",
        answer_type="yes_no",
        gold_as_of=True,
        revision_date=f"{int(ym[:4]) + 1}{ym[4:]}-28",
        gold_revised=not flips,
        flips=flips,
    )


def _pool(flip_every: int = 3) -> list[Task]:
    out = []
    keys = {"GDPC1": ["q"], "PAYEMS": ["w", "a100", "a150"], "INDPRO": ["f"], "PCEPI": ["y"]}
    i = 0
    for year in range(2016, 2026):
        for month in (1, 4, 7, 10):
            ym = f"{year}-{month:02d}"
            for s, ks in keys.items():
                for k in ks:
                    i += 1
                    out.append(_fake(s, k, ym, flips=i % flip_every == 0))
            out.append(_fake("UNRATE", "r", ym, flips=False))
    return out


def test_select_pilot_balance_and_spread() -> None:
    pool = _pool()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        pilot = tasks.select_pilot(pool, n=20, seed=0)
    assert len(pilot) == 20
    assert len({t.id for t in pilot}) == 20
    assert sum(t.flips for t in pilot) == 10
    assert sum(t.series_id == "UNRATE" and not t.flips for t in pilot) == 2
    assert len({t.series_id for t in pilot}) == 5
    years = {t.id[-7:-3] for t in pilot}
    assert len(years) >= 8
    assert len({(t.series_id, t.id[-7:]) for t in pilot}) == 20  # one task per target
    assert all(2016 <= int(y) <= 2025 for y in years)


def test_select_pilot_deterministic_and_seeded() -> None:
    pool = _pool()
    a = tasks.select_pilot(pool, seed=0)
    assert a == tasks.select_pilot(list(reversed(pool)), seed=0)
    assert a == tasks.select_pilot(pool + pool, seed=0)  # duplicates dropped
    assert {t.id for t in a} != {t.id for t in tasks.select_pilot(pool, seed=1)}


def test_select_pilot_short_on_flips_warns() -> None:
    pool = [t for t in _pool() if not t.flips] + [t for t in _pool() if t.flips][:3]
    with pytest.warns(UserWarning, match="3 flips"):
        pilot = tasks.select_pilot(pool, n=20, seed=0)
    assert len(pilot) == 20 and sum(t.flips for t in pilot) == 3


def test_select_pilot_excludes_out_of_range_years() -> None:
    pool = _pool() + [_fake("INDPRO", "f", "2015-06", flips=True)]
    pilot = tasks.select_pilot(pool, n=40, seed=0)
    assert all(not t.id.endswith("2015-06") for t in pilot)


# --- I/O --------------------------------------------------------------------


def test_save_load_round_trip(tmp_path: Path) -> None:
    rows = tasks.load_tasks(FIXTURES / "tasks.jsonl")
    assert len(rows) == 3 and rows[2].gold_as_of == 0.4
    out = tmp_path / "sub" / "t.jsonl"
    tasks.save_tasks(out, rows)
    assert tasks.load_tasks(out) == rows
    assert out.read_text() == (FIXTURES / "tasks.jsonl").read_text()
    assert [type(r.gold_as_of) for r in tasks.load_tasks(out)] == [bool, bool, float]
    assert list(dataclasses.asdict(rows[0])) == [f.name for f in dataclasses.fields(Task)]


# --- README / entry point ---------------------------------------------------


@pytest.mark.usefixtures("toy")
def test_main_writes_pilot_and_readme(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks, "SERIES", ("TOY",))
    with pytest.warns(UserWarning):  # TOY has only one flip and no UNRATE
        tasks.main(root=TOY_ROOT, out_dir=tmp_path, seed=0)
    pilot = tasks.load_tasks(tmp_path / "pilot.jsonl")
    readme = (tmp_path / "README.md").read_text()
    assert any(t.flips for t in pilot)
    assert "| toy-mom-fall (TOY) |" in readme and "| 11 | 1 |" in readme
    for t in pilot:
        row = f"| {t.id} | {t.question} | {'Yes' if t.gold_as_of else 'No'} |"
        assert row in readme


@pytest.mark.usefixtures("toy")
def test_skips_targets_first_seen_in_pre_2016_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    # Pretend TOY's first vintage (2021-01-15) is a baseline: every target is first
    # seen there, so none is a genuine first release.
    assert len(tasks.build_candidates(["TOY"], TOY_ROOT)) == 11
    monkeypatch.setattr(tasks, "BASELINE_CUTOFF", date(2021, 2, 1))
    assert tasks.build_candidates(["TOY"], TOY_ROOT) == []
