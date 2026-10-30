"""CLI entry point (SPEC §4).

python -m vintagebench.run --models config/models.yaml --tasks tasks/pilot.jsonl
    --trials 3 [--limit N] [--sanity]
-> runs/<timestamp>/results.jsonl + summary.md
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    raise NotImplementedError


def main(argv: Sequence[str] | None = None) -> int:
    """Run the benchmark, enforcing the budget cap in config/run.yaml. Returns exit code."""
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
