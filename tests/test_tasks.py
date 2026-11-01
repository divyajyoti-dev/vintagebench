"""Tests for vintagebench.tasks (v1). Synthetic data only, never RTDSM values; offline.

Real-data checks at the end skip when data/raw is missing.
"""

from __future__ import annotations

import json
import random
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from vintagebench import data, tasks
from vintagebench.tasks import Candidate, Task

D = date
START = D(2018, 1, 1)
LATEST = D(2026, 9, 30)


def monthly(values: list[float], start: date = START) -> dict[date, float]:
    return {tasks.shift(start, i): v for i, v in enumerate(values)}


def quarterly(values: list[float], start: date = START) -> dict[date, float]:
    return {tasks.shift(start, 3 * i): v for i, v in enumerate(values)}


def levels_from_changes(changes: list[float], start: date = START) -> dict[date, float]:
    lv = [1000.0]
    for c in changes:
        lv.append(lv[-1] + c)
    return monthly(lv, start)


# --- helpers ----------------------------------------------------------------------------


def test_shift_and_snapshot() -> None:
    assert tasks.shift(D(2019, 11, 1), 3) == D(2020, 2, 1)
    assert tasks.shift(D(2019, 1, 1), -13) == D(2017, 12, 1)
    s = tasks.as_snapshot(
        {
            "2019-01-01": "1.5",
            pd.Timestamp("2019-02-01"): float("nan"),
            D(2019, 3, 1): None,
            D(2019, 4, 1): "x",
            D(2019, 5, 1): 2,
        }
    )
    assert s == {D(2019, 1, 1): 1.5, D(2019, 5, 1): 2.0}


def test_quantities() -> None:
    s = monthly([100.0, 101.0, 103.0, 106.0])
    assert tasks.level_change(s, D(2018, 4, 1)) == 3
    assert tasks.level_change(s, D(2018, 1, 1)) is None
    assert tasks.avg_change_3m(s, D(2018, 4, 1)) == pytest.approx(2.0)
    assert tasks.pct_change(s, D(2018, 2, 1)) == pytest.approx(1.0)
    y = monthly([100.0] + [0.0] * 11 + [102.5])
    del y[D(2018, 6, 1)]
    assert tasks.yoy_pct(y, D(2019, 1, 1)) == pytest.approx(2.5)
    q = quarterly([100.0, 101.0])
    assert tasks.annualized_qoq_pct(q, D(2018, 4, 1)) == pytest.approx(100 * (1.01**4 - 1))
    assert tasks.rounded_change(monthly([4.04, 4.06]), D(2018, 2, 1)) == pytest.approx(0.1)


# --- gold functions ---------------------------------------------------------------------


def test_real_gdp_shrank() -> None:
    s = quarterly([100.0, 99.0, 99.0, 99.5])
    assert tasks.real_gdp_shrank(s, D(2018, 4, 1)) is True
    assert tasks.real_gdp_shrank(s, D(2018, 7, 1)) is False  # tie -> no
    assert tasks.real_gdp_shrank(s, D(2018, 10, 1)) is False
    assert tasks.real_gdp_shrank(s, D(2018, 1, 1)) is None


@pytest.mark.parametrize("rate,expected", [(1.9, False), (2.1, True), (2.0, False)])
def test_real_gdp_grew_faster_than(rate: float, expected: bool) -> None:
    s = quarterly([100.0, 100.0 * (1 + rate / 100) ** 0.25])
    assert tasks.real_gdp_grew_faster_than(s, D(2018, 4, 1), 2.0) is expected
    assert tasks.real_gdp_grew_faster_than(quarterly([100.0]), D(2018, 4, 1), 2.0) is None


def test_payrolls_weakest_in_12m() -> None:
    base = [150, 120, 200, 90, 180, 160, 140, 210, 130, 170, 110]  # 11 earlier changes
    s = levels_from_changes(base + [89], D(2018, 2, 1))  # levels 2018-02 .. 2019-02
    t = D(2019, 2, 1)
    assert tasks.payrolls_weakest_in_12m(s, t) is True
    assert (
        tasks.payrolls_weakest_in_12m(levels_from_changes(base + [90], D(2018, 2, 1)), t) is False
    )  # tie with the weakest earlier month -> no
    assert (
        tasks.payrolls_weakest_in_12m(levels_from_changes(base + [95], D(2018, 2, 1)), t) is False
    )
    s.pop(D(2018, 6, 1))
    assert tasks.payrolls_weakest_in_12m(s, t) is None


