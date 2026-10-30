"""Deterministic grading, no LLM judge (SPEC §1, §4, §5).

Rules:
- Answers. yes_no: a bool, or a string starting with yes/no/true/false (case and
  punctuation ignored). number: an int/float, or a numeric string (commas, %, $ and
  spaces stripped). A number answer is correct when
  ``|answer - gold| <= max(0.01 * |gold|, 0.5 * 10**-d)``, where d is the number of
  decimals in the gold value (capped at 6): i.e. within 1% or within rounding of the
  gold's precision. Missing or unparsable answers are wrong.
- update_correct: turn-2 ``changed`` (bool, or a yes/no/true/false string) == task.flips.
  Missing ``changed`` is wrong.
- leakage (turn 1 only): some values_used entry, for an observation date d, matches the
  value of d in some vintage published after as_of_date but does not match the as-of
  value of d (or d was not yet published as of as_of_date). Match tolerance is half a
  unit in the last decimal place the agent reported (``0.5 * 10**-d``, d = decimals of
  the reported value, capped at 6; integers get 0.5). So a value rounded consistently
  with both vintages is not leakage. Keys are parsed as dates ("2020-06-01", "2020-06",
  "2020Q2" ...); entries with unparsable keys or non-numeric values are ignored.
- Brier (turn 1, all answer types): ``(confidence - asof_correct)**2``, i.e. the
  confidence is read as the stated probability that the turn-1 answer is correct. This
  makes number tasks gradable the same way as yes/no tasks. A missing or invalid
  confidence counts as 1.0 (Brier 1 if the answer is wrong, 0 if right); percent
  strings ("80%") are divided by 100; values are clipped to [0, 1].
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from vintagebench import data
from vintagebench.episode import EpisodeRecord
from vintagebench.tasks import Answer, Task

MAX_DECIMALS = 6
NUMBER_REL_TOL = 0.01


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
    answer_type: str = "yes_no"


# --- parsing -------------------------------------------------------------------------


def parse_bool(x: Any) -> bool | None:
    if isinstance(x, bool):
        return x
    if isinstance(x, str):
        s = re.sub(r"[^a-z]", " ", x.lower()).split()
        if s and s[0] in ("yes", "true"):
            return True
        if s and s[0] in ("no", "false"):
            return False
    return None


def parse_number(x: Any) -> float | None:
    if isinstance(x, bool):
        return None
    if isinstance(x, int | float):
        return float(x) if math.isfinite(x) else None
    if isinstance(x, str):
        try:
            v = float(re.sub(r"[,%$\s]", "", x))
        except ValueError:
            return None
        return v if math.isfinite(v) else None
    return None


def decimals(x: Any) -> int:
    """Decimal places as written (str) or in the shortest float repr, capped."""
    s = x if isinstance(x, str) else repr(x)
    s = re.sub(r"[,%$\s]", "", s).lower()
    if "e" in s:
        return MAX_DECIMALS
    return min(len(s.split(".")[1]) if "." in s else 0, MAX_DECIMALS)


def parse_obs_date(key: Any) -> date | None:
    s = str(key).strip()
    q = re.fullmatch(r"(\d{4})[-\s]?Q([1-4])", s, re.I)
    if q:
        return date(int(q.group(1)), 3 * int(q.group(2)) - 2, 1)
    try:
        return pd.Timestamp(s).date()
    except (ValueError, TypeError):
        return None


# --- correctness ---------------------------------------------------------------------


def answer_correct(answer: Any, gold: Answer, answer_type: str) -> bool:
    if answer_type == "yes_no":
        got = parse_bool(answer)
        return got is not None and got == bool(gold)
    got = parse_number(answer)
    if got is None:
        return False
    g = float(gold)
    tol = max(NUMBER_REL_TOL * abs(g), 0.5 * 10 ** -decimals(gold))
    return abs(got - g) <= tol + 1e-12


def _matches(reported: float, true: float, tol: float) -> bool:
    return abs(reported - true) <= tol + 1e-12


def leaked(task: Task, values_used: Any, root: Path) -> bool:
    """True if some reported value matches a later vintage but not the as-of vintage."""
    if not isinstance(values_used, dict) or not values_used:
        return False
    as_of = date.fromisoformat(task.as_of_date)
    asof_values = data.get_as_of(task.series_id, as_of, root)
    vint = data.load_vintages(task.series_id, root)
    later = vint[vint["vintage_date"] > as_of]
    later_by_date = later.groupby("observation_date")["value"].apply(list).to_dict()
    for key, raw in values_used.items():
        d, v = parse_obs_date(key), parse_number(raw)
        if d is None or v is None:
            continue
        tol = 0.5 * 10 ** -decimals(raw)
        if d in asof_values.index and _matches(v, float(asof_values[d]), tol):
            continue
        if any(_matches(v, float(x), tol) for x in later_by_date.get(d, [])):
            return True
    return False


def _confidence(turn1: dict[str, Any]) -> float:
    raw = turn1.get("confidence")
    c = parse_number(raw)
    if c is not None and isinstance(raw, str) and raw.strip().endswith("%"):
        c /= 100
    return 1.0 if c is None else min(max(c, 0.0), 1.0)


def grade(task: Task, record: EpisodeRecord, root: Path) -> Scores:
    """Score one episode.

    update_correct is ``changed == flips``. leakage is true when a values_used
    entry matches a later vintage but not the as-of vintage (with rounding
    tolerance). Brier uses the turn-1 confidence. ``root`` is the vintage data dir.
    """
    t1, t2 = record.turn1, record.turn2
    asof_ok = answer_correct(t1.get("answer"), task.gold_as_of, task.answer_type)
    changed = parse_bool(t2.get("changed"))
    return Scores(
        task_id=task.id,
        agent=record.agent,
        trial=record.trial,
        flips=task.flips,
        asof_correct=asof_ok,
        revised_correct=answer_correct(t2.get("answer"), task.gold_revised, task.answer_type),
        update_correct=changed is not None and changed == task.flips,
        leakage=leaked(task, t1.get("values_used"), Path(root)),
        brier=(_confidence(t1) - float(asof_ok)) ** 2,
        cost_usd=record.cost_usd,
        answer_type=task.answer_type,
    )


# --- aggregation ---------------------------------------------------------------------

SUMMARY_COLUMNS = [
    "episodes",
    "tasks",
    "trials",
    "asof_correct",
    "revised_correct",
    "update_correct",
    "update_correct_flip",
    "update_correct_control",
    "leakage_rate",
    "brier",
    "pass_k",
    "cost_usd",
]


def _rate(s: pd.Series) -> float:
    return float(s.mean()) if len(s) else float("nan")


def summarize(scores: Iterable[Scores]) -> pd.DataFrame:
    """Aggregate scores per agent (flip/control splits, leakage rate, Brier, pass^k, cost).

    Rates are fractions of episodes. pass_k is the fraction of tasks whose trials were
    all asof_correct; ``trials`` is the minimum number of trials over the agent's tasks
    (k). Index: agent, in first-seen order.
    """
    df = pd.DataFrame([asdict(s) for s in scores])
    if df.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS).rename_axis("agent")
    rows = {}
    for agent, g in df.groupby("agent", sort=False):
        per_task = g.groupby("task_id")
        rows[agent] = {
            "episodes": len(g),
            "tasks": per_task.ngroups,
            "trials": int(per_task.size().min()),
            "asof_correct": _rate(g["asof_correct"]),
            "revised_correct": _rate(g["revised_correct"]),
            "update_correct": _rate(g["update_correct"]),
            "update_correct_flip": _rate(g.loc[g["flips"], "update_correct"]),
            "update_correct_control": _rate(g.loc[~g["flips"], "update_correct"]),
            "leakage_rate": _rate(g["leakage"]),
            "brier": float(g["brier"].mean()),
            "pass_k": _rate(per_task["asof_correct"].all()),
            "cost_usd": float(g["cost_usd"].sum()),
        }
    return pd.DataFrame.from_dict(rows, orient="index", columns=SUMMARY_COLUMNS).rename_axis(
        "agent"
    )


def _count(mask: pd.Series) -> str:
    n = len(mask)
    return f"{int(mask.sum())}/{n} ({mask.mean():.0%})" if n else "n/a"


def summary_markdown(scores: Iterable[Scores]) -> str:
    """Per-agent markdown table with counts and percentages."""
    df = pd.DataFrame([asdict(s) for s in scores])
    header = (
        "| Agent | Episodes | asof_correct | revised_correct | update_correct (flip) "
        "| update_correct (control) | Leakage | Brier | pass^k (asof) | Cost (USD) |\n"
        "|---|---|---|---|---|---|---|---|---|---|"
    )
    if df.empty:
        return header
    lines = [header]
    for agent, g in df.groupby("agent", sort=False):
        per_task = g.groupby("task_id")["asof_correct"]
        k = int(per_task.size().min())
        lines.append(
            f"| {agent} | {len(g)} | {_count(g['asof_correct'])} "
            f"| {_count(g['revised_correct'])} "
            f"| {_count(g.loc[g['flips'], 'update_correct'])} "
            f"| {_count(g.loc[~g['flips'], 'update_correct'])} "
            f"| {_count(g['leakage'])} | {g['brier'].mean():.3f} "
            f"| {_count(per_task.all())} (k={k}) | {g['cost_usd'].sum():.4f} |"
        )
    return "\n".join(lines)
