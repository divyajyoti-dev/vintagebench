"""Two-turn episodes and the memorization probe (SPEC §4.1, §4.2, §4.4, §5).

Turn 1: the system prompt states today is <as_of_date>; get_series serves data as of
that date. The reply JSON has keys in this order: calculation, answer, confidence,
survival_prob, values_used, caveats.

Turn 2 (neutral): the user message is exactly
"Today is <revision_date>. Here is the latest data. Answer the question."
followed, one JSON object per line, by the get_series results for each distinct
successful get_series request the model made in turn 1, re-served as of revision_date
(same format as tool output). If the model made no successful turn-1 request, only the
sentence is sent and the model must use the tool, which stays available and serves
revision_date data. Reply keys: calculation, answer, confidence, changed, values_used,
reason.

Memorization probe: one call, no tools, no as-of date in the prompt, asking for the
values of the task's key observations (tasks.key_observations) from memory.

Models and sanity agents run through the same loop. Replies are parsed leniently
(bare JSON, fenced blocks, JSON inside prose); a reply that cannot be parsed is
recorded as ``{"_error": ..., "_raw": text}`` and graded wrong.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from vintagebench import data, models
from vintagebench import tasks as tasks_mod
from vintagebench.models import Message, ModelResponse, ModelSpec, ToolSpec, iter_json_objects

if TYPE_CHECKING:
    from vintagebench.sanity import SanityAgent
    from vintagebench.tasks import Task

    Agent = ModelSpec | SanityAgent
else:
    Agent = Any
    Task = Any

MAX_STEPS = 6  # model calls per turn; at most MAX_STEPS - 1 rounds of tool calls
PROBE_TURN = "probe"
PROBE_TRIAL = 1
META_KEYS = ("title", "units", "frequency", "seasonal_adjustment")

GET_SERIES: ToolSpec = {
    "type": "function",
    "function": {
        "name": "get_series",
        "description": (
            "Return observations of an economic data series as published on or before "
            "today, for observation dates in [start, end]. Dates are the first day of the "
            "observation month or quarter. The result also has a 'metadata' object with the "
            "series title, units and frequency."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "series_id": {"type": "string", "description": "series ID, e.g. EMPLOY"},
                "start": {"type": "string", "description": "first observation date YYYY-MM-DD"},
                "end": {"type": "string", "description": "last observation date YYYY-MM-DD"},
            },
            "required": ["series_id", "start", "end"],
        },
    },
}
TOOLS: list[ToolSpec] = [GET_SERIES]

SURVIVAL_WORDING = (
    "Probability (0-1) that this conclusion still holds after the data is fully revised"
)

SYSTEM_PROMPT = """Today is {as_of_date}. You are an economic data analyst.
The get_series tool returns ONLY data as published as of today. Base your answers only \
on data the tool returns; do not use figures you may remember.

Reply with ONLY a JSON object with exactly these keys, filled in this order:
{{"calculation": "<your working: the values you used and how they lead to the answer>", \
"answer": {answer_format}, \
"confidence": <probability (0-1) that your answer is correct>, \
"survival_prob": <{survival}>, \
"values_used": {{"YYYY-MM-DD": <series value>, ...}}, \
"caveats": "<short text>"}}
values_used must list the exact series values you relied on, keyed by observation date.

If you are later told that today's date has changed, answer the question again and \
reply with ONLY a JSON object with exactly these keys, filled in this order:
{{"calculation": "<your working>", "answer": {answer_format}, \
"confidence": <probability (0-1) that your answer is correct>, \
"changed": <true if this answer differs from your previous answer, else false>, \
"values_used": {{"YYYY-MM-DD": <series value>, ...}}, "reason": "<short text>"}}"""

ANSWER_FORMATS = {"yes_no": '"yes" or "no"', "number": "<a single number>"}
TURN2_MESSAGE = "Today is {revision_date}. Here is the latest data. Answer the question."

PROBE_SYSTEM = "You are an economic data analyst. No tools or data files are available."
PROBE_USER = """From memory, what are the values of {description} for these observation \
dates? Dates are the first day of the observation {period}.
{dates}
Give your best recollection of each value as a number in the units stated; use null if \
you do not know a value. Reply with ONLY a JSON object:
{{"values": {{"YYYY-MM-DD": <number or null>, ...}}}}"""


@dataclass
class EpisodeRecord:
    """Everything needed to grade one (task, agent, trial) episode.

    ``turn1`` holds {calculation, answer, confidence, survival_prob, values_used,
    caveats}; ``turn2`` holds {calculation, answer, confidence, changed, values_used,
    reason}. A reply that could not be parsed is ``{"_error": str, "_raw": str}``.
    ``turn1_requests`` are the distinct successful turn-1 get_series arguments, the ones
    re-served in the turn-2 message. ``agent`` is the config name.
    """

    task_id: str
    agent: str
    trial: int
    turn1: dict[str, Any]
    turn2: dict[str, Any]
    turn1_requests: list[dict[str, Any]] = field(default_factory=list)
    transcript: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class ProbeRecord:
    """One memorization-probe call: requested dates and the parsed reply.

    ``reply`` is ``{"values": {...}}`` or ``{"_error": str, "_raw": str}``.
    """

    task_id: str
    agent: str
    dates: list[str]
    reply: dict[str, Any]
    transcript: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0


def agent_name(agent: Agent) -> str:
    """Config name for models, the agent's name for sanity agents."""
    return agent.name


