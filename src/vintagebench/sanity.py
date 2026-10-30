"""Sanity agents that need no API (SPEC §4).

Design: a sanity agent is an object with a ``name`` that the episode drives through
exactly the same tool-call loop as a model. Each call receives the conversation in
OpenAI native format and the available tools, plus the ``task`` and data ``root``
(keyword-only; a model never sees these, it only sees the prompt), and returns a
:class:`ModelResponse`: either a ``get_series`` tool call or a final JSON reply text.
The turn is inferred from the conversation (one user message = turn 1); the data a
sanity agent reports comes from the tool result the harness served, except for the
leaker, which reads the latest vintage directly. Answers come from the task's gold
fields (the agents test the harness and grader, not the gold computation).

Expected behaviour:
- oracle: turn 1 gold_as_of with as-of values; turn 2 gold_revised, changed=flips.
  100% on everything, 0 leakage, Brier 0.
- always_yes: "yes" (confidence 0.5) both turns, never calls tools, changed=false.
  Scores the share of yes golds on yes/no tasks (~50% on a balanced set; the run
  summary prints that share), wrong on number tasks; update_correct on controls only.
- leaker: reads the latest vintage regardless of date; answers gold_revised (a proxy
  for "the answer on revised data") with confidence 1 on both turns, changed=false.
  Leakage flagged wherever a reported value differs from the as-of vintage, and not
  flagged when the latest vintage equals the as-of vintage over its window.
- never_update: like oracle on turn 1, then repeats its turn-1 answer with
  changed=false. update_correct and revised_correct only on controls.

values_used covers every observation in the window [as_of - 2 years, as_of].
The window ends on as_of_date by design: the leaker reads it from the latest vintage,
so on real data it also reports the most recent observation(s) that had not yet been
published on as_of (e.g. the as_of month itself). Such values count as leakage, as they
should: an analyst who cites them is using data from the future. This is why the
leaker is flagged on every real-data episode; the oracle and never_update read the
window through the tool, which only serves published data.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Protocol

from vintagebench import data
from vintagebench.models import Message, ModelResponse, ToolSpec
from vintagebench.tasks import Answer, Task

WINDOW_DAYS = 731


class SanityAgent(Protocol):
    """Same interface as ``models.complete`` minus the spec, plus task context."""

    name: str

    def __call__(
        self, messages: list[Message], tools: list[ToolSpec], *, task: Task, root: Path
    ) -> ModelResponse: ...


def _turn(messages: list[Message]) -> int:
    return sum(1 for m in messages if m["role"] == "user")


def _last_tool_result(messages: list[Message]) -> dict[str, Any] | None:
    """The tool result served since the latest user message, if any."""
    for m in reversed(messages):
        if m["role"] == "tool":
            return json.loads(m["content"])
        if m["role"] == "user":
            return None
    return None


def _window(task: Task) -> tuple[str, str]:
    end = date.fromisoformat(task.as_of_date)
    return (end - timedelta(days=WINDOW_DAYS)).isoformat(), end.isoformat()


def _tool_call(task: Task) -> ModelResponse:
    start, end = _window(task)
    args = {"series_id": task.series_id, "start": start, "end": end}
    return ModelResponse("", [{"id": "sanity-0", "name": "get_series", "arguments": args}])


def _fmt(answer: Answer, task: Task) -> Any:
    if task.answer_type == "yes_no":
        return "yes" if answer else "no"
    return answer


def _reply(**fields: Any) -> ModelResponse:
    return ModelResponse(json.dumps(fields))


def _observations(result: dict[str, Any]) -> dict[str, float]:
    return {o["date"]: o["value"] for o in result.get("observations", [])}


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
        result = _last_tool_result(messages)
        if result is None:
            return _tool_call(task)
        return _reply(
            answer=_fmt(task.gold_as_of, task),
            confidence=1.0,
            values_used=_observations(result),
            caveats="oracle",
        )

    def turn2(self, messages: list[Message], task: Task, root: Path) -> ModelResponse:
        if _last_tool_result(messages) is None:
            return _tool_call(task)
        return _reply(
            answer=_fmt(task.gold_revised, task),
            confidence=1.0,
            changed=task.flips,
            reason="oracle",
        )


class AlwaysYes(_Base):
    """Always answer yes; scores the share of yes golds (~50% on a balanced set)."""

    name = "always_yes"

    def turn1(self, messages: list[Message], task: Task, root: Path) -> ModelResponse:
        return _reply(answer="yes", confidence=0.5, values_used={}, caveats="always yes")

    def turn2(self, messages: list[Message], task: Task, root: Path) -> ModelResponse:
        return _reply(answer="yes", confidence=0.5, changed=False, reason="always yes")


class Leaker(_Base):
    """Read the latest vintage regardless of date; leakage flagged wherever values differ."""

    name = "leaker"

    def turn1(self, messages: list[Message], task: Task, root: Path) -> ModelResponse:
        latest = data.get_as_of(task.series_id, data.vintage_dates(task.series_id, root)[-1], root)
        start, end = (date.fromisoformat(d) for d in _window(task))
        values = {d.isoformat(): float(v) for d, v in latest.items() if start <= d <= end}
        return _reply(
            answer=_fmt(task.gold_revised, task),
            confidence=1.0,
            values_used=values,
            caveats="used the latest vintage",
        )

    def turn2(self, messages: list[Message], task: Task, root: Path) -> ModelResponse:
        return _reply(
            answer=_fmt(task.gold_revised, task),
            confidence=1.0,
            changed=False,
            reason="already used the latest data",
        )


class NeverUpdate(Oracle):
    """Answer correctly as of turn 1 and never change; update_correct only on controls."""

    name = "never_update"

    def turn2(self, messages: list[Message], task: Task, root: Path) -> ModelResponse:
        return _reply(
            answer=_fmt(task.gold_as_of, task),
            confidence=1.0,
            changed=False,
            reason="never updates",
        )


oracle = Oracle()
always_yes = AlwaysYes()
leaker = Leaker()
never_update = NeverUpdate()

SANITY_AGENTS: list[SanityAgent] = [oracle, always_yes, leaker, never_update]