@pytest.mark.parametrize("thr,expected", [(100.0, True), (150.0, False), (120.0, False)])
def test_payrolls_3m_avg_above(thr: float, expected: bool) -> None:
    s = monthly([1000.0, 1100.0, 1220.0, 1360.0])  # avg (1360 - 1000) / 3 = 120
    assert tasks.payrolls_3m_avg_above(s, D(2018, 4, 1), thr) is expected
    assert tasks.payrolls_3m_avg_above(s, D(2018, 3, 1), thr) is None


def test_industrial_production_fell() -> None:
    s = monthly([100.0, 99.9, 99.9, 100.2])
    assert tasks.industrial_production_fell(s, D(2018, 2, 1)) is True
    assert tasks.industrial_production_fell(s, D(2018, 3, 1)) is False  # tie
    assert tasks.industrial_production_fell(s, D(2018, 4, 1)) is False
    assert tasks.industrial_production_fell(s, D(2018, 1, 1)) is None


@pytest.mark.parametrize(
    "level,thr,expected",
    [(102.6, 2.5, True), (102.4, 2.5, False), (103.1, 3.0, True), (102.0, 2.0, False)],
)
def test_cpi_12m_above(level: float, thr: float, expected: bool) -> None:
    s = {D(2018, 1, 1): 100.0, D(2019, 1, 1): level}
    assert tasks.cpi_12m_above(s, D(2019, 1, 1), thr) is expected
    assert tasks.cpi_12m_above(s, D(2019, 2, 1), thr) is None


@pytest.mark.parametrize(
    "level,thr,expected",
    [(100.25, 0.2, True), (100.15, 0.2, False), (100.35, 0.3, True), (100.3, 0.3, False)],
)
def test_cpi_1m_above(level: float, thr: float, expected: bool) -> None:
    s = monthly([100.0, level])
    assert tasks.cpi_1m_above(s, D(2018, 2, 1), thr) is expected
    assert tasks.cpi_1m_above(s, D(2018, 1, 1), thr) is None


def test_unemployment_rose() -> None:
    s = monthly([4.0, 4.1, 4.1, 4.0, 4.0000001, 4.04, 4.06])
    assert tasks.unemployment_rose(s, D(2018, 2, 1)) is True
    assert tasks.unemployment_rose(s, D(2018, 3, 1)) is False  # unchanged
    assert tasks.unemployment_rose(s, D(2018, 4, 1)) is False  # fell
    assert tasks.unemployment_rose(s, D(2018, 5, 1)) is False  # float noise
    assert tasks.unemployment_rose(s, D(2018, 6, 1)) is False  # 4.04 rounds to 4.0
    assert tasks.unemployment_rose(s, D(2018, 7, 1)) is True  # 4.06 rounds to 4.1
    assert tasks.unemployment_rose(s, D(2018, 1, 1)) is None


def _random_snapshot(tp: tasks.Template, rng: random.Random, period: date) -> dict[date, float]:
    obs = tp.window(period)
    base = {"EMPLOY": 150000.0, "RUC": 4.0, "PCPI": 250.0}.get(tp.series_id, 100.0)
    if tp.series_id == "RUC":
        return {
            o: round(base + rng.choice([-0.2, -0.1, 0, 0.1, 0.2]) * i, 1) for i, o in enumerate(obs)
        }
    if tp.series_id == "EMPLOY":
        out, lv = {}, base
        for o in obs:
            lv += rng.randint(-50, 300)
            out[o] = lv
        return out
    return {o: base * (1 + rng.uniform(-0.01, 0.01)) for o in obs}


@pytest.mark.parametrize("key", list(tasks.TEMPLATES))
def test_distance_sign_matches_gold(key: str) -> None:
    tp, rng = tasks.TEMPLATES[key], random.Random(key)
    period = D(2019, 4, 1)
    for _ in range(300):
        s = _random_snapshot(tp, rng, period)
        for thr in tp.thresholds:
            g, d = tp.gold(s, period, thr), tp.distance(s, period, thr)
            assert g is not None and d is not None
            if abs(d) > 1e-6:
                assert g is (d > 0)


# --- templates and questions ------------------------------------------------------------


