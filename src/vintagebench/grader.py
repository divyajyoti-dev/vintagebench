"""Deterministic grading, no LLM judge (SPEC §1, §4, §5)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from vintagebench.episode import EpisodeRecord
from vintagebench.tasks import Task


@dataclass(frozen=True)
class Scores:
    """Per-episode scores."""

    task_id: str
    agent: str
    trial: int
    flips: bool
    asof_correct: bool
    revised_correct: bool
    update_correct: bool
    leakage: bool
    brier: float
    cost_usd: float


def grade(task: Task, record: EpisodeRecord, root: Path) -> Scores:
    """Score one episode.

    update_correct is ``changed == flips``. leakage is true when a values_used
    entry matches a later vintage but not the as-of vintage (with rounding
    tolerance). Brier uses the turn-1 confidence. ``root`` is the vintage data dir.
    """
    raise NotImplementedError


def summarize(scores: Iterable[Scores]) -> pd.DataFrame:
    """Aggregate scores per agent (flip/control splits, leakage rate, Brier, pass^k, cost)."""
    raise NotImplementedError
