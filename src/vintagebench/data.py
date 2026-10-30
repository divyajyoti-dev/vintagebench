"""ALFRED vintage storage and as-of lookups (SPEC §2, §5).

Vintages live in data/vintages/<SERIES>.parquet with columns
series_id, observation_date, vintage_date, value.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

DATA_DIR: Path = Path(__file__).resolve().parents[2] / "data" / "vintages"


def load_vintages(series_id: str, root: Path = DATA_DIR) -> pd.DataFrame:
    """Load all vintages for a series.

    Returns a DataFrame with columns series_id, observation_date, vintage_date, value.
    """
    raise NotImplementedError


def vintage_dates(series_id: str, root: Path = DATA_DIR) -> list[date]:
    """Return the sorted, distinct vintage dates available for a series."""
    raise NotImplementedError


def get_as_of(series_id: str, as_of: date, root: Path = DATA_DIR) -> pd.Series:
    """Return the series as it was known on ``as_of``.

    For each observation, the value from the latest vintage with
    vintage_date <= as_of. Indexed by observation_date. Never returns values
    from vintages after ``as_of``.
    """
    raise NotImplementedError