def test_questions_are_plain_and_round() -> None:
    for tp in tasks.TEMPLATE_LIST:
        for thr in tp.thresholds:
            assert thr == round(thr, 1)
            q = tp.question(D(2019, 4, 1), thr)
            assert q.endswith("?") and q.startswith(("Did", "Was"))
            for sid in data.SERIES_IDS:
                assert sid not in q
            for formula in ("level(", "/", "=", "annualized"):
                assert formula not in q
    assert tasks.TEMPLATES["gdp_shrink"].question(D(2018, 10, 1), 0.0) == (
        "Did US real GDP shrink in 2018 Q4?"
    )
    q = tasks.TEMPLATES["payroll_avg3m_above"].question(D(2019, 5, 1), 150.0)
    assert "150,000" in q and "May 2019" in q
    assert "2.5%" in tasks.TEMPLATES["cpi_12m_above"].question(D(2019, 5, 1), 2.5)


def _task(
    key: str,
    period: str,
    thr: float | None = None,
    kind: str = "control",
    series: str | None = None,
) -> Task:
    tp = tasks.TEMPLATES[key]
    p = date.fromisoformat(period)
    thr = tp.thresholds[0] if thr is None else thr
    return Task(
        id=tasks.task_id(tp, p, thr) if series is None else f"{series}-{period}",
        series_id=series or tp.series_id,
        template=key,
        period=period,
        threshold=thr,
        as_of_date="2019-06-30",
        revision_date="2026-09-30",
        question=tp.question(p, thr),
        answer_type="yes_no",
        kind=kind,
    )


def test_task_ids() -> None:
    assert _task("gdp_shrink", "2018-10-01").id == "routput-gdp_shrink-2018q4"
    assert _task("payroll_avg3m_above", "2019-05-01", 150.0).id == (
        "employ-payroll_avg3m_above-150k-2019-05"
    )
    assert _task("cpi_12m_above", "2019-05-01", 2.5).id == "pcpi-cpi_12m_above-2.5pct-2019-05"


@pytest.mark.parametrize("key,period,keys,window", [
    ("gdp_shrink", "2018-10-01", ["2018-07", "2018-10"], ["2018-07", "2018-10"]),
    ("gdp_growth_above", "2018-01-01", ["2017-10", "2018-01"], ["2017-10", "2018-01"]),
    ("ip_fell", "2019-01-01", ["2018-12", "2019-01"], ["2018-12", "2019-01"]),
    ("unemployment_rose", "2019-03-01", ["2019-02", "2019-03"], ["2019-02", "2019-03"]),
    ("cpi_1m_above", "2019-03-01", ["2019-02", "2019-03"], ["2019-02", "2019-03"]),
    ("payroll_avg3m_above", "2019-05-01", ["2019-02", "2019-05"],
     ["2019-02", "2019-03", "2019-04", "2019-05"]),
    ("cpi_12m_above", "2019-05-01", ["2018-05", "2019-05"],
     [f"{d:%Y-%m}" for d in (tasks.shift(D(2019, 5, 1), k) for k in range(-12, 1))]),
])  # fmt: skip
def test_key_observations_and_window(
    key: str, period: str, keys: list[str], window: list[str]
) -> None:
    t = _task(key, period)
    assert [f"{d:%Y-%m}" for d in tasks.key_observations(t)] == keys
    assert [f"{d:%Y-%m}" for d in tasks.computation_window(t)] == window


def test_weakest_key_observations() -> None:
    t = _task("payroll_weakest_12m", "2019-05-01")
    obs = tasks.key_observations(t)
    assert len(obs) == 13 and obs[0] == D(2018, 5, 1) and obs[-1] == D(2019, 5, 1)


def test_readme_labels() -> None:
    tp = tasks.TEMPLATES
    assert tasks.key_observations_label(tp["payroll_avg3m_above"]) == "t-3, t"
    assert tasks.window_label(tp["payroll_avg3m_above"]) == "t-3..t (4 months)"
    assert tasks.key_observations_label(tp["payroll_weakest_12m"]) == "t-12..t (13 obs)"
    assert tasks.key_observations_label(tp["gdp_shrink"]) == "q-1, q"
    assert tasks.window_label(tp["gdp_shrink"]) == "q-1..q (2 quarters)"
    assert tasks.window_label(tp["cpi_12m_above"]) == "t-12..t (13 months)"


