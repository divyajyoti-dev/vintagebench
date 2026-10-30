"""Model specs and provider calls via the OpenAI Python SDK (SPEC §4, §5).

Providers: "openai" (default base URL) and "together"
(base_url https://api.together.xyz/v1). API keys come from OPENAI_API_KEY /
TOGETHER_API_KEY and are never logged or cached.

``complete`` runs at temperature 0, retries transient errors with exponential backoff,
caches every request/response as JSON under ``runs/cache/`` and tracks tokens and cost.
Messages are always passed in OpenAI native tool-calling format (assistant messages with
``tool_calls``, ``role: "tool"`` results). When ``spec.native_tools`` is false they are
translated to a plain-text JSON tool protocol: the tools are described in the system
prompt, the model requests a tool by replying with ``{"tool": name, "arguments": {...}}``
and tool results come back as user messages.

Cache layout: ``<cache_dir>/<provider>/<model>/<task_id>/turn<T>_trial<R>_step<S>_<hash>.json``
where step counts model calls within a turn and hash is a digest of the exact request,
so a changed prompt never reuses a stale response while reruns are free.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import openai
import yaml

Provider = Literal["openai", "together"]
Message = dict[str, Any]
ToolSpec = dict[str, Any]

BASE_URLS: dict[str, str | None] = {"openai": None, "together": "https://api.together.xyz/v1"}
KEY_ENV = {"openai": "OPENAI_API_KEY", "together": "TOGETHER_API_KEY"}
CACHE_DIR: Path = Path(__file__).resolve().parents[2] / "runs" / "cache"
RETRYABLE: tuple[type[BaseException], ...] = (
    openai.APIConnectionError,  # includes APITimeoutError
    openai.RateLimitError,
    openai.InternalServerError,
)


@dataclass(frozen=True)
class ModelSpec:
    """A model entry from config/models.yaml. Prices are USD per million tokens."""

    provider: Provider
    model_id: str
    price_in: float
    price_out: float
    native_tools: bool
    reasoning_effort: str | None = None

    @property
    def name(self) -> str:
        return f"{self.provider}/{self.model_id}"


def effective_settings(spec: ModelSpec, temperature: float) -> dict[str, Any]:
    """Sampling settings actually sent for ``spec``.

    ``reasoning_effort`` is sent only when set in the spec. OpenAI reasoning models
    reject ``temperature`` unless reasoning is off, so temperature is sent only when
    reasoning_effort is unset or "none".
    """
    send_temp = spec.reasoning_effort in (None, "none")
    return {
        "temperature": temperature if send_temp else None,
        "temperature_sent": send_temp,
        "reasoning_effort": spec.reasoning_effort,
    }


@dataclass
class ModelResponse:
    """One completion: text, parsed tool calls, token usage and cost.

    ``tool_calls`` entries are ``{"id": str, "name": str, "arguments": dict}``.
    ``cached`` is true when served from the response cache (no spend this run).
    """

    text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cached: bool = False


class BudgetExceeded(RuntimeError):
    """Raised before a call that could push spend past the budget cap."""


@dataclass
class Budget:
    """Tracks spend against a USD cap. ``check`` refuses calls that could exceed it."""

    limit_usd: float
    spent_usd: float = 0.0

    def check(self, estimate_usd: float) -> None:
        if self.spent_usd + estimate_usd > self.limit_usd:
            raise BudgetExceeded(
                f"budget cap ${self.limit_usd:.2f} would be exceeded "
                f"(spent ${self.spent_usd:.4f}, next call up to ${estimate_usd:.4f})"
            )

    def charge(self, cost_usd: float) -> None:
        self.spent_usd += cost_usd


def cost_usd(spec: ModelSpec, input_tokens: int, output_tokens: int) -> float:
    """Cost of one call; prices are USD per million tokens."""
    return (input_tokens * spec.price_in + output_tokens * spec.price_out) / 1_000_000


def estimate_cost(
    spec: ModelSpec, messages: list[Message], tools: list[ToolSpec], max_tokens: int
) -> float:
    """Conservative upper bound: ~3 chars per input token, full ``max_tokens`` output."""
    chars = len(json.dumps(messages)) + len(json.dumps(tools))
    return cost_usd(spec, chars // 3 + 1, max_tokens)


SPEC_REQUIRED = ("provider", "model_id", "price_in", "price_out", "native_tools")
SPEC_OPTIONAL = ("reasoning_effort",)


def load_model_specs(path: Path) -> list[ModelSpec]:
    """Read config/models.yaml (a YAML list of ModelSpec fields).

    Unknown or missing keys, unknown providers and malformed values raise ValueError.
    """
    rows = yaml.safe_load(Path(path).read_text()) or []
    if not isinstance(rows, list):
        raise ValueError(f"{path}: expected a YAML list of models")
    specs = []
    for i, row in enumerate(rows):
        where = f"{path}: entry {i}"
        if not isinstance(row, dict):
            raise ValueError(f"{where}: expected a mapping")
        unknown = set(row) - set(SPEC_REQUIRED) - set(SPEC_OPTIONAL)
        missing = set(SPEC_REQUIRED) - set(row)
        if unknown or missing:
            raise ValueError(f"{where}: unknown keys {sorted(unknown)}, missing {sorted(missing)}")
        if row["provider"] not in BASE_URLS:
            raise ValueError(f"{where}: unknown provider {row['provider']!r}")
        if not isinstance(row["native_tools"], bool):
            raise ValueError(f"{where}: native_tools must be true or false")
        effort = row.get("reasoning_effort")
        if effort is not None and not isinstance(effort, str):
            raise ValueError(f"{where}: reasoning_effort must be a string")
        specs.append(
            ModelSpec(
                provider=row["provider"],
                model_id=str(row["model_id"]),
                price_in=float(row["price_in"]),
                price_out=float(row["price_out"]),
                native_tools=row["native_tools"],
                reasoning_effort=effort,
            )
        )
    return specs


def make_client(provider: str) -> Any:
    """Create an OpenAI SDK client for ``provider``. Network use only happens on calls."""
    key = os.environ.get(KEY_ENV[provider])
    if not key:
        raise RuntimeError(f"{KEY_ENV[provider]} is not set")
    return openai.OpenAI(api_key=key, base_url=BASE_URLS[provider], max_retries=0)


# --- plain-text JSON tool protocol ---------------------------------------------------

TEXT_PROTOCOL = """You have these tools:
{tools}

