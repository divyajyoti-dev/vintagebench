"""Task schema, candidate generation and pilot selection (SPEC §3, §5)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

AnswerType = Literal["yes_no", "number"]
Answer = bool | float


@dataclass(frozen=True)
class Task:
    """One benchmark task; one line of tasks/pilot.jsonl.

    Dates are ISO strings (YYYY-MM-DD). Gold answers are computed
    programmatically from the as-of and revision vintages, never hand-labeled.
    """

    id: str
    series_id: str
    as_of_date: str
    question: str
    answer_type: AnswerType
    gold_as_of: Answer
    revision_date: str
    gold_revised: Answer
    flips: bool
    notes: str = ""


def build_candidates(series_ids: Iterable[str], root: Path) -> list[Task]:
    """Generate all candidate tasks from the SPEC §3 templates for ``series_ids``.

    ``root`` is the vintage data directory. Gold answers are computed from vintages.
    """
    raise NotImplementedError


def select_pilot(candidates: list[Task], n: int = 20, seed: int = 0) -> list[Task]:
    """Select a seeded, balanced pilot set (~half flips, spread across series/years)."""
    raise NotImplementedError


def save_tasks(path: Path, tasks: Iterable[Task]) -> None:
    """Write tasks to ``path`` as JSON Lines, one Task per line."""
    raise NotImplementedError


def load_tasks(path: Path) -> list[Task]:
    """Read tasks from a JSON Lines file written by :func:`save_tasks`."""
    raise NotImplementedError