def test_rounding_boundary_flips() -> None:
    def ruc(kind: str, d1: float, d2: float, period: str = "2019-03-01") -> Task:
        return replace(
            _task("unemployment_rose", period, kind=kind),
            id=f"{kind}{d1}{d2}",
            margin_as_of=d1,
            margin_revised=d2,
        )

    rows = [
        ruc("flip", -0.05, 0.05),  # unchanged -> +0.1: boundary
        ruc("flip", 0.05, -0.05),  # +0.1 -> unchanged: boundary
        ruc("flip", 0.15, -0.05),  # +0.2 -> unchanged: not boundary
        ruc("flip", -0.15, 0.05),  # -0.1 -> +0.1: not boundary
        ruc("control", -0.05, -0.05),  # not a flip
        _task("ip_fell", "2019-03-01", kind="flip"),  # other template
    ]
    assert tasks.rounding_boundary_flips(rows) == (2, 4)


def test_implied_answer() -> None:
    t = _task("ip_fell", "2019-02-01")
    assert tasks.implied_answer(t, {D(2019, 1, 1): 100.0, D(2019, 2, 1): 99.5}) is True
    assert tasks.implied_answer(t, {"2019-01-01": 100.0, "2019-02-01": 100.5}) is False
    assert tasks.implied_answer(t, {D(2019, 2, 1): 99.5}) is None
    assert tasks.implied_answer(t, {D(2019, 1, 1): "n/a", D(2019, 2, 1): 99.5}) is None
    c = _task("payroll_avg3m_above", "2019-05-01", 150.0)
    assert tasks.implied_answer(c, {"2019-02-01": 1000, "2019-05-01": 1500}) is True
    assert tasks.implied_answer(c, {"2019-02-01": 1000, "2019-05-01": 1300}) is False


@pytest.mark.parametrize("key,period,touches", [
    ("ip_fell", "2020-01-01", False), ("ip_fell", "2020-02-01", True),
    ("ip_fell", "2021-04-01", True), ("ip_fell", "2021-05-01", False),
    ("cpi_12m_above", "2022-03-01", True), ("cpi_12m_above", "2022-04-01", False),
    ("cpi_12m_above", "2020-01-01", False),
    ("payroll_avg3m_above", "2021-06-01", True), ("payroll_avg3m_above", "2021-07-01", False),
    ("payroll_weakest_12m", "2022-03-01", True), ("payroll_weakest_12m", "2022-04-01", False),
    ("gdp_shrink", "2019-10-01", False), ("gdp_shrink", "2020-01-01", True),
    ("gdp_growth_above", "2021-04-01", True), ("gdp_growth_above", "2021-07-01", False),
])  # fmt: skip
def test_covid_exclusion_window(key: str, period: str, touches: bool) -> None:
    assert tasks.covid_window_overlap(_task(key, period)) is touches


def test_overlap_and_clusters() -> None:
    a = _task("payroll_avg3m_above", "2019-02-01")
    b = _task("payroll_avg3m_above", "2019-05-01")  # shares 2019-02
    c = _task("payroll_avg3m_above", "2019-09-01")
    w = _task("payroll_weakest_12m", "2020-01-01")  # spans 2019-01..2020-01
    u = _task("unemployment_rose", "2019-05-01")
    assert tasks.windows_overlap(a, b) and not tasks.windows_overlap(a, c)
    assert not tasks.windows_overlap(b, u)  # other series never overlap
    rows = [a, b, c, u]
    cl = tasks.task_clusters(rows)
    assert cl[a.id] == cl[b.id] != cl[c.id] and cl[u.id].startswith("RUC")
    assert tasks.task_clusters(list(reversed(rows))) == cl
    assert len(set(tasks.task_clusters([a, b, c, w]).values())) == 1
    assert tasks.overlap_pairs([a, b, c]) == 1
    assert tasks.task_clusters([]) == {}


# --- synthetic vintages on disk ---------------------------------------------------------


def _write(root: Path, sid: str, snaps: dict[date, dict[date, float]]) -> None:
    rows = [
        (sid, o, f"{sid}{vd:%y}M{vd.month}", vd, v)
        for vd, snap in snaps.items()
        for o, v in snap.items()
    ]
    root.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=data.COLUMNS).to_parquet(root / f"{sid}.parquet", index=False)


