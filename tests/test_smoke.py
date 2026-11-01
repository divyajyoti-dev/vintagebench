"""Smoke test: package imports and fixtures match the SPEC schemas. Offline only."""

import dataclasses
import json
from pathlib import Path

import pandas as pd

import vintagebench
from vintagebench import data, episode, grader, models, run, sanity, tasks  # noqa: F401

FIXTURES = Path(__file__).parent / "fixtures"


def _as_of(df: pd.DataFrame, as_of: str) -> pd.Series:
    known = df[df["vintage_date"] <= pd.Timestamp(as_of).date()]
    latest = known.sort_values("vintage_date").groupby("observation_date").last()
    return latest["value"]


def test_smoke() -> None:
    assert vintagebench.__version__

    df = pd.read_parquet(FIXTURES / "vintages" / "TOY.parquet")
    assert list(df.columns) == ["series_id", "observation_date", "vintage_date", "value"]
    assert df["observation_date"].nunique() == 12
    assert df["vintage_date"].nunique() == 3

    first, revised = _as_of(df, "2021-01-15").diff(), _as_of(df, "2021-02-15").diff()
    june = pd.Timestamp("2020-06-01").date()
    assert first[june] > 0 > revised[june]

    task_fields = {f.name for f in dataclasses.fields(tasks.Task)}
    assert set(tasks.DEFINITION_FIELDS) <= task_fields
    lines = (FIXTURES / "tasks.jsonl").read_text().splitlines()
    assert len(lines) == 3
    for line in lines:
        row = json.loads(line)
        assert tuple(row) == tasks.DEFINITION_FIELDS
