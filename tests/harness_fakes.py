"""Synthetic data and tasks for the harness tests (never RTDSM values; SPEC §2.3).

``install(monkeypatch)`` replaces the data.py / tasks.py functions the harness calls
(load_vintages, vintage_dates, get_as_of, first_release, latest_value, SERIES,
implied_answer, key_observations) with in-memory versions over one toy series TOY.

TOY (monthly, rounding unit 0.1), three dense vintages:
- V1 2021-01-15: Jan..Aug 2020
- V2 2021-02-15: June revised down (June now falls vs May)
- V3 2022-03-15 (latest): March and June revised again
Template: "Did TOY fall in <month> versus the prior month?" -> value[m] < value[m-1].
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from vintagebench import data, tasks

V1, V2, V3 = date(2021, 1, 15), date(2021, 2, 15), date(2022, 3, 15)
MONTHS = [date(2020, m, 1) for m in range(1, 9)]
BASE = [100.0, 100.5, 101.0, 101.4, 101.1, 101.5, 101.9, 102.3]
SNAPSHOTS = {
    V1: dict(zip(MONTHS, BASE, strict=True)),
    V2: {**dict(zip(MONTHS, BASE, strict=True)), date(2020, 6, 1): 100.8},
    V3: {
        **dict(zip(MONTHS, BASE, strict=True)),
        date(2020, 3, 1): 100.2,
        date(2020, 6, 1): 100.7,
    },
}
SERIES = {
    "TOY": {
        "title": "Toy activity index",
        "units": "index",
        "frequency": "Monthly",
        "seasonal_adjustment": "seasonally adjusted",
        "rounding_unit": 0.1,
    }
}


@dataclass(frozen=True)
class FakeTask:
    id: str
    series_id: str
    period: str
    as_of_date: str
    revision_date: str
    question: str
    gold_as_of: bool
    gold_revised: bool
    flips: bool
    kind: str
    answer_type: str = "yes_no"


def _task(id_: str, month: int, gold_as_of: bool, gold_revised: bool, kind: str) -> FakeTask:
    name = date(2020, month, 1).strftime("%B")
    return FakeTask(
        id=id_,
        series_id="TOY",
        period=f"2020-{month:02d}-01",
        as_of_date=V1.isoformat(),
        revision_date=V2.isoformat(),
        question=f"Did TOY fall in {name} 2020 versus the prior month?",
        gold_as_of=gold_as_of,
        gold_revised=gold_revised,
        flips=gold_as_of != gold_revised,
        kind=kind,
    )


FLIP = _task("toy-flip", 6, False, True, "flip")  # June: rises in V1, falls in V2
CONTROL = _task("toy-control", 5, True, True, "control")  # May: falls in all vintages
NO_CHANGE = _task("toy-nochange", 3, False, False, "no_change")  # March same in V1/V2
TASKS = [FLIP, CONTROL, NO_CHANGE]


def frame() -> pd.DataFrame:
    rows = [
        {
            "series_id": "TOY",
            "observation_date": d,
            "vintage": f"TOY{v:%y}M{v.month}",
            "vintage_date": v,
            "value": x,
        }
        for v, snap in SNAPSHOTS.items()
        for d, x in snap.items()
    ]
    return pd.DataFrame(rows)


def load_vintages(series_id, root=None):
    if series_id != "TOY":
        raise FileNotFoundError(series_id)
    return frame()


def vintage_dates(series_id, root=None):
    return sorted(SNAPSHOTS)


def get_as_of(series_id, as_of, root=None):
    load_vintages(series_id)
    known = [v for v in sorted(SNAPSHOTS) if v <= pd.Timestamp(as_of).date()]
    if not known:
        return pd.Series(dtype=float, name=series_id)
    snap = SNAPSHOTS[known[-1]]
    return pd.Series(snap, name=series_id).sort_index()


def first_release(series_id, obs, root=None):
    for v in sorted(SNAPSHOTS):
        if obs in SNAPSHOTS[v]:
            return SNAPSHOTS[v][obs], v
    raise KeyError(obs)


def latest_value(series_id, obs, root=None):
    return SNAPSHOTS[max(SNAPSHOTS)][obs]


def key_observations(task):
    m = date.fromisoformat(task.period)
    prev = date(m.year, m.month - 1, 1)
    return [prev, m]


def implied_answer(task, values):
    prev, m = key_observations(task)
    if prev not in values or m not in values:
        return None
    return values[m] < values[prev]


def install(monkeypatch) -> None:
    for name, fn in [
        ("load_vintages", load_vintages),
        ("vintage_dates", vintage_dates),
        ("get_as_of", get_as_of),
        ("first_release", first_release),
        ("latest_value", latest_value),
    ]:
        monkeypatch.setattr(data, name, fn, raising=False)
    monkeypatch.setattr(data, "SERIES", SERIES, raising=False)
    monkeypatch.setattr(tasks, "implied_answer", implied_answer, raising=False)
    monkeypatch.setattr(tasks, "key_observations", key_observations, raising=False)