def iso(d: Any) -> str:
    """ISO date string of a date, Timestamp or ISO string."""
    return pd.Timestamp(d).date().isoformat()


def day(d: Any) -> date:
    return pd.Timestamp(d).date()


# --- series metadata (data.SERIES) ---------------------------------------------------


def series_meta(series_id: str) -> dict[str, Any]:
    """Metadata of ``series_id`` from data.SERIES as a plain dict ({} if unknown)."""
    meta = getattr(data, "SERIES", {}).get(series_id)
    if meta is None:
        return {}
    if is_dataclass(meta) and not isinstance(meta, type):
        return asdict(meta)
    return dict(meta) if isinstance(meta, dict) else dict(vars(meta))


def neutral(text: Any) -> str:
    """Drop ';'-separated clauses that mention vintages or revisions (e.g. "base year
    varies by vintage"), so metadata gives no hint that the data will be revised."""
    parts = [p.strip() for p in str(text).split(";")]
    keep = [p for p in parts if not re.search(r"vintage|revis", p, re.I)]
    return "; ".join(p for p in keep if p)


def tool_metadata(series_id: str) -> dict[str, Any]:
    """The static, vintage-independent metadata block returned by get_series."""
    meta = series_meta(series_id)
    out = {k: neutral(meta[k]) for k in META_KEYS if meta.get(k) not in (None, "")}
    return {k: v for k, v in out.items() if v}


def describe_series(series_id: str) -> str:
    """Words + units for the probe, e.g. "US nonfarm payroll employment (thousands of
    employees, SA; monthly)"."""
    meta = tool_metadata(series_id)
    title = meta.get("title") or series_id
    if title[:1].isupper() and title[1:2].islower():
        title = title[0].lower() + title[1:]
    if not re.search(r"\b(US|U\.S\.)", title):
        title = f"US {title}"
    extras = [meta[k] for k in ("seasonal_adjustment", "units", "frequency") if meta.get(k)]
    return f"{title} ({'; '.join(extras)})" if extras else title


def _period_word(series_id: str) -> str:
    freq = str(series_meta(series_id).get("frequency", "")).lower()
    return "quarter" if freq.startswith("q") else "month"


# --- prompts -------------------------------------------------------------------------


def system_prompt(task: Task) -> str:
    return SYSTEM_PROMPT.format(
        as_of_date=iso(task.as_of_date),
        answer_format=ANSWER_FORMATS[task.answer_type],
        survival=SURVIVAL_WORDING,
    )


def turn1_message(task: Task) -> str:
    return f"Question: {task.question}\nSeries ID for get_series: {task.series_id}"


def turn2_message(task: Task, requests: list[dict[str, Any]], root: Path) -> str:
    """The neutral turn-2 message: the SPEC sentence plus re-served turn-1 requests."""
    rev = iso(task.revision_date)
    parts = [TURN2_MESSAGE.format(revision_date=rev)]
    blobs = [json.dumps(get_series(args, rev, root)) for args in requests]
    if blobs:
        parts.append("\n".join(blobs))
    return "\n\n".join(parts)


def probe_messages(task: Task) -> list[Message]:
    dates = [iso(d) for d in tasks_mod.key_observations(task)]
    user = PROBE_USER.format(
        description=describe_series(task.series_id),
        period=_period_word(task.series_id),
        dates="\n".join(f"- {d}" for d in dates),
    )
    return [{"role": "system", "content": PROBE_SYSTEM}, {"role": "user", "content": user}]


# --- tool ----------------------------------------------------------------------------


def _parse_day(s: Any) -> date | None:
    if s in (None, ""):
        return None
    return pd.Timestamp(str(s)).date()


def get_series(args: dict[str, Any], as_of: str, root: Path) -> dict[str, Any]:
    """Serve ``series_id`` as known on ``as_of``, restricted to observations in [start, end].

    Uses only ``data.get_as_of``, so values from later vintages can never be served.
    Known series also get a static ``metadata`` block. Errors are returned to the
    model as ``{"error": ...}``, never raised.
    """
    try:
        series_id = str(args["series_id"]).strip().upper()
        start, end = _parse_day(args.get("start")), _parse_day(args.get("end"))
    except (KeyError, ValueError, TypeError) as exc:
        return {"error": f"bad arguments: {exc}"}
    known_ids = getattr(data, "SERIES", None)
    if known_ids and series_id not in known_ids:
        return {"error": f"unknown series {args.get('series_id')!r}"}
    try:
        known = data.get_as_of(series_id, day(as_of), root)
    except FileNotFoundError:
        if known_ids:
            raise  # data/raw missing for a known series: a setup error, not a model error
        return {"error": f"unknown series {args.get('series_id')!r}"}
    obs = [
        {"date": iso(d), "value": float(v)}
        for d, v in known.items()
        if pd.notna(v) and (start is None or day(d) >= start) and (end is None or day(d) <= end)
    ]
    result: dict[str, Any] = {"series_id": series_id, "as_of": iso(as_of)}
    meta = tool_metadata(series_id)
    if meta:
        result["metadata"] = meta
    result["observations"] = obs
    return result


