"""Two-turn episodes: as-of answer, then re-check after a revision (SPEC §4, §5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vintagebench.models import ModelSpec
from vintagebench.sanity import SanityAgent
from vintagebench.tasks import Task

Agent = ModelSpec | SanityAgent


@dataclass
class EpisodeRecord:
    """Everything needed to grade one (task, agent, trial) episode.

    ``turn1`` holds {answer, confidence, values_used, caveats};
    ``turn2`` holds {answer, confidence, changed, reason}.
    """

    task_id: str
    agent: str
    trial: int
    turn1: dict[str, Any]
    turn2: dict[str, Any]
    transcript: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


def run_episode(task: Task, agent: Agent, trial: int, root: Path) -> EpisodeRecord:
    """Run both turns of ``task`` for ``agent``.

    Turn 1 serves get_series as of task.as_of_date; turn 2 as of
    task.revision_date. ``root`` is the vintage data directory.
    """
    raise NotImplementedError