To call a tool, reply with ONLY a JSON object of the form
{{"tool": "<tool name>", "arguments": {{...}}}}
and nothing else. The tool result will be sent back to you in the next message.
When you have your final answer, reply with the requested answer JSON instead (no "tool" key)."""


def _render_tools(tools: list[ToolSpec]) -> str:
    lines = []
    for t in tools:
        fn = t.get("function", t)
        lines.append(
            f"- {fn['name']}: {fn.get('description', '')}\n"
            f"  parameters (JSON schema): {json.dumps(fn.get('parameters', {}))}"
        )
    return "\n".join(lines)


def to_text_protocol(messages: list[Message], tools: list[ToolSpec]) -> list[Message]:
    """Translate native tool-calling messages into plain-text protocol messages."""
    out: list[Message] = []
    protocol = TEXT_PROTOCOL.format(tools=_render_tools(tools)) if tools else ""
    has_system = any(m["role"] == "system" for m in messages)
    if protocol and not has_system:
        out.append({"role": "system", "content": protocol})
    for m in messages:
        role = m["role"]
        if role == "system":
            content = m["content"] + ("\n\n" + protocol if protocol else "")
            out.append({"role": "system", "content": content})
        elif role == "assistant" and m.get("tool_calls"):
            parts = [m["content"]] if m.get("content") else []
            for tc in m["tool_calls"]:
                fn = tc["function"]
                req = {"tool": fn["name"], "arguments": _loads_or_raw(fn["arguments"])}
                parts.append(json.dumps(req))
            out.append({"role": "assistant", "content": "\n".join(parts)})
        elif role == "tool":
            name = m.get("name", "tool")
            out.append({"role": "user", "content": f"Tool result ({name}):\n{m['content']}"})
        else:
            out.append({"role": role, "content": m.get("content") or ""})
    return out


def _loads_or_raw(s: Any) -> Any:
    if not isinstance(s, str):
        return s
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return {"_raw": s}


def iter_json_objects(text: str) -> list[dict[str, Any]]:
    """All top-level JSON objects found in ``text`` (fenced blocks, prose, bare JSON)."""
    decoder = json.JSONDecoder()
    found: list[dict[str, Any]] = []
    candidates = [m.group(1) for m in re.finditer(r"```(?:json)?\s*(.*?)```", text, re.S)]
    candidates.append(text)
    for chunk in candidates:
        i = chunk.find("{")
        while i != -1:
            try:
                obj, end = decoder.raw_decode(chunk, i)
            except json.JSONDecodeError:
                i = chunk.find("{", i + 1)
                continue
            if isinstance(obj, dict):
                found.append(obj)
            i = chunk.find("{", end)
        if found:
            break
    return found


def parse_text_tool_calls(text: str) -> list[dict[str, Any]]:
    """Tool requests ``{"tool": name, "arguments": {...}}`` in a plain-text reply."""
    calls = []
    for obj in iter_json_objects(text):
        if isinstance(obj.get("tool"), str):
            args = obj.get("arguments", {})
            calls.append(
                {
                    "id": f"text-{len(calls)}",
                    "name": obj["tool"],
                    "arguments": args if isinstance(args, dict) else {"_raw": args},
                }
            )
    return calls


# --- completion ----------------------------------------------------------------------


def _cache_path(
    cache_dir: Path, spec: ModelSpec, task_id: str, turn: int, trial: int, step: int, request: dict
) -> Path:
    digest = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()[:12]
    name = f"turn{turn}_trial{trial}_step{step}_{digest}.json"
    return Path(cache_dir) / spec.provider / _safe_model(spec) / task_id / name


def _safe_model(spec: ModelSpec) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", spec.model_id)


_CACHE_NAME = re.compile(r"turn(\d+)_trial(\d+)_step(\d+)_[0-9a-f]+\.json")


def cached_episode_usage(spec: ModelSpec, cache_dir: Path) -> list[tuple[int, int]]:
    """Measured (input_tokens, output_tokens) per cached episode of ``spec``.

    Reads only the local cache, never the network. If a (task, turn, trial, step)
    slot has several cached requests (e.g. after a prompt change), the newest file is
    used. Only episodes that reached turn 2 count.
    """
    newest: dict[tuple[str, int, int, int], tuple[float, int, int]] = {}
    for f in (Path(cache_dir) / spec.provider / _safe_model(spec)).glob("*/*.json"):
        m = _CACHE_NAME.fullmatch(f.name)
        if not m:
            continue
        turn, trial, step = (int(g) for g in m.groups())
        key = (f.parent.name, turn, trial, step)
        mtime = f.stat().st_mtime
        if key in newest and newest[key][0] >= mtime:
            continue
        resp = json.loads(f.read_text())["response"]
        newest[key] = (mtime, int(resp["input_tokens"]), int(resp["output_tokens"]))
    episodes: dict[tuple[str, int], list[int]] = {}
    turns: dict[tuple[str, int], set[int]] = {}
    for (task, turn, trial, _), (_, tin, tout) in newest.items():
        tot = episodes.setdefault((task, trial), [0, 0])
        tot[0] += tin
        tot[1] += tout
        turns.setdefault((task, trial), set()).add(turn)
    return [(t[0], t[1]) for k, t in sorted(episodes.items()) if 2 in turns[k]]


def _call_with_retries(
    fn: Callable[[], Any], max_retries: int, backoff_s: float, sleep: Callable[[float], None]
) -> Any:
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except RETRYABLE:
            if attempt == max_retries:
                raise
            sleep(backoff_s * 2**attempt)
    raise AssertionError("unreachable")


def _parse_completion(spec: ModelSpec, completion: Any) -> ModelResponse:
    msg = completion.choices[0].message
    text = msg.content or ""
    if spec.native_tools:
        calls = [
            {
                "id": tc.id,
                "name": tc.function.name,
                "arguments": _as_dict(_loads_or_raw(tc.function.arguments)),
            }
            for tc in (msg.tool_calls or [])
        ]
    else:
        calls = parse_text_tool_calls(text)
    usage = completion.usage
    tin = int(getattr(usage, "prompt_tokens", 0) or 0)
    tout = int(getattr(usage, "completion_tokens", 0) or 0)
    return ModelResponse(text, calls, tin, tout, cost_usd(spec, tin, tout))


def _as_dict(x: Any) -> dict[str, Any]:
    return x if isinstance(x, dict) else {"_raw": x}


def complete(
    spec: ModelSpec,
    messages: list[Message],
    tools: list[ToolSpec],
    *,
    task_id: str = "adhoc",
    turn: int = 0,
    trial: int = 0,
    step: int = 0,
    temperature: float = 0.0,
    max_tokens: int = 2048,
    client: Any = None,
    cache_dir: Path | None = CACHE_DIR,
    budget: Budget | None = None,
    max_retries: int = 4,
    backoff_s: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
) -> ModelResponse:
    """Call the model at temperature 0 with retries, caching and cost tracking.

    ``spec.reasoning_effort``, when set, is sent; temperature is then sent only if it
    is "none" (see :func:`effective_settings`, recorded in each cache file).

    Uses native tool calling when ``spec.native_tools`` is true, otherwise the
    plain-text JSON tool protocol. A cache hit makes no client call and is not
    charged to ``budget``. ``client`` defaults to :func:`make_client` (created only
    on a cache miss); tests inject a fake.
    """
    if spec.native_tools:
        wire = list(messages)
        request: dict[str, Any] = {"model": spec.model_id, "messages": wire}
        if tools:
            request["tools"] = tools
    else:
        request = {"model": spec.model_id, "messages": to_text_protocol(messages, tools)}
    settings = effective_settings(spec, temperature)
    if settings["temperature_sent"]:
        request["temperature"] = temperature
    if spec.reasoning_effort is not None:
        request["reasoning_effort"] = spec.reasoning_effort
    tok_key = "max_completion_tokens" if spec.provider == "openai" else "max_tokens"
    request[tok_key] = max_tokens

    path = None
    if cache_dir is not None:
        path = _cache_path(cache_dir, spec, task_id, turn, trial, step, request)
        if path.exists():
            stored = json.loads(path.read_text())["response"]
            return ModelResponse(**{**stored, "cached": True})

    if budget is not None:
        budget.check(estimate_cost(spec, request["messages"], tools, max_tokens))
    if client is None:
        client = make_client(spec.provider)
    completion = _call_with_retries(
        lambda: client.chat.completions.create(**request), max_retries, backoff_s, sleep
    )
    response = _parse_completion(spec, completion)
    if budget is not None:
        budget.charge(response.cost_usd)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "provider": spec.provider,
            "settings": settings,
            "request": request,
            "response": asdict(response),
        }
        path.write_text(json.dumps(payload, indent=1, default=str))
    return response