def _ip_root(tmp_path: Path) -> Path:
    """Synthetic IPT: baseline vintage 2015-12-31 with obs 2015-01..2015-11; monthly
    vintages through 2018-12; each vintage adds the previous month. Revisions:
    - 2016-05 (first release 2016-06-30) rises; revised to fall in 2016-08-31.
    - 2016-03 window identical through 2016-06-30, then revised slightly.
    """
    ends = [D(2015, 12, 31)] + [
        (tasks.shift(D(2016, 1, 1), i + 1) - timedelta(days=1)) for i in range(36)
    ]
    snaps: dict[date, dict[date, float]] = {}
    for vd in ends:
        last = tasks.shift(D(vd.year, vd.month, 1), -1)
        snap = {}
        o = D(2015, 1, 1)
        i = 0
        while o <= last:
            snap[o] = 100.0 + 0.2 * i  # always rising
            o, i = tasks.shift(o, 1), i + 1
        snaps[vd] = snap
    for vd, snap in snaps.items():
        if vd >= D(2016, 8, 31) and D(2016, 5, 1) in snap:
            snap[D(2016, 5, 1)] = snap[D(2016, 4, 1)] - 0.2  # May now falls
        if vd >= D(2016, 7, 31) and D(2016, 3, 1) in snap:
            snap[D(2016, 3, 1)] += 0.01
    _write(tmp_path, "IPT", snaps)
    return tmp_path


def test_build_candidates_dates_and_flags(tmp_path: Path) -> None:
    root = _ip_root(tmp_path)
    cands = {c.id: c for c in tasks.build_candidates(["IPT"], root)}
    assert all(c.period >= tasks.PERIOD_START for c in cands.values())
    assert "ipt-ip_fell-2015-12" not in cands
    may = cands["ipt-ip_fell-2016-05"]
    assert may.as_of == D(2016, 6, 30)  # first release
    assert may.latest == D(2018, 12, 31)
    assert may.year_later == D(2017, 6, 30)
    assert (may.gold_first, may.gold_latest, may.gold_year) == (False, True, True)
    assert may.flips_latest and tasks.flip_eligible(may)
    assert may.no_change_until == D(2016, 7, 31)  # identical in the next vintage only
    mar = cands["ipt-ip_fell-2016-03"]
    assert mar.as_of == D(2016, 4, 30) and mar.no_change_until == D(2016, 6, 30)
    with pytest.raises(KeyError):
        tasks.build_candidates(["NOPE"], root)


def _cand(
    key: str,
    period: date,
    first: bool,
    latest: bool | None = None,
    d_first: float = 1.0,
    d_latest: float | None = None,
    thr: float | None = None,
    as_of: date | None = None,
    latest_date: date = LATEST,
    nc: date | None = None,
) -> Candidate:
    tp = tasks.TEMPLATES[key]
    latest = first if latest is None else latest
    sign1 = 1 if first else -1
    sign2 = 1 if latest else -1
    d_latest = d_first if d_latest is None else d_latest
    as_of = as_of or tasks.shift(period, 2) - timedelta(days=1)
    return Candidate(
        template=key, series_id=tp.series_id, period=period,
        threshold=tp.thresholds[0] if thr is None else thr, as_of=as_of, latest=latest_date,
        year_later=as_of + timedelta(days=400), gold_first=first, gold_year=latest,
        gold_latest=latest, dist_first=sign1 * abs(d_first), dist_year=sign2 * abs(d_latest),
        dist_latest=sign2 * abs(d_latest), no_change_until=nc,
    )  # fmt: skip


def test_materiality_cap_gap_and_covid_filters() -> None:
    p = D(2018, 5, 1)
    ok = _cand("ip_fell", p, True, True, 0.2, 0.25)
    assert tasks.control_eligible(ok)
    assert not tasks.control_eligible(_cand("ip_fell", p, True, True, 0.2, 0.31))  # over cap
    assert not tasks.control_eligible(_cand("ip_fell", p, True, True, 0.04, 0.2))  # immaterial
    assert not tasks.flip_eligible(_cand("ip_fell", p, True, False, 0.2, 0.04))  # immaterial
    assert tasks.flip_eligible(_cand("ip_fell", p, True, False, 3.0, 3.0))  # flips: no cap
    short = _cand("ip_fell", p, True, False, 1.0, latest_date=D(2019, 1, 31))
    assert not short.gap_ok and not tasks.flip_eligible(short)
    covid = _cand("ip_fell", D(2020, 4, 1), True, False, 1.0)
    assert not tasks.flip_eligible(covid)
    nc_covid = _cand("ip_fell", D(2020, 4, 1), True, nc=D(2020, 9, 30), d_first=0.2)
    assert not tasks.no_change_eligible(nc_covid)
    assert tasks.no_change_eligible(_cand("ip_fell", p, True, nc=D(2018, 12, 31), d_first=0.2))
    assert not tasks.no_change_eligible(_cand("ip_fell", p, True, d_first=0.2))  # no run


