"""Tests for task generation (SPEC §3, §5). Offline: hand-built series and fixtures only."""

from __future__ import annotations

import dataclasses
import math
import subprocess
import sys
import warnings
from collections import Counter
from collections.abc import Iterable
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
    assert "3 months ending March 2020 above 100k" in q
    assert "(level(March 2020) - level(December 2019)) / 3 above 100" in q
    assert "in thousands of jobs" in q
    assert "above 150k" in tasks.TEMPLATES["PAYEMS"][2].question(t)
    assert "Q2 2020" in tasks.TEMPLATES["GDPC1"][0].question(T("2020-04-01"))
    assert "Q1 2020" in tasks.TEMPLATES["GDPC1"][0].question(T("2020-04-01"))
    pce_q = tasks.TEMPLATES["PCEPI"][0].question(t)
    assert pce_q.startswith("Is PCE inflation (year over year) above 2.5% for March 2020")
    assert "from March 2019 to March 2020, 100 * (level(March 2020) / level(March 2019) - 1)" in (
        pce_q
    )
    assert "as of" not in pce_q
    weak_q = tasks.TEMPLATES["PAYEMS"][0].question(t)
    assert weak_q.startswith("Was March 2020 the weakest of the 12 months ending in March 2020")
    assert "change(April 2019) through change(February 2020)" in weak_q
    assert "level(month) - level(previous month)" in weak_q and "thousands of jobs" in weak_q


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


