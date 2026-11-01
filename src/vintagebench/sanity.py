"""Sanity agents that need no API (SPEC §4.5).

Design: a sanity agent is an object with a ``name`` that the episode drives through
exactly the same loop as a model. Each call receives the conversation in OpenAI native
format and the available tools, plus the ``task`` and data ``root`` (keyword-only; a
model never sees these), and returns a :class:`ModelResponse`: a ``get_series`` tool
call or a final JSON reply text. The turn is inferred from the conversation (one user
message = turn 1). Answers come from the task's gold fields (the agents test the
harness and grader, not the gold computation). Every agent reports values_used over
the task's key observations (tasks.key_observations) and writes a ``calculation``
whose final conclusion agrees with its answer and contains no numbers.

Expected behaviour (checked by :func:`check_expectations`):
- oracle: turn 1 gold_as_of with the as-of values (from the tool), survival_prob =
  0 if flips else 1; turn 2 gold_revised with the re-served revision values,
  changed = flips. 100% on all metrics, 0 leakage, 0 contradiction, Briers 0.
- always_yes: "yes" both turns (confidence and survival_prob 0.5), no tools, no
  values. asof_correct exactly on Yes golds; update_correct exactly on non-flips.
- leaker: reads the latest vintage regardless of date and answers what those values
  imply (tasks.implied_answer; gold_revised if not computable) on both turns,
  changed = false. Turn-1 leakage on exactly the tasks where some key observation's
  latest value differs from its as-of value.
- never_update: oracle on turn 1, then repeats its turn-1 reply (answer and values)
  with changed = false. update_correct and revised_correct exactly on non-flips.
- probe agents first_release_recaller / latest_recaller answer the probe with the
  first-release / latest value of each key observation: every distinguishable value
  is classified first_release / latest.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from vintagebench import data
from vintagebench import tasks as tasks_mod
from vintagebench.episode import day, iso
from vintagebench.models import Message, ModelResponse, ToolSpec, iter_json_objects

if TYPE_CHECKING:
    from vintagebench.grader import ProbeScores, Scores
    from vintagebench.tasks import Task
else:
    Task = Any


class SanityAgent(Protocol):
    """Same interface as ``models.complete`` minus the spec, plus task context."""

    name: str

    def __call__(
        self, messages: list[Message], tools: list[ToolSpec], *, task: Task, root: Path
    ) -> ModelResponse: ...


def _turn(messages: list[Message]) -> int:
    return sum(1 for m in messages if m["role"] == "user")


def _key_dates(task: Task) -> list[str]:
    return [iso(d) for d in tasks_mod.key_observations(task)]


def _yn(answer: Any) -> str:
    return "yes" if answer else "no"


def _calc(answer: Any, how: str) -> str:
    return f"{how}; therefore, {_yn(answer)}."


def _reply(**fields: Any) -> ModelResponse:
    return ModelResponse(json.dumps(fields))


def _tool_call(task: Task) -> ModelResponse:
    dates = _key_dates(task)
    args = {"series_id": task.series_id, "start": min(dates), "end": max(dates)}
    return ModelResponse("", [{"id": "sanity-0", "name": "get_series", "arguments": args}])


def _results_since_user(messages: list[Message]) -> list[dict[str, Any]]:
    """Tool results since the latest user message, else the series JSON objects
    attached to that user message (the turn-2 re-served data)."""
    results = []
    for m in reversed(messages):
        if m["role"] == "tool":
            results.append(json.loads(m["content"]))
        elif m["role"] == "user":
            if results:
                return results
            return [o for o in iter_json_objects(m["content"] or "") if "observations" in o]
    return results


def _key_values(task: Task, results: list[dict[str, Any]]) -> dict[str, float]:
    wanted = set(_key_dates(task))
    return {
        o["date"]: o["value"]
        for r in results
        for o in r.get("observations", [])
        if o["date"] in wanted
    }


def _last_reply(messages: list[Message]) -> dict[str, Any]:
    for m in reversed(messages):
        if m["role"] == "assistant" and m.get("content"):
            return json.loads(m["content"])
    return {}


class _Base:
    name = "sanity"

    def __call__(
        self, messages: list[Message], tools: list[ToolSpec], *, task: Task, root: Path
    ) -> ModelResponse:
        if _turn(messages) <= 1:
            return self.turn1(messages, task, Path(root))
        return self.turn2(messages, task, Path(root))

    def turn1(self, messages: list[Message], task: Task, root: Path) -> ModelResponse:
        raise NotImplementedError

    def turn2(self, messages: list[Message], task: Task, root: Path) -> ModelResponse:
        raise NotImplementedError


class Oracle(_Base):
    """Answer from the correct vintage each turn: 100% on all metrics, 0 leakage."""

    name = "oracle"

    def turn1(self, messages: list[Message], task: Task, root: Path) -> ModelResponse:
        results = _results_since_user(messages)
        if not results:
            return _tool_call(task)
        return _reply(
            calculation=_calc(task.gold_as_of, "Applied the definition to values_used"),
            answer=_yn(task.gold_as_of),
            confidence=1.0,
            survival_prob=0.0 if task.flips else 1.0,
            values_used=_key_values(task, results),
            caveats="oracle",
        )

    def turn2(self, messages: list[Message], task: Task, root: Path) -> ModelResponse:
        results = _results_since_user(messages)
        if not results:
            return _tool_call(task)
        return _reply(
            calculation=_calc(task.gold_revised, "Applied the definition to values_used"),
            answer=_yn(task.gold_revised),
            confidence=1.0,
            changed=bool(task.flips),
            values_used=_key_values(task, results),
            reason="oracle",
        )


class AlwaysYes(_Base):
    """Always answer yes; scores the share of yes golds (~50% on a balanced set)."""

    name = "always_yes"

    def turn1(self, messages: list[Message], task: Task, root: Path) -> ModelResponse:
        return _reply(
            calculation="Always yes.",
            answer="yes",
            confidence=0.5,
            survival_prob=0.5,
            values_used={},
            caveats="always yes",
        )

    def turn2(self, messages: list[Message], task: Task, root: Path) -> ModelResponse:
        return _reply(
            calculation="Always yes.",
            answer="yes",
            confidence=0.5,
            changed=False,
            values_used={},
            reason="always yes",
        )


def latest_key_values(task: Task, root: Path) -> dict[str, float]:
    """Latest-vintage value of each key observation."""
    return {d: float(data.latest_value(task.series_id, day(d), root)) for d in _key_dates(task)}


class Leaker(_Base):
    """Read the latest vintage regardless of date; leakage wherever values differ."""

    name = "leaker"

    def _answer(self, task: Task, root: Path) -> tuple[dict[str, float], bool]:
        values = latest_key_values(task, root)
        implied = tasks_mod.implied_answer(task, {day(d): v for d, v in values.items()})
        return values, bool(task.gold_revised if implied is None else implied)

    def turn1(self, messages: list[Message], task: Task, root: Path) -> ModelResponse:
        values, answer = self._answer(task, root)
        return _reply(
            calculation=_calc(answer, "Used the latest vintage"),
            answer=_yn(answer),
            confidence=1.0,
            survival_prob=1.0,
            values_used=values,
            caveats="used the latest vintage",
        )

    def turn2(self, messages: list[Message], task: Task, root: Path) -> ModelResponse:
        values, answer = self._answer(task, root)
        return _reply(
            calculation=_calc(answer, "Used the latest vintage"),
            answer=_yn(answer),
            confidence=1.0,
            changed=False,
            values_used=values,
            reason="already used the latest data",
        )


class NeverUpdate(Oracle):
    """Answer correctly as of turn 1 and never change; update_correct only on non-flips."""

    name = "never_update"

    def turn2(self, messages: list[Message], task: Task, root: Path) -> ModelResponse:
        prev = _last_reply(messages)
        return _reply(
            calculation=prev.get("calculation", ""),
            answer=prev.get("answer"),
            confidence=1.0,
            changed=False,
            values_used=prev.get("values_used", {}),
            reason="never updates",
        )


class _Recaller:
    """Probe agent: replies {"values": {...}} from a fixed vintage choice."""

    name = "recaller"

    def value(self, task: Task, d: str, root: Path) -> float:
        raise NotImplementedError

    def __call__(
        self, messages: list[Message], tools: list[ToolSpec], *, task: Task, root: Path
    ) -> ModelResponse:
        values = {d: self.value(task, d, Path(root)) for d in _key_dates(task)}
        return _reply(values=values)


class FirstReleaseRecaller(_Recaller):
    name = "first_release_recaller"

    def value(self, task: Task, d: str, root: Path) -> float:
        return float(data.first_release(task.series_id, day(d), root)[0])


class LatestRecaller(_Recaller):
    name = "latest_recaller"

    def value(self, task: Task, d: str, root: Path) -> float:
        return float(data.latest_value(task.series_id, day(d), root))


oracle = Oracle()
always_yes = AlwaysYes()
leaker = Leaker()
never_update = NeverUpdate()
first_release_recaller = FirstReleaseRecaller()
latest_recaller = LatestRecaller()

SANITY_AGENTS: list[SanityAgent] = [oracle, always_yes, leaker, never_update]
PROBE_AGENTS: list[SanityAgent] = [first_release_recaller, latest_recaller]


# --- expected scores -----------------------------------------------------------------


def latest_differs(task: Task, root: Path) -> bool:
    """True if some key observation's latest value differs from its as-of value (or
    was unpublished as of as_of_date): exactly where the leaker must be flagged."""
    asof = data.get_as_of(task.series_id, day(task.as_of_date), root)
    known = {iso(d): float(v) for d, v in asof.items()}
    latest = latest_key_values(task, root)
    return any(d not in known or abs(known[d] - v) > 1e-9 for d, v in latest.items())


def _episode_failures(s: Scores, task: Task, root: Path) -> list[str]:
    nf = not task.flips
    clean = not (s.leakage_t1 or s.leakage_t2 or s.contradiction_t1 or s.contradiction_t2)
    checks: dict[str, dict[str, bool]] = {
        "oracle": {
            "asof_correct": s.asof_correct,
            "revised_correct": s.revised_correct,
            "update_correct": s.update_correct,
            "self_report_agrees": s.self_report_agrees is True,
            "no leakage / contradiction": clean,
            "confidence Brier 0": s.confidence_brier == 0,
            "survival Brier 0": s.survival_brier == 0,
        },
        "always_yes": {
            "asof_correct == gold_as_of": s.asof_correct == bool(task.gold_as_of),
            "update_correct == not flips": s.update_correct == nf,
            "no leakage / contradiction": clean,
        },
        "leaker": {
            "leakage_t1 == latest differs": s.leakage_t1 == latest_differs(task, root),
            "no contradiction": not (s.contradiction_t1 or s.contradiction_t2),
        },
        "never_update": {
            "asof_correct": s.asof_correct,
            "update_correct == not flips": s.update_correct == nf,
            "revised_correct == not flips": s.revised_correct == nf,
            "no leakage / contradiction": clean,
        },
    }
    return [
        f"{s.agent} {s.task_id} trial {s.trial}: expected {name}"
        for name, ok in checks.get(s.agent, {}).items()
        if not ok
    ]


def _probe_failures(p: ProbeScores) -> list[str]:
    want = {"first_release_recaller": "first_release", "latest_recaller": "latest"}.get(p.agent)
    if want is None:
        return []
    return [
        f"{p.agent} {p.task_id} {v['date']}: classified {v['class']}, expected {want}"
        for v in p.values
        if v["distinguishable"] and v["class"] != want
    ]


def check_expectations(
    scores: Iterable[Scores], probes: Iterable[ProbeScores], tasks: Iterable[Task], root: Path
) -> list[str]:
    """Failures of the sanity agents' expected scores ([] = all as expected)."""
    by_id = {t.id: t for t in tasks}
    failures: list[str] = []
    for s in scores:
        failures += _episode_failures(s, by_id[s.task_id], Path(root))
    for p in probes:
        failures += _probe_failures(p)
    return failures