def test_control_caps_are_tighter_than_v0() -> None:
    caps = {k: tp.cap / tp.margin for k, tp in tasks.TEMPLATES.items()}
    assert caps["ip_fell"] < 10 and caps["cpi_12m_above"] < 10 and caps["cpi_1m_above"] < 10
    assert tasks.TEMPLATES["payroll_avg3m_above"].cap < 40
    assert tasks.TEMPLATES["payroll_weakest_12m"].cap < 40
    assert tasks.TEMPLATES["gdp_growth_above"].cap < 2.0


# --- selection --------------------------------------------------------------------------


def _pool() -> list[Candidate]:
    """Synthetic pool: plenty of each kind across series, periods 2016-2019, 2022-2025."""
    out: list[Candidate] = []
    months = [
        D(y, m, 1) for y in (2016, 2017, 2018, 2019, 2022, 2023, 2024, 2025) for m in range(1, 13)
    ]
    for i, p in enumerate(months):
        ans = i % 2 == 0
        out.append(_cand("ip_fell", p, ans, not ans, 0.5, 0.5))  # flips
        out.append(_cand("unemployment_rose", p, ans, not ans, 0.05, 0.05))  # flips
        out.append(_cand("cpi_1m_above", p, ans, ans, 0.08, 0.08))  # controls
        if p.month % 3 == 1:  # flips in even years, controls in odd years (unique ids)
            flip = p.year % 2 == 0
            out.append(_cand("gdp_growth_above", p, ans, not ans if flip else ans, 0.5, 0.5))
        if i % 6 == 0:  # no_change candidates on a series used by no other kind
            out.append(
                _cand(
                    "payroll_avg3m_above",
                    p,
                    i % 12 == 0,
                    d_first=5.0,
                    thr=100.0,
                    nc=tasks.shift(p, 8),
                )
            )
    return out


def test_select_v1_counts_balance_and_spread() -> None:
    sel = tasks.select_v1_detailed(_pool(), seed=0)
    ts = sel.tasks
    assert len(ts) == 45 and sel.shortfall == {"flip": 0, "control": 0, "no_change": 0}
    assert len({t.id for t in ts}) == 45
    by = {k: [t for t in ts if t.kind == k] for k in tasks.KINDS}
    assert [len(by[k]) for k in tasks.KINDS] == [20, 20, 5]
    assert sum(t.gold_as_of for t in by["flip"]) == 10
    assert sum(t.gold_as_of for t in by["control"]) == 10
    assert sum(t.gold_as_of for t in by["no_change"]) in (2, 3)
    assert all(t.flips for t in by["flip"]) and not any(t.flips for t in by["control"])
    assert all(t.revision_date != "2026-09-30" for t in by["no_change"])
    assert sel.overlaps == 0
    assert len({t.series_id for t in by["flip"]}) == 3  # IPT, RUC, ROUTPUT all used
    assert len({tasks._d(t.period).year for t in ts}) == 8
    assert not any(tasks.covid_window_overlap(t) for t in ts)


def test_select_v1_deterministic_and_order_independent() -> None:
    pool = _pool()
    a = tasks.select_v1(pool, seed=0)
    assert a == tasks.select_v1(list(reversed(pool)), seed=0)
    assert a == tasks.select_v1(pool + pool, seed=0)  # duplicates dropped
    assert {t.id for t in a} != {t.id for t in tasks.select_v1(pool, seed=1)}


def test_select_v1_overlap_only_when_needed_and_shortfall() -> None:
    p = D(2018, 5, 1)
    # two flips sharing a window: the second only if no other candidate fits
    pool = [
        _cand("payroll_avg3m_above", p, True, False, 5, 5, thr=100.0),
        _cand("payroll_avg3m_above", p, True, False, 5, 5, thr=150.0),
        _cand("payroll_avg3m_above", D(2019, 5, 1), True, False, 5, 5, thr=100.0),
    ]
    quotas = {"flip": (2, 0), "control": (0, 0), "no_change": (0, 0)}
    sel = tasks.select_v1_detailed(pool, 0, quotas)
    assert sel.overlaps == 0 and len(sel.tasks) == 2
    sel = tasks.select_v1_detailed(pool, 0, {**quotas, "flip": (3, 1)})
    assert sel.overlaps == 1 and len(sel.tasks) == 3 and sel.shortfall["flip"] == 1


