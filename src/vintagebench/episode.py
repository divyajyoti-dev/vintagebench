"""Two-turn episodes: as-of answer, then re-check after a revision (SPEC §4, §5).

Turn 1: the system prompt states today is <as_of_date>; get_series serves data as of
that date. Turn 2: the user message is exactly the SPEC text and get_series serves data
as of <revision_date>. Models and sanity agents run through the same tool-call loop.
Replies are parsed leniently (bare JSON, fenced blocks, JSON inside prose); a reply
that cannot be parsed is recorded as ``{"_error": ..., "_raw": text}`` and graded wrong.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from vintagebench import data, models
from vintagebench.models import Message, ModelResponse, ModelSpec, ToolSpec, iter_json_objects
from vintagebench.sanity import SanityAgent
from vintagebench.tasks import Task

Agent = ModelSpec | SanityAgent

MAX_STEPS = 6  # model calls per turn; at most MAX_STEPS - 1 rounds of tool calls

GET_SERIES: ToolSpec = {
    "type": "function",
    "function": {
        "name": "get_series",
        "description": (
            "Return observations of an economic data series as published on or before "
            "today, for observation dates in [start, end]. For known series the result also "
            "has a 'metadata' object with the series title, units, frequency and seasonal "
            "adjustment."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "series_id": {"type": "string", "description": "FRED series ID, e.g. PAYEMS"},
                "start": {"type": "string", "description": "first observation date YYYY-MM-DD"},
                "end": {"type": "string", "description": "last observation date YYYY-MM-DD"},
            },
            "required": ["series_id", "start", "end"],
        },
    },
}
TOOLS: list[ToolSpec] = [GET_SERIES]

# Static, vintage-independent series metadata returned with get_series results (FRED
# titles/units). Index and chained-dollar base years change across vintages (e.g.
# 2012 -> 2017), so no base year is stated. Series not listed here get no metadata block.
_SA = "Seasonally Adjusted"
SERIES_METADATA: dict[str, dict[str, str]] = {
    "PAYEMS": {
        "title": "All Employees, Total Nonfarm",
        "units": "Thousands of Persons",
        "frequency": "Monthly",
        "seasonal_adjustment": _SA,
    },
    "GDPC1": {
        "title": "Real Gross Domestic Product",
        "units": "Billions of Chained Dollars",
        "frequency": "Quarterly",
        "seasonal_adjustment": "Seasonally Adjusted Annual Rate",
    },
    "PCEPI": {
        "title": "Personal Consumption Expenditures: Chain-type Price Index",
        "units": "Index",
        "frequency": "Monthly",
        "seasonal_adjustment": _SA,
    },
    "INDPRO": {
        "title": "Industrial Production: Total Index",
        "units": "Index",
        "frequency": "Monthly",
        "seasonal_adjustment": _SA,
    },
    "UNRATE": {
        "title": "Unemployment Rate",
        "units": "Percent",
        "frequency": "Monthly",
        "seasonal_adjustment": _SA,
    },
    "TOY": {"title": "Toy test series", "units": "Index", "frequency": "Monthly"},
}

SYSTEM_PROMPT = """Today is {as_of_date}. You are an economic data analyst.
Use the get_series tool to look up data. Base your answers only on data that has been \
published as of the date the tool serves; do not use figures you may remember from later \
releases.

When answering a question, reply with ONLY a JSON object:
{{"answer": {answer_format}, "confidence": <probability 0-1 that your answer is correct>, \
"values_used": {{"YYYY-MM-DD": <series value>, ...}}, "caveats": "<short text>"}}
values_used must list the exact series values you relied on, keyed by observation date.

If you are later told that a new data release is available, look up the data again and \
reply with ONLY a JSON object:
{{"answer": {answer_format}, "confidence": <probability 0-1>, \
"changed": <true if your answer changed, else false>, "reason": "<short text>"}}"""

ANSWER_FORMATS = {"yes_no": '"yes" or "no"', "number": "<a single number>"}
TURN2_MESSAGE = "A new data release is available as of {revision_date}. Re-check your conclusion."


@dataclass
class EpisodeRecord:
    """Everything needed to grade one (task, agent, trial) episode.

    ``turn1`` holds {answer, confidence, values_used, caveats};
    ``turn2`` holds {answer, confidence, changed, reason}. A reply that could not be
    parsed is ``{"_error": str, "_raw": str}``.
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


def agent_name(agent: Agent) -> str:
    """ "provider/model_id" for models, the agent's name for sanity agents."""
    return agent.name


def system_prompt(task: Task) -> str:
    return SYSTEM_PROMPT.format(
        as_of_date=task.as_of_date, answer_format=ANSWER_FORMATS[task.answer_type]
    )


def turn1_message(task: Task) -> str:
    return f"Question: {task.question}\nSeries: {task.series_id}"


def turn2_message(task: Task) -> str:
    return TURN2_MESSAGE.format(revision_date=task.revision_date)


# --- tool ----------------------------------------------------------------------------


