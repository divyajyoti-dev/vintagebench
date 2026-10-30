"""Regenerate tests/fixtures/vintages/TOY.parquet (run from repo root).

TOY: 12 monthly observations (2020-01..2020-12), 3 vintages. Like ALFRED, each
later vintage only carries the observations it revised.
- 2021-01-15: first release of all 12 months.
- 2021-02-15: June revised 101.5 -> 100.8, flipping June's MoM change from
  +0.5 to -0.2; December revised 103.0 -> 103.2.
- 2021-03-15: November revised 102.6 -> 102.7; December 103.2 -> 103.1.
"""

from pathlib import Path

import pandas as pd

OUT = Path(__file__).parent / "vintages" / "TOY.parquet"

FIRST = [100.0, 100.4, 100.9, 101.1, 101.0, 101.5, 101.8, 102.0, 102.3, 102.1, 102.6, 103.0]
REVISIONS = {
    "2021-02-15": {"2020-06-01": 100.8, "2020-12-01": 103.2},
    "2021-03-15": {"2020-11-01": 102.7, "2020-12-01": 103.1},
}


def build() -> pd.DataFrame:
    months = pd.date_range("2020-01-01", periods=12, freq="MS")
    rows = [
        ("TOY", m.date(), pd.Timestamp("2021-01-15").date(), v)
        for m, v in zip(months, FIRST, strict=True)
    ]
    for vintage, changes in REVISIONS.items():
        for obs, value in changes.items():
            rows.append(("TOY", pd.Timestamp(obs).date(), pd.Timestamp(vintage).date(), value))
    return pd.DataFrame(rows, columns=["series_id", "observation_date", "vintage_date", "value"])


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    build().to_parquet(OUT, index=False)
    print(f"wrote {OUT}")