def _fake(series: str, key: str, ym: str, flips: bool, yes: bool = True) -> Task:
    return Task(
        id=f"{series.lower()}-{key}-{ym}",
        series_id=series,
        as_of_date=f"{ym}-28",
        question=f"{series} {key} {ym}?",
        answer_type="yes_no",
        gold_as_of=yes,
        revision_date=f"{int(ym[:4]) + 1}{ym[4:]}-28",
        gold_revised=yes != flips,
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
                    out.append(_fake(s, k, ym, flips=i % flip_every == 0, yes=i % 2 == 0))
            out.append(_fake("UNRATE", "r", ym, flips=False, yes=month in (1, 7)))
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
    # Stratified on (flips, gold_as_of): half Yes within flips and within controls.
    cells = Counter((t.flips, t.gold_as_of) for t in pilot)
    assert cells == {(True, True): 5, (True, False): 5, (False, True): 5, (False, False): 5}
    unrate = [t for t in pilot if t.series_id == "UNRATE"]
    assert sorted(t.gold_as_of for t in unrate) == [False, True]


def test_select_pilot_short_stratum_warns_and_uses_sibling() -> None:
    pool = [t for t in _pool() if not (t.flips and t.gold_as_of)]  # no flip/as-of Yes
    with pytest.warns(UserWarning, match=r"flip/as-of Yes 0/5"):
        pilot = tasks.select_pilot(pool, n=20, seed=0)
    assert len(pilot) == 20
    assert sum(t.flips for t in pilot) == 10  # sibling stratum keeps flips at 10
    assert sum(t.series_id == "UNRATE" for t in pilot) == 2


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
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
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
        tasks.main(
            ["--out", str(tmp_path / "pilot.jsonl"), "--readme-out", str(tmp_path / "README.md")],
            root=TOY_ROOT,
        )
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


# --- materiality margins ------------------------------------------------------


def test_pct_change() -> None:
    s = monthly([200.0, 201.0])
    assert tasks.pct_change(s, T("2020-02-01")) == pytest.approx(0.5)
    assert tasks.pct_change(s, T("2020-01-01")) is None


@pytest.mark.parametrize(
    ("level", "kept"),
    [(100.05, True), (100.049, False), (99.95, True), (99.951, False), (100.0, False)],
)
def test_indpro_margin_boundary(level: float, kept: bool) -> None:
    s = monthly([100.0, level])  # % change = level - 100
    assert tasks.is_material(tasks.mom_pct_margin(s, T("2020-02-01")), 0.05) is kept


@pytest.mark.parametrize(("level", "kept"), [(100.05, True), (100.04, False), (99.94, True)])
def test_gdp_margin_boundary(level: float, kept: bool) -> None:
    s = quarterly([100.0, level])
    assert tasks.is_material(tasks.gdp_margin(s, T("2020-04-01")), 0.05) is kept


@pytest.mark.parametrize(
    ("latest", "kept"),
    [(102.55, True), (102.45, True), (102.54, False), (102.46, False), (102.5137, False)],
)
def test_pce_margin_boundary(latest: float, kept: bool) -> None:
    s = monthly([100.0] * 12 + [latest])  # YoY = latest - 100
    assert tasks.is_material(tasks.pce_margin(s, T("2021-01-01"), 2.5), 0.05) is kept


@pytest.mark.parametrize(
    ("total", "kept"), [(453, True), (447, True), (452, False), (448, False), (450, False)]
)
def test_payrolls_3m_margin_boundary(total: int, kept: bool) -> None:
    s = monthly([150_000, 150_100, 150_200, 150_000 + total])  # avg = total / 3 vs 150
    assert tasks.is_material(tasks.payrolls_3m_margin(s, T("2020-04-01"), 150), 1.0) is kept


@pytest.mark.parametrize(
    ("this", "kept"), [(89, True), (91, True), (89.5, False), (90.5, False), (90, False)]
)
def test_payrolls_weakest_margin_boundary(this: float, kept: bool) -> None:
    base = [200, 180, 250, 90, 300, 210, 160, 220, 150, 175, 205]  # min = 90
    s = _levels_from_changes(base + [this])
    assert tasks.is_material(tasks.payrolls_weakest_margin(s, T("2020-01-01")), 1.0) is kept


def test_margins_missing_data() -> None:
    assert tasks.is_material(None, 0.05) is False
    assert tasks.mom_pct_margin(monthly([100.0]), T("2020-01-01")) is None
    assert tasks.payrolls_weakest_margin(monthly([1.0, 2.0]), T("2020-02-01")) is None


@pytest.mark.usefixtures("toy")
def test_build_candidates_drops_immaterial(monkeypatch: pytest.MonkeyPatch) -> None:
    # TOY one-month % changes are all >= ~0.2% in both vintages: nothing dropped at 0.05.
    assert len(tasks.build_candidates(["TOY"], TOY_ROOT)) == 11
    # Raising the margin to 0.3% drops months clear by less (e.g. Apr +0.198%), and June
    # (as-of +0.495%, revised -0.198%) is dropped because the revised vintage is too close.
    strict = dataclasses.replace(tasks.fell_vs_prior_month_template("TOY"), min_margin=0.3)
    monkeypatch.setitem(tasks.TEMPLATES, "TOY", (strict,))
    ids = {c.id for c in tasks.build_candidates(["TOY"], TOY_ROOT)}
    assert "toy-mom-fall-2020-04" not in ids and "toy-mom-fall-2020-06" not in ids
    assert "toy-mom-fall-2020-03" in ids  # +0.498% in both vintages
    assert all(
        "Kept only if, in both vintages" in c.notes
        for c in tasks.build_candidates(["TOY"], TOY_ROOT)
    )


@pytest.mark.parametrize("n", range(1, 13))
def test_select_pilot_small_n_exact_size(n: int) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # a well-stocked pool meets every quota
        pilot = tasks.select_pilot(_pool(), n=n, seed=0)
    assert len(pilot) == n
    assert len({t.id for t in pilot}) == n
    assert sum(t.series_id == "UNRATE" for t in pilot) == min(2, n - n // 2)
    assert sum(t.flips for t in pilot) == n // 2


def test_select_pilot_too_small_pool_warns() -> None:
    pool = _pool()[:12]  # 2 target months only: cannot fill 20
    with pytest.warns(UserWarning, match=r"got \d+/20 tasks"):
        pilot = tasks.select_pilot(pool, n=20, seed=0)
    assert len(pilot) < 20


# --- GDPC1 growth above 2% (annualized) ---------------------------------------


def _ann(rate_pct: float) -> pd.Series:
    """Two quarters whose annualized growth is exactly ``rate_pct``."""
    return quarterly([100.0, 100.0 * (1 + rate_pct / 100) ** 0.25])


def test_annualized_qoq_pct() -> None:
    assert tasks.annualized_qoq_pct(_ann(2.0), T("2020-04-01")) == pytest.approx(2.0)
    s = quarterly([100.0, 101.0])
    assert tasks.annualized_qoq_pct(s, T("2020-04-01")) == pytest.approx(100 * (1.01**4 - 1))
    assert tasks.annualized_qoq_pct(s, T("2020-01-01")) is None


@pytest.mark.parametrize(
    ("rate", "expected"), [(2.5, True), (2.01, True), (1.99, False), (-1.0, False)]
)
def test_real_gdp_grew_faster_than(rate: float, expected: bool) -> None:
    assert tasks.real_gdp_grew_faster_than(_ann(rate), T("2020-04-01")) is expected


def test_real_gdp_grew_faster_than_tie_missing_and_flip() -> None:
    q = T("2020-04-01")
    tie = quarterly([100.0, 100.0])  # 0% vs threshold 0 -> tie -> no
    assert tasks.real_gdp_grew_faster_than(tie, q, threshold_pct=0.0) is False
    assert tasks.real_gdp_grew_faster_than(quarterly([100.0]), q) is None
    # Sign flip: advance 1.2% annualized, revised 2.2%.
    assert tasks.real_gdp_grew_faster_than(_ann(1.2), q) is False
    assert tasks.real_gdp_grew_faster_than(_ann(2.2), q) is True


@pytest.mark.parametrize(
    ("rate", "kept"),
    [(2.2, True), (1.8, True), (2.19, False), (1.81, False), (2.0, False), (3.0, True)],
)
def test_gdp_growth_margin_boundary(rate: float, kept: bool) -> None:
    m = tasks.gdp_growth_margin(_ann(rate), T("2020-04-01"))
    assert tasks.is_material(m, tasks.GDP_ANNUALIZED_MARGIN) is kept


def test_gdp_growth_template_question() -> None:
    tp = tasks.TEMPLATES["GDPC1"][1]
    q = tp.question(T("2020-07-01"))
    assert q.startswith("Did real GDP grow faster than 2% (annualized) in Q3 2020, i.e.")
    assert "Q2 2020" in q and "above 2.0%" in q
    assert tp.min_margin == 0.2 and tp.lookback_months == 3


# --- COVID exclusion for controls ---------------------------------------------


@pytest.mark.parametrize(
    ("task_id", "overlaps"),
    [
        ("gdpc1-qoq-shrink-2019-10", False),  # Q3-Q4 2019: clear
        ("gdpc1-qoq-shrink-2020-01", True),  # 2020 Q1 contains March 2020
        ("gdpc1-growth-above-2-2020-01", True),
        ("gdpc1-qoq-shrink-2020-04", True),  # 2020 Q2
        ("gdpc1-growth-above-2-2020-07", True),  # 2020 Q3
        ("gdpc1-qoq-shrink-2020-10", True),  # compares with Q3
        ("gdpc1-qoq-shrink-2021-01", False),
        ("indpro-mom-fall-2020-02", False),
        ("indpro-mom-fall-2020-03", True),
        ("indpro-mom-fall-2020-07", True),  # compares with June
        ("indpro-mom-fall-2020-08", False),
        ("unrate-mom-rise-2020-05", True),
        ("payems-avg3m-above-100k-2020-09", True),  # reads June level
        ("payems-avg3m-above-100k-2020-10", False),
        ("payems-weakest-12m-2021-06", True),  # window reaches June 2020
        ("payems-weakest-12m-2021-07", False),
        ("pcepi-yoy-above-2.5-2021-06", True),
        ("pcepi-yoy-above-2.5-2021-07", False),
        ("pcepi-yoy-above-2.5-2020-02", False),
    ],
)
def test_covid_window_overlap(task_id: str, overlaps: bool) -> None:
    series = task_id.split("-")[0].upper()
    key, ym = task_id[len(series) + 1 : -8], task_id[-7:]
    task = _fake(series, key, ym, flips=False)
    assert tasks.template_for(task) is not None
    assert tasks.covid_window_overlap(task) is overlaps


def test_select_pilot_excludes_covid_controls_keeps_covid_flips() -> None:
    pool = []
    months = [f"{y}-{m:02d}" for y in (2019, 2020, 2021) for m in range(1, 13)]
    for i, ym in enumerate(months):
        for s, key in [("INDPRO", "mom-fall"), ("PAYEMS", "avg3m-above-150k"),
                       ("PCEPI", "yoy-above-2.5"), ("UNRATE", "mom-rise")]:  # fmt: skip
            pool.append(_with_dist(_fake(s, key, ym, flips=False, yes=i % 2 == 0), 2.0, 3.0))
    covid = ["2020-03", "2020-04", "2020-05", "2020-06", "2020-07"]
    for j, ym in enumerate(covid):  # the only flips are inside COVID windows
        pool.append(_fake("INDPRO", "mom-rise-x", ym, flips=True, yes=j % 2 == 0))
        pool.append(_fake("PAYEMS", "weakest-x", ym, flips=True, yes=j % 2 == 1))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pilot = tasks.select_pilot(pool, n=20, seed=0)
    controls = [t for t in pilot if not t.flips]
    assert controls and not any(tasks.covid_window_overlap(t) for t in controls)
    assert sum(t.flips for t in pilot) == 10  # COVID flips remain eligible
    # Sanity: the pool did contain eligible-looking COVID controls.
    assert any(not t.flips and tasks.covid_window_overlap(t) for t in pool)


# --- notes and non-trivial controls -------------------------------------------


@pytest.mark.usefixtures("toy")
def test_notes_report_pct_change_and_distance() -> None:
    june = {c.id: c for c in tasks.build_candidates(["TOY"], TOY_ROOT)}["toy-mom-fall-2020-06"]
    assert "one-month % change: as-of 0.495, revised -0.198." in june.notes
    # |% change| / 0.05: 0.4951 / 0.05 = 9.90; 0.198 / 0.05 = 3.96
    assert tasks.threshold_distances(june) == pytest.approx((9.90, 3.96), abs=0.01)
    assert "margin units: as-of 9.9010, revised 3.9604." in june.notes  # 4 decimals


@pytest.mark.parametrize(("as_of", "trivial"), [(10.000001, True), (10.0, False), (9.99999, False)])
def test_trivial_control_compares_unrounded(as_of: float, trivial: bool) -> None:
    # INDPRO cap is 10 margins; 10.000001 would display as 10.0000 in notes.
    task = _with_dist(_fake("INDPRO", "mom-fall", "2021-07", flips=False), as_of, 13.1)
    assert tasks.trivial_control(task) is trivial


def test_prior_11_min_change() -> None:
    base = [200, 180, 250, 90, 300, 210, 160, 220, 150, 175, 205]
    s = _levels_from_changes(base + [70])
    assert tasks.prior_11_min_change(s, T("2020-01-01")) == 90
    assert tasks.prior_11_min_change(s.iloc[3:], T("2020-01-01")) is None


def _with_dist(task: Task, as_of: float, revised: float) -> Task:
    tasks._attach_distances(task, (as_of, revised))  # as build_candidates does
    return task


@pytest.mark.parametrize(
    ("series", "key", "dists", "flips", "trivial"),
    [
        ("INDPRO", "mom-fall", (10.0, 10.0), False, False),  # at the cap: kept
        ("INDPRO", "mom-fall", (10.01, 30.0), False, True),  # over the cap in both
        ("INDPRO", "mom-fall", (30.0, 9.0), False, False),  # close in one vintage
        ("PCEPI", "yoy-above-2.5", (19.2, 19.0), False, True),
        ("PAYEMS", "avg3m-above-150k", (39.0, 41.0), False, False),
        ("PAYEMS", "avg3m-above-150k", (391.0, 380.0), False, True),
        ("PAYEMS", "weakest-12m", (40.5, 41.0), False, True),
        ("GDPC1", "qoq-shrink", (12.0, 11.0), False, True),
        ("GDPC1", "qoq-shrink", (5.0, 9.0), False, False),  # shrink cap is 5: at the cap
        ("GDPC1", "qoq-shrink", (5.01, 9.0), False, True),
        ("GDPC1", "growth-above-2", (9.0, 12.0), False, False),
        ("INDPRO", "mom-fall", (50.0, 50.0), True, False),  # flips exempt
        ("UNRATE", "mom-rise", (50.0, 50.0), False, False),  # UNRATE exempt
    ],
)
def test_trivial_control(
    series: str, key: str, dists: tuple[float, float], flips: bool, trivial: bool
) -> None:
    task = _with_dist(_fake(series, key, "2018-04", flips=flips), *dists)
    assert tasks.trivial_control(task) is trivial


def test_trivial_control_without_distance_raises(tmp_path: Path) -> None:
    task = _fake("INDPRO", "mom-fall", "2018-04", flips=False)  # capped, no distance
    with pytest.raises(ValueError, match="cannot load vintages"):
        tasks.trivial_control(task, root=tmp_path)  # no data to recompute from
    # Uncapped or exempt tasks never need a distance.
    assert tasks.trivial_control(_fake("UNRATE", "mom-rise", "2018-04", flips=False)) is False
    assert tasks.trivial_control(_fake("INDPRO", "mom-fall", "2018-04", flips=True)) is False


@pytest.mark.usefixtures("toy")
def test_distances_recomputed_after_load(tmp_path: Path) -> None:
    built = tasks.build_candidates(["TOY"], TOY_ROOT)
    tasks.save_tasks(tmp_path / "t.jsonl", built)
    assert "_threshold_distances" not in (tmp_path / "t.jsonl").read_text()
    loaded = tasks.load_tasks(tmp_path / "t.jsonl")
    assert loaded == built  # the distance is not a field
    for b, lo in zip(built, loaded, strict=True):
        assert tasks.threshold_distances(lo, root=TOY_ROOT) == tasks.threshold_distances(b)


@pytest.mark.skipif(not (data.DATA_DIR / "GDPC1.parquet").exists(), reason="no vintage data")
def test_every_capped_candidate_has_finite_distance() -> None:
    cands = tasks.build_candidates(tasks.SERIES, data.DATA_DIR)
    capped = [c for c in cands if (tp := tasks.template_for(c)) and tp.control_cap is not None]
    assert len(capped) > 500
    for c in capped:
        d = tasks.threshold_distances(c, root=Path("/nonexistent"))  # must be attached
        assert len(d) == 2 and all(math.isfinite(x) and x >= 1.0 - 1e-9 for x in d)


def test_select_pilot_skips_trivial_controls() -> None:
    pool = []
    months = [f"{y}-{m:02d}" for y in range(2016, 2020) for m in range(1, 13)]
    for i, ym in enumerate(months):
        far = i % 2 == 0  # half the controls are far from the line in both vintages
        for s, key in [("INDPRO", "mom-fall"), ("PCEPI", "yoy-above-2.5"),
                       ("PAYEMS", "avg3m-above-150k"), ("UNRATE", "mom-rise")]:  # fmt: skip
            d = (100.0, 100.0) if far else (2.0, 3.0)
            pool.append(_with_dist(_fake(s, key, ym, flips=False, yes=(i // 2) % 2 == 0), *d))
        pool.append(_fake("GDPC1", "growth-above-2", ym, flips=True, yes=i % 2 == 0))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pilot = tasks.select_pilot(pool, n=20, seed=0)
    controls = [t for t in pilot if not t.flips]
    assert len(controls) == 10
    assert not any(tasks.trivial_control(t) for t in controls)
    # UNRATE controls are exempt: far-from-the-line UNRATE tasks remain eligible.
    unrate = [t for t in controls if t.series_id == "UNRATE"]
    assert len(unrate) == 2


def test_readme_escapes_pipes_in_cells() -> None:
    assert tasks._cell("|a - b| >= 1") == "\\|a - b\\| >= 1"


# --- extend_pilot (60-task set) -------------------------------------------------


def _check_rules(chosen: list[Task]) -> None:
    """Every selection rule that does not need vintage data."""
    assert len({t.id for t in chosen}) == len(chosen)  # no duplicate ids
    assert len({(t.series_id, t.id[-7:]) for t in chosen}) == len(chosen)  # one per target
    assert all(2016 <= int(t.id[-7:-3]) <= 2025 for t in chosen)
    assert not any(t.flips and t.series_id == "UNRATE" for t in chosen)
    controls = [t for t in chosen if not t.flips]
    assert not any(tasks.covid_window_overlap(t) for t in controls)
    assert not any(tasks.trivial_control(t) for t in controls)


def _check_balance_60(chosen: list[Task]) -> None:
    assert len(chosen) == 60
    cells = Counter((t.flips, t.gold_as_of) for t in chosen)
    assert cells == {(True, True): 15, (True, False): 15, (False, True): 15, (False, False): 15}
    unrate = Counter(t.gold_as_of for t in chosen if t.series_id == "UNRATE")
    assert unrate == {True: 3, False: 3}
    assert sum(t.gold_as_of for t in chosen) == 30
    assert sum(t.gold_revised for t in chosen) == 30  # follows from the 4 cells


def test_extend_pilot_keeps_existing_and_balances() -> None:
    pool = _pool()
    base = tasks.select_pilot(pool, n=20, seed=0)
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # a well-stocked pool meets every quota
        ext = tasks.extend_pilot(base, pool, n_total=60, seed=0)
    by_id = {t.id: t for t in ext}
    assert all(by_id[t.id] is t for t in base)  # the 20 are kept, same objects
    _check_balance_60(ext)
    _check_rules(ext)
    assert ext[:20] == base  # base first, in its given order
    assert ext[20:] == sorted(ext[20:], key=lambda t: t.id)  # then new ones by id
    assert len({t.series_id for t in ext}) == 5
    assert len({t.id[-7:-3] for t in ext}) == 10  # every year 2016-2025


def test_extend_pilot_keeps_existing_not_in_candidates() -> None:
    pool = _pool()
    odd = _fake("INDPRO", "f", "2016-02", flips=True, yes=True)  # not a candidate
    ext = tasks.extend_pilot([odd], pool, n_total=10, seed=0)
    assert odd in ext and len(ext) == 10
    # Its (series, period) is taken: no other INDPRO 2016-02 task was added.
    assert [t for t in ext if (t.series_id, t.id[-7:]) == ("INDPRO", "2016-02")] == [odd]


def test_extend_pilot_quota_net_of_existing() -> None:
    pool = _pool()
    # 6 existing flip/as-of Yes: the 60-set target is 15, so 9 more are added.
    base = [t for t in pool if t.flips and t.gold_as_of and t.series_id != "UNRATE"][:6]
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        ext = tasks.extend_pilot(base, pool, n_total=60, seed=0)
    _check_balance_60(ext)


def test_extend_pilot_deterministic_and_seeded() -> None:
    pool = _pool()
    base = tasks.select_pilot(pool, n=20, seed=0)
    a = tasks.extend_pilot(base, pool, n_total=60, seed=0)
    assert a == tasks.extend_pilot(base, pool, n_total=60, seed=0)
    rev = tasks.extend_pilot(list(reversed(base)), list(reversed(pool)), 60, seed=0)
    assert rev[:20] == list(reversed(base)) and rev[20:] == a[20:]  # base order kept
    assert a == tasks.extend_pilot(base, pool + pool, n_total=60, seed=0)  # duplicates dropped
    b = tasks.extend_pilot(base, pool, n_total=60, seed=1)
    assert {t.id for t in a} != {t.id for t in b}
    assert {t.id for t in base} <= {t.id for t in b}


def test_extend_pilot_short_stratum_warns_with_cells() -> None:
    pool = _pool()
    base = tasks.select_pilot(pool, n=20, seed=0)
    no_new_flip_yes = [t for t in pool if not (t.flips and t.gold_as_of)]
    with pytest.warns(UserWarning, match=r"flip/as-of Yes 5/15.*actual cells: flip/as-of Yes 5"):
        ext = tasks.extend_pilot(base, no_new_flip_yes, n_total=60, seed=0)
    assert len(ext) == 60
    assert sum(t.flips for t in ext) == 30  # sibling stratum keeps flips at 30
    _check_rules(ext)


def test_extend_pilot_rejects_bad_input() -> None:
    pool = _pool()
    base = tasks.select_pilot(pool, n=20, seed=0)
    with pytest.raises(ValueError, match="n_total"):
        tasks.extend_pilot(base, pool, n_total=10)
    with pytest.raises(ValueError, match="duplicate"):
        tasks.extend_pilot(base + base[:1], pool, n_total=60)


def test_extend_pilot_skips_covid_and_trivial_controls() -> None:
    pool = []
    months = [f"{y}-{m:02d}" for y in range(2018, 2023) for m in range(1, 13)]
    for i, ym in enumerate(months):
        far = i % 3 == 0
        for s, key in [("INDPRO", "mom-fall"), ("PCEPI", "yoy-above-2.5"),
                       ("PAYEMS", "avg3m-above-150k"), ("UNRATE", "mom-rise")]:  # fmt: skip
            d = (100.0, 100.0) if far else (2.0, 3.0)
            pool.append(_with_dist(_fake(s, key, ym, flips=False, yes=(i // 2) % 2 == 0), *d))
        pool.append(_fake("GDPC1", "growth-above-2", ym, flips=True, yes=i % 2 == 0))
        pool.append(_fake("UNRATE", "mom-rise", ym, flips=True, yes=True))  # never drawn
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        base = tasks.select_pilot(pool, n=20, seed=0)
        ext = tasks.extend_pilot(base, pool, n_total=60, seed=0)
    _check_rules(ext)
    assert any(not t.flips and tasks.covid_window_overlap(t) for t in pool)
    assert any(tasks.trivial_control(t) for t in pool)


@pytest.mark.parametrize(("n", "expected"), [(20, 2), (40, 4), (60, 6), (4, 2), (2, 1)])
def test_default_n_unrate(n: int, expected: int) -> None:
    assert tasks.default_n_unrate(n) == expected


def test_strata_quotas_60() -> None:
    q = tasks._strata_quotas(60, 6)
    assert list(q.values()) == [15, 15, 3, 3, 12, 12]
    assert tasks._strata_quotas(20, 2) == dict(zip(q, [5, 5, 1, 1, 4, 4], strict=True))


# --- CLI ----------------------------------------------------------------------


def test_cli_help_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(tasks, "TASKS_DIR", tmp_path)

    def boom(*a: object, **k: object) -> None:
        raise AssertionError("--help must not build candidates")

    monkeypatch.setattr(tasks, "build_candidates", boom)
    with pytest.raises(SystemExit) as exc:
        tasks.main(["--help"])
    assert exc.value.code == 0
    assert "--extend-from" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_cli_help_subprocess_leaves_repo_files_untouched() -> None:
    files = [tasks.TASKS_DIR / n for n in ("pilot.jsonl", "README.md")]
    files = [f for f in files if f.exists()]
    before = {f: (f.stat().st_mtime_ns, f.read_bytes()) for f in files}
    res = subprocess.run(
        [sys.executable, "-m", "vintagebench.tasks", "--help"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert res.returncode == 0 and "usage:" in res.stdout
    assert {f: (f.stat().st_mtime_ns, f.read_bytes()) for f in files} == before


def test_cli_extend_refuses_overwriting_base(tmp_path: Path) -> None:
    base = tmp_path / "pilot.jsonl"
    base.write_text("")
    with pytest.raises(SystemExit) as exc:
        tasks.main(["--extend-from", str(base), "--out", str(base)], root=TOY_ROOT)
    assert exc.value.code == 2
    assert base.read_text() == ""


@pytest.mark.usefixtures("toy")
def test_cli_extend_toy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks, "SERIES", ("TOY",))
    # TOY revisions are 2 months after as-of: lift the gap rule to exercise the CLI.
    monkeypatch.setattr(tasks, "MIN_REVISION_GAP_DAYS", 0)
    cands = tasks.build_candidates(["TOY"], TOY_ROOT)
    base = sorted(cands, key=lambda t: t.id)[:2]
    tasks.save_tasks(tmp_path / "base.jsonl", base)
    out, readme = tmp_path / "ext.jsonl", tmp_path / "R.md"
    argv = ["--extend-from", str(tmp_path / "base.jsonl"), "--n", "6", "--out", str(out),
            "--readme-out", str(readme)]  # fmt: skip
    with pytest.warns(UserWarning, match="extend_pilot: strata short"):  # 1 flip, no UNRATE
        tasks.main(argv, root=TOY_ROOT)
    ext = tasks.load_tasks(out)
    assert len(ext) == 6 and ext[:2] == base
    base_lines = (tmp_path / "base.jsonl").read_text().splitlines()
    assert out.read_text().splitlines()[:2] == base_lines  # byte-identical, first
    text = readme.read_text()
    assert "# VintageBench tasks: 6-task set" in text and "## Clusters" in text
    clusters = tasks.task_clusters(ext)
    for t in ext:
        tag = "pilot20" if t in base else "new"
        row = f"| {'yes' if t.flips else 'no'} | {tag} | {clusters[t.id]} |"
        assert row in text and f"| {t.id} |" in text


@pytest.mark.usefixtures("toy")
def test_cli_extend_toy_gap_rule_blocks_short_revisions(tmp_path: Path) -> None:
    cands = tasks.build_candidates(["TOY"], TOY_ROOT)
    assert not any(tasks.revision_gap_ok(c) for c in cands)  # 2021-01-15 -> 2021-03-15
    base = sorted(cands, key=lambda t: t.id)[:2]
    with pytest.warns(UserWarning, match="got 2/6 tasks"):
        ext = tasks.extend_pilot(base, cands, n_total=6, seed=0)
    assert ext == base  # base kept even though it fails the gap rule


# --- the committed task files (real vintage data, no network) --------------------

HAVE_DATA = (data.DATA_DIR / "GDPC1.parquet").exists()


@pytest.fixture(scope="module")
def real_candidates() -> list[Task]:
    return tasks.build_candidates(tasks.SERIES, data.DATA_DIR)


@pytest.mark.skipif(not HAVE_DATA, reason="no vintage data")
def test_default_cli_reproduces_pilot_and_readme(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_tasks = tasks.TASKS_DIR
    monkeypatch.setattr(tasks, "TASKS_DIR", tmp_path)
    tasks.main([])
    for name in ("pilot.jsonl", "README.md"):
        assert (tmp_path / name).read_bytes() == (repo_tasks / name).read_bytes()


@pytest.mark.skipif(not HAVE_DATA, reason="no vintage data")
def test_pilot60_file_reproduces_and_holds_rules(
    tmp_path: Path, real_candidates: list[Task]
) -> None:
    repo = tasks.TASKS_DIR
    pilot = tasks.load_tasks(repo / "pilot.jsonl")
    p60 = tasks.load_tasks(repo / "pilot60.jsonl")
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # every stratum is filled on the real data
        regen = tasks.extend_pilot(pilot, real_candidates, n_total=60, seed=0)
    assert regen == p60
    tasks.save_tasks(tmp_path / "p60.jsonl", regen)
    assert (tmp_path / "p60.jsonl").read_bytes() == (repo / "pilot60.jsonl").read_bytes()
    # The 20 are kept exactly and first, in pilot.jsonl order; then new ones by id.
    lines60 = (repo / "pilot60.jsonl").read_text().splitlines()
    assert lines60[:20] == (repo / "pilot.jsonl").read_text().splitlines()
    assert len(lines60) == 60
    new = p60[20:]
    assert [t.id for t in new] == sorted(t.id for t in new)
    assert all(tasks.revision_gap_ok(t) for t in new)  # gap rule, new tasks only
    assert _avoidable_overlaps(p60, real_candidates, {t.id for t in pilot}) == []
    _check_balance_60(p60)
    # Gold, flips, materiality: every task equals a programmatically built candidate.
    by_id = {c.id: c for c in real_candidates}
    assert all(by_id.get(t.id) == t for t in p60)
    for t in p60:  # templates and materiality margins in both vintages
        tp = tasks.template_for(t)
        assert tp is not None and t.question == tp.question(T(t.id[-7:] + "-01"))
        if tp.margin is not None:
            assert min(tasks.threshold_distances(t)) >= 1.0 - 1e-9
    _check_rules(p60)
    years = Counter(t.id[-7:-3] for t in p60)
    assert set(years) == {str(y) for y in range(2016, 2026)}
    assert {t.series_id for t in p60} == set(tasks.SERIES)


@pytest.mark.skipif(not HAVE_DATA, reason="no vintage data")
def test_readme60_matches_render(real_candidates: list[Task]) -> None:
    repo = tasks.TASKS_DIR
    pilot = tasks.load_tasks(repo / "pilot.jsonl")
    p60 = tasks.load_tasks(repo / "pilot60.jsonl")
    text = tasks.render_extended_readme(
        real_candidates, p60, pilot, 0, repo / "pilot60.jsonl", repo / "pilot.jsonl"
    )
    assert (repo / "README60.md").read_text() == text
    assert tasks.EXTEND_COMMAND in text


# --- revision gap, computation windows, overlap avoidance, clusters ---------------


def _avoidable_overlaps(chosen: list[Task], candidates: list[Task], base: set[str]) -> list[str]:
    """New tasks that overlap another chosen task although a free candidate in the
    same stratum overlaps none of the other chosen tasks (so greedy would have
    preferred it: the chosen set only grows during selection)."""
    ids = {t.id for t in chosen}
    taken = {(t.series_id, t.id[-7:]) for t in chosen}
    free = [
        u
        for u in candidates
        if u.id not in ids
        and (u.series_id, u.id[-7:]) not in taken
        and tasks._selectable(u)
        and tasks.revision_gap_ok(u)
        and 2016 <= int(u.id[-7:-3]) <= 2025
    ]
    bad = []
    for t in chosen:
        rest = [o for o in chosen if o.id != t.id]
        if t.id in base or not any(tasks.windows_overlap(t, o) for o in rest):
            continue
        name = tasks._stratum_name(t)
        alts = [u for u in free if tasks._stratum_name(u) == name]
        if any(not any(tasks.windows_overlap(u, o) for o in rest) for u in alts):
            bad.append(t.id)
    return bad


@pytest.mark.parametrize(
    ("as_of", "revised", "ok"),
    [
        ("2020-01-10", "2021-01-09", True),  # 365 days (2020 is a leap year)
        ("2021-01-10", "2022-01-10", True),  # 365 days
        ("2021-01-10", "2022-01-09", False),  # 364 days
        ("2025-06-06", "2026-02-06", False),  # "else the latest vintage" fallback
    ],
)
def test_revision_gap_ok(as_of: str, revised: str, ok: bool) -> None:
    t = dataclasses.replace(
        _fake("INDPRO", "mom-fall", "2020-01", flips=True), as_of_date=as_of, revision_date=revised
    )
    assert tasks.revision_gap_ok(t) is ok


def test_extend_pilot_skips_short_gap_new_tasks() -> None:
    pool = _pool()
    base = tasks.select_pilot(pool, n=20, seed=0)
    short = [dataclasses.replace(t, revision_date=t.as_of_date) for t in pool]
    with pytest.warns(UserWarning, match="got 20/60 tasks"):
        ext = tasks.extend_pilot(base, short, n_total=60, seed=0)
    assert ext == base


@pytest.mark.parametrize(
    ("task_id", "window"),
    [
        ("indpro-mom-fall-2019-03", ["2019-02", "2019-03"]),
        ("unrate-mom-rise-2019-03", ["2019-02", "2019-03"]),
        ("gdpc1-qoq-shrink-2019-04", ["2019-01", "2019-04"]),
        ("gdpc1-growth-above-2-2019-01", ["2018-10", "2019-01"]),
        ("payems-avg3m-above-100k-2025-04", ["2025-01", "2025-02", "2025-03", "2025-04"]),
        ("payems-weakest-12m-2022-10", [f"{y}-{m:02d}" for y, m in
                                        [(2021, 10), (2021, 11), (2021, 12)]
                                        + [(2022, k) for k in range(1, 11)]]),
        ("pcepi-yoy-above-2.5-2024-01", ["2023-01", *[f"2023-{m:02d}" for m in range(2, 13)],
                                         "2024-01"]),
    ],
)  # fmt: skip
def test_computation_window(task_id: str, window: list[str]) -> None:
    series = task_id.split("-")[0].upper()
    task = _fake(series, task_id[len(series) + 1 : -8], task_id[-7:], flips=False)
    assert [f"{d:%Y-%m}" for d in tasks.computation_window(task)] == window


def test_windows_overlap() -> None:
    a = _fake("INDPRO", "mom-fall", "2019-02", flips=True)
    b = _fake("INDPRO", "mom-fall", "2019-03", flips=True)  # shares February
    c = _fake("INDPRO", "mom-fall", "2019-04", flips=True)  # Mar-Apr: disjoint from a
    p1 = _fake("PAYEMS", "weakest-12m", "2022-09", flips=True)
    p2 = _fake("PAYEMS", "avg3m-above-100k", "2023-09", flips=True)  # Jun-Sep 2023
    p3 = _fake("PAYEMS", "avg3m-above-100k", "2022-12", flips=True)  # Sep-Dec 2022
    u = _fake("UNRATE", "mom-rise", "2019-03", flips=False)
    assert tasks.windows_overlap(a, b) and tasks.windows_overlap(b, c)
    assert not tasks.windows_overlap(a, c)
    assert not tasks.windows_overlap(b, u)  # other series never overlap
    assert tasks.windows_overlap(p1, p3) and not tasks.windows_overlap(p1, p2)  # cross-template
    g1 = _fake("GDPC1", "qoq-shrink", "2019-01", flips=True)
    g2 = _fake("GDPC1", "growth-above-2", "2019-04", flips=True)  # shares 2019 Q1
    g3 = _fake("GDPC1", "growth-above-2", "2019-07", flips=True)
    assert tasks.windows_overlap(g1, g2) and not tasks.windows_overlap(g1, g3)


def test_task_clusters() -> None:
    rows = [
        _fake("INDPRO", "mom-fall", "2019-02", flips=True),
        _fake("INDPRO", "mom-fall", "2019-04", flips=True),
        _fake("INDPRO", "mom-fall", "2019-03", flips=False),  # links 02 and 04 (a chain)
        _fake("INDPRO", "mom-fall", "2019-06", flips=True),  # alone
        _fake("UNRATE", "mom-rise", "2019-03", flips=False),  # other series: alone
    ]
    cl = tasks.task_clusters(rows)
    assert cl == {
        "indpro-mom-fall-2019-02": "INDPRO:2019-01..2019-04",
        "indpro-mom-fall-2019-03": "INDPRO:2019-01..2019-04",
        "indpro-mom-fall-2019-04": "INDPRO:2019-01..2019-04",
        "indpro-mom-fall-2019-06": "INDPRO:2019-05..2019-06",
        "unrate-mom-rise-2019-03": "UNRATE:2019-02..2019-03",
    }
    assert tasks.task_clusters(list(reversed(rows))) == cl  # order-independent
    assert tasks.task_clusters([]) == {}


def _indpro_pool(flip_months: Iterable[int] | None = None) -> list[Task]:
    """INDPRO mom-fall for every month 2016-2025 (flips where i % 4 == 0 unless
    ``flip_months`` is given) plus UNRATE controls; controls carry distances."""
    out = []
    months = [f"{y}-{m:02d}" for y in range(2016, 2026) for m in range(1, 13)]
    flip_set = set(range(0, len(months), 4)) if flip_months is None else set(flip_months)
    for i, ym in enumerate(months):
        flips = i in flip_set
        t = _fake(
            "INDPRO", "mom-fall", ym, flips=flips, yes=(i // 4) % 2 == 0 if flips else i % 2 == 0
        )
        out.append(t if flips else _with_dist(t, 2.0, 3.0))
        out.append(_fake("UNRATE", "mom-rise", ym, flips=False, yes=i % 2 == 0))
    return out


def test_extend_pilot_avoids_overlap_when_possible() -> None:
    pool = _indpro_pool()
    base = [t for t in pool if t.id == "indpro-mom-fall-2016-01"]
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        ext = tasks.extend_pilot(base, pool, n_total=40, seed=0)
    assert len(ext) == 40
    cl = tasks.task_clusters(ext)
    assert len(set(cl.values())) == 40  # no two chosen tasks overlap
    assert _avoidable_overlaps(ext, pool, {t.id for t in base}) == []
    # Without the penalty (select_pilot) the same pool does produce overlaps.
    plain = tasks.select_pilot(pool, n=40, seed=0)
    assert len(set(tasks.task_clusters(plain).values())) < 40


def test_extend_pilot_allows_overlap_only_when_forced() -> None:
    # Only 4 flips exist, in two adjacent pairs: filling 4 flip slots forces overlaps.
    pool = _indpro_pool(flip_months=[24, 25, 60, 61])  # 2018-01/02, 2021-01/02
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # the flip strata are short of 10
        ext = tasks.extend_pilot([], pool, n_total=20, seed=0)
    flips = [t for t in ext if t.flips]
    assert sorted(t.id[-7:] for t in flips) == ["2018-01", "2018-02", "2021-01", "2021-02"]
    cl = tasks.task_clusters(ext)
    assert cl["indpro-mom-fall-2018-01"] == cl["indpro-mom-fall-2018-02"]
    assert _avoidable_overlaps(ext, pool, set()) == []