def _parse_day(s: Any) -> date | None:
    if s in (None, ""):
        return None
    return pd.Timestamp(str(s)).date()


def get_series(args: dict[str, Any], as_of: str, root: Path) -> dict[str, Any]:
    """Serve ``series_id`` as known on ``as_of``, restricted to observations in [start, end].

    Uses only ``data.get_as_of``, so values from later vintages can never be served.
    Known series also get a static ``metadata`` block (SERIES_METADATA). Errors are
    returned to the model as ``{"error": ...}``, never raised.
    """
    try:
        series_id = str(args["series_id"]).strip().upper()
        start, end = _parse_day(args.get("start")), _parse_day(args.get("end"))
        known = data.get_as_of(series_id, date.fromisoformat(as_of), root)
    except FileNotFoundError:
        return {"error": f"unknown series {args.get('series_id')!r}"}
    except (KeyError, ValueError, TypeError) as exc:
        return {"error": f"bad arguments: {exc}"}
    obs = [
        {"date": d.isoformat(), "value": float(v)}
        for d, v in known.items()
        if (start is None or d >= start) and (end is None or d <= end)
    ]
    result: dict[str, Any] = {"series_id": series_id, "as_of": as_of}
    if series_id in SERIES_METADATA:
        result["metadata"] = dict(SERIES_METADATA[series_id])
    result["observations"] = obs
    return result


def _run_tool(call: dict[str, Any], as_of: str, root: Path) -> dict[str, Any]:
    if call["name"] != "get_series":
        return {"error": f"unknown tool {call['name']!r}"}
    return get_series(call["arguments"], as_of, root)


# --- replies -------------------------------------------------------------------------


def parse_reply(text: str) -> dict[str, Any]:
    """Extract the reply JSON object (preferring one with an "answer" key)."""
    objs = iter_json_objects(text or "")
    for obj in objs:
        if "answer" in obj:
            return obj
    if objs:
        return {"_error": "reply JSON has no 'answer'", "_raw": text}
    return {"_error": "unparsable reply", "_raw": text}


def _assistant_message(resp: ModelResponse) -> Message:
    msg: Message = {"role": "assistant", "content": resp.text or None}
    if resp.tool_calls:
        msg["tool_calls"] = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])},
            }
            for tc in resp.tool_calls
        ]
    return msg


# --- loop ----------------------------------------------------------------------------


@dataclass
class _Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def add(self, r: ModelResponse) -> None:
        self.input_tokens += r.input_tokens
        self.output_tokens += r.output_tokens
        self.cost_usd += r.cost_usd


def _call(
    agent: Agent,
    messages: list[Message],
    task: Task,
    root: Path,
    turn: int,
    trial: int,
    step: int,
    model_kwargs: dict[str, Any],
) -> ModelResponse:
    if isinstance(agent, ModelSpec):
        ids = {"task_id": task.id, "turn": turn, "trial": trial, "step": step}
        return models.complete(agent, messages, TOOLS, **ids, **model_kwargs)
    return agent(messages, TOOLS, task=task, root=root)


def _run_turn(
    agent: Agent,
    messages: list[Message],
    task: Task,
    root: Path,
    turn: int,
    trial: int,
    serve_as_of: str,
    usage: _Usage,
    model_kwargs: dict[str, Any],
) -> dict[str, Any]:
    for step in range(MAX_STEPS):
        resp = _call(agent, messages, task, root, turn, trial, step, model_kwargs)
        usage.add(resp)
        messages.append(_assistant_message(resp))
        if not resp.tool_calls:
            return parse_reply(resp.text)
        for call in resp.tool_calls:
            result = _run_tool(call, serve_as_of, root)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "name": call["name"],
                    "content": json.dumps(result),
                }
            )
    return {"_error": f"no final answer within {MAX_STEPS} model calls", "_raw": ""}


def run_episode(
    task: Task,
    agent: Agent,
    trial: int,
    root: Path,
    *,
    model_kwargs: dict[str, Any] | None = None,
) -> EpisodeRecord:
    """Run both turns of ``task`` for ``agent``.

    Turn 1 serves get_series as of task.as_of_date; turn 2 as of
    task.revision_date. ``root`` is the vintage data directory. ``model_kwargs``
    are passed to :func:`models.complete` (client, cache_dir, budget, ...) for model
    agents. ``models.BudgetExceeded`` propagates to the caller.
    """
    root = Path(root)
    kwargs = model_kwargs or {}
    usage = _Usage()
    messages: list[Message] = [
        {"role": "system", "content": system_prompt(task)},
        {"role": "user", "content": turn1_message(task)},
    ]
    turn1 = _run_turn(agent, messages, task, root, 1, trial, task.as_of_date, usage, kwargs)
    messages.append({"role": "user", "content": turn2_message(task)})
    turn2 = _run_turn(agent, messages, task, root, 2, trial, task.revision_date, usage, kwargs)
    return EpisodeRecord(
        task_id=task.id,
        agent=agent_name(agent),
        trial=trial,
        turn1=turn1,
        turn2=turn2,
        transcript=messages,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=usage.cost_usd,
    )