# --- save / load ------------------------------------------------------------------------


def test_save_writes_definitions_only_and_load_recomputes(tmp_path: Path) -> None:
    root = _ip_root(tmp_path / "raw")
    cands = {c.id: c for c in tasks.build_candidates(["IPT"], root)}
    flip = tasks.to_task(cands["ipt-ip_fell-2016-05"], "flip")
    nc = tasks.to_task(cands["ipt-ip_fell-2016-03"], "no_change")
    path = tmp_path / "t.jsonl"
    tasks.save_tasks(path, [flip, nc])
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    assert [list(r) for r in rows] == [list(tasks.DEFINITION_FIELDS)] * 2
    loaded = tasks.load_tasks(path, root)
    assert loaded == [flip, nc]
    assert (loaded[0].gold_as_of, loaded[0].gold_revised, loaded[0].flips) == (False, True, True)
    assert loaded[1].revision_date == "2016-06-30" and loaded[1].flips is False


@pytest.mark.parametrize("cid,stored,revision", [
    ("ipt-ip_fell-2016-05", "control", None),  # actually flips
    ("ipt-ip_fell-2016-04", "flip", None),  # does not flip
    ("ipt-ip_fell-2016-03", "no_change", "2018-12-31"),  # window revised by then
])  # fmt: skip
def test_load_tasks_kind_mismatch_raises(
    tmp_path: Path, cid: str, stored: str, revision: str | None
) -> None:
    root = _ip_root(tmp_path / "raw")
    c = {c.id: c for c in tasks.build_candidates(["IPT"], root)}[cid]
    t = replace(tasks.to_task(c, "flip" if c.flips_latest else "control"), kind=stored)
    if revision:
        t = replace(t, revision_date=revision)
    tasks.save_tasks(tmp_path / "t.jsonl", [t])
    with pytest.raises(tasks.TaskKindError):
        tasks.load_tasks(tmp_path / "t.jsonl", root)


def test_evaluate_materiality_and_missing() -> None:
    t = _task("ip_fell", "2019-02-01", kind="control")
    s = {D(2019, 1, 1): 100.0, D(2019, 2, 1): 99.0}
    assert tasks.evaluate(t, s, s).gold_as_of is True
    with pytest.raises(tasks.TaskKindError, match="materiality"):
        tasks.evaluate(t, s, {D(2019, 1, 1): 100.0, D(2019, 2, 1): 99.99})
    with pytest.raises(tasks.TaskKindError, match="computable"):
        tasks.evaluate(t, s, {D(2019, 2, 1): 99.0})


# --- base rates -------------------------------------------------------------------------


def test_base_rates_counting() -> None:
    p, q = D(2018, 5, 1), D(2020, 5, 1)  # q: COVID window
    cands = [
        _cand("ip_fell", p, True, False, 0.5, 0.5),  # material flip
        _cand("ip_fell", tasks.shift(p, 2), True, False, 0.5, 0.01),  # immaterial flip
        _cand("ip_fell", tasks.shift(p, 4), True, True, 0.5, 0.5),  # same
        _cand("ip_fell", q, True, False, 0.5, 0.5),  # COVID flip
        _cand("ip_fell", tasks.shift(p, 6), True, False, latest_date=D(2018, 9, 30)),  # gap
        _cand("unemployment_rose", p, False, False, 0.05, 0.05),
    ]
    rows = tasks.base_rates(cands)
    cell = {(r.group, r.name, r.comparison, r.variant): (r.k, r.n) for r in rows}
    assert cell[("series", "IPT", "latest", "all")] == (3, 4)
    assert cell[("series", "IPT", "latest", "all_no_covid")] == (2, 3)
    assert cell[("series", "IPT", "latest", "material")] == (2, 3)
    assert cell[("series", "IPT", "latest", "material_no_covid")] == (1, 2)
    assert cell[("overall", "all", "one_year", "all")] == (3, 5)
    assert cell[("template", "unemployment_rose", "latest", "all")] == (0, 1)
    md = tasks.render_base_rates(rows)
    assert "3/4 (75.0%)" in md and "| overall |" in md
    assert tasks._cell(0, 0) == "0/0 (n/a)"


# --- CLI on a synthetic five-series root -------------------------------------------------