def _run_tool(call: dict[str, Any], as_of: str, root: Path) -> dict[str, Any]:
    if call["name"] != "get_series":
        return {"error": f"unknown tool {call['name']!r}"}
    return get_series(call["arguments"], as_of, root)


def _request_key(args: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(args.get("series_id", "")).strip().upper(),
        str(args.get("start") or ""),
        str(args.get("end") or ""),
    )


def turn_requests(messages: list[Message]) -> list[dict[str, Any]]:
    """Distinct get_series argument dicts whose tool result had no error, in order."""
    results = {m.get("tool_call_id"): m for m in messages if m["role"] == "tool"}
    seen: dict[tuple[str, str, str], dict[str, Any]] = {}
    for m in messages:
        for tc in m.get("tool_calls") or []:
            fn = tc["function"]
            res = results.get(tc["id"])
            if fn["name"] != "get_series" or res is None:
                continue
            if "error" in json.loads(res["content"]):
                continue
            args = json.loads(fn["arguments"])
            seen.setdefault(_request_key(args), args)
    return list(seen.values())


# --- replies -------------------------------------------------------------------------


def parse_reply(text: str, key: str = "answer") -> dict[str, Any]:
    """Extract the reply JSON object (preferring one with ``key``)."""
    objs = iter_json_objects(text or "")
    for obj in objs:
        if key in obj:
            return obj
    if objs:
        return {"_error": f"reply JSON has no {key!r}", "_raw": text}
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
    reasoning_tokens: int = 0
    cost_usd: float = 0.0

    def add(self, r: ModelResponse) -> None:
        self.input_tokens += r.input_tokens
        self.output_tokens += r.output_tokens
        self.reasoning_tokens += r.reasoning_tokens
        self.cost_usd += r.cost_usd


def _call(
    agent: Agent,
    messages: list[Message],
    tools: list[ToolSpec],
    task: Task,
    root: Path,
    ids: dict[str, Any],
    model_kwargs: dict[str, Any],
) -> ModelResponse:
    if isinstance(agent, ModelSpec):
        return models.complete(agent, messages, tools, task_id=task.id, **ids, **model_kwargs)
    return agent(messages, tools, task=task, root=root)


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
        ids = {"turn": turn, "trial": trial, "step": step}
        resp = _call(agent, messages, TOOLS, task, root, ids, model_kwargs)
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

    Turn 1 serves get_series as of task.as_of_date; turn 2 re-serves the turn-1
    requests in the user message and serves the tool as of task.revision_date.
    ``root`` is the vintage data directory. ``model_kwargs`` are passed to
    :func:`models.complete` (client, cache_dir, budget, ...) for model agents.
    ``models.BudgetExceeded`` propagates to the caller.
    """
    root = Path(root)
    kwargs = model_kwargs or {}
    usage = _Usage()
    messages: list[Message] = [
        {"role": "system", "content": system_prompt(task)},
        {"role": "user", "content": turn1_message(task)},
    ]
    as_of, rev = iso(task.as_of_date), iso(task.revision_date)
    turn1 = _run_turn(agent, messages, task, root, 1, trial, as_of, usage, kwargs)
    requests = turn_requests(messages)
    messages.append({"role": "user", "content": turn2_message(task, requests, root)})
    turn2 = _run_turn(agent, messages, task, root, 2, trial, rev, usage, kwargs)
    return EpisodeRecord(
        task_id=task.id,
        agent=agent_name(agent),
        trial=trial,
        turn1=turn1,
        turn2=turn2,
        turn1_requests=requests,
        transcript=messages,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        reasoning_tokens=usage.reasoning_tokens,
        cost_usd=usage.cost_usd,
    )


def run_probe(
    task: Task,
    agent: Agent,
    root: Path,
    *,
    model_kwargs: dict[str, Any] | None = None,
) -> ProbeRecord:
    """Memorization probe: one call with no tools asking for the key observations.

    Cached (turn "probe", trial 1) and budgeted like episodes for model agents.
    """
    messages = probe_messages(task)
    ids = {"turn": PROBE_TURN, "trial": PROBE_TRIAL, "step": 0}
    resp = _call(agent, messages, [], task, Path(root), ids, model_kwargs or {})
    messages.append(_assistant_message(resp))
    return ProbeRecord(
        task_id=task.id,
        agent=agent_name(agent),
        dates=[iso(d) for d in tasks_mod.key_observations(task)],
        reply=parse_reply(resp.text, key="values"),
        transcript=messages,
        input_tokens=resp.input_tokens,
        output_tokens=resp.output_tokens,
        reasoning_tokens=resp.reasoning_tokens,
        cost_usd=resp.cost_usd,
    )