def _synthetic_root(root: Path) -> Path:
    """Five series with random walks and periodic revisions (synthetic, seeded)."""
    rng = random.Random(7)
    for sid, info in data.SERIES.items():
        quarterly_obs = info.frequency == "quarterly"
        if info.vintage_frequency == "quarterly":
            vds = [D(2015, 11, 15)] + [
                D(y, m, 15) for y in range(2016, 2020) for m in (2, 5, 8, 11)
            ]
        else:
            day = 15 if info.vintage_rule == "mid_month" else None
            vds = []
            for i in range(-1, 48):
                first = tasks.shift(D(2016, 1, 1), i)
                vds.append(
                    first.replace(day=15) if day else tasks.shift(first, 1) - timedelta(days=1)
                )
        base = {"EMPLOY": 140000.0, "RUC": 5.0, "PCPI": 240.0}.get(sid, 100.0)
        step = 3 if quarterly_obs else 1
        obs = [tasks.shift(D(2015, 1, 1), k) for k in range(0, 60, step)]
        truth, lv = {}, base
        for o in obs:
            lv += {"EMPLOY": rng.randint(-50, 350), "RUC": rng.choice([-0.1, 0, 0.1])}.get(
                sid, base * rng.uniform(-0.004, 0.008)
            )
            truth[o] = round(lv, info.decimals)
        snaps = {}
        for k, vd in enumerate(vds):
            lag = 4 if quarterly_obs else 1
            last = tasks.shift(D(vd.year, vd.month, 1), -lag)
            snaps[vd] = {
                o: round(
                    v + (0 if (k + o.month) % 5 else {"EMPLOY": 40, "RUC": 0.1}.get(sid, 0.2)),
                    info.decimals,
                )
                for o, v in truth.items()
                if o <= last
            }
        _write(root, sid, snaps)
    return root


def test_cli_build_on_synthetic_data(tmp_path: Path) -> None:
    root = _synthetic_root(tmp_path / "raw")
    out = tmp_path / "tasks"
    assert tasks.main(["--build", "--root", str(root), "--out-dir", str(out)]) == 0
    loaded = tasks.load_tasks(out / "v1.jsonl", root)
    assert loaded and len(loaded) <= 45
    readme, rates = (out / "README.md").read_text(), (out / "BASE_RATES.md").read_text()
    assert "## Tasks" in readme and all(t.id in readme for t in loaded)
    assert "First release vs latest vintage" in rates
    (out / "BASE_RATES.md").unlink()
    assert tasks.main(["--base-rates", "--root", str(root), "--out-dir", str(out)]) == 0
    assert (out / "BASE_RATES.md").read_text() == rates
    with pytest.raises(SystemExit):
        tasks.main([])


# --- real data (skipped without data/raw) -----------------------------------------------

REAL = data.RAW_DIR / "EMPLOY.parquet"
needs_data = pytest.mark.skipif(not REAL.exists(), reason="data/raw not fetched")


@pytest.fixture(scope="module")
def real_candidates() -> list[Candidate]:
    return tasks.build_candidates(data.SERIES_IDS, data.RAW_DIR)


@needs_data
def test_v1_file_loads_and_matches_rules() -> None:
    ts = tasks.load_tasks(tasks.V1_PATH, data.RAW_DIR)
    assert len(ts) == 45 and len({t.id for t in ts}) == 45
    for kind, (yes, no) in tasks.QUOTAS.items():
        mine = [t for t in ts if t.kind == kind]
        assert len(mine) == yes + no
        assert sum(t.gold_as_of for t in mine) in ({yes, no} if kind == "no_change" else {yes})
    for t in ts:
        assert not tasks.covid_window_overlap(t)
        gap = (date.fromisoformat(t.revision_date) - date.fromisoformat(t.as_of_date)).days
        assert gap >= (365 if t.kind != "no_change" else 1)
        tp = tasks.template_of(t)
        assert min(abs(t.margin_as_of), abs(t.margin_revised)) >= tp.margin - 1e-9
        if t.kind != "flip":
            assert max(abs(t.margin_as_of), abs(t.margin_revised)) <= tp.cap + 1e-9
    stored = tasks.V1_PATH.read_text()
    assert "gold" not in stored and "margin" not in stored


@needs_data
def test_v1_file_is_reproducible(real_candidates: list[Candidate], tmp_path: Path) -> None:
    sel = tasks.select_v1(real_candidates, seed=0)
    tasks.save_tasks(tmp_path / "v1.jsonl", sel)
    assert (tmp_path / "v1.jsonl").read_text() == tasks.V1_PATH.read_text()
