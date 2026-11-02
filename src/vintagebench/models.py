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

Cache layout:
``<cache_dir>/<provider>/<model>/<config name>/<task_id>/turn<T>_trial<R>_step<S>_<hash>.json``
where T is 1, 2 or "probe", step counts model calls within a turn and hash is a digest
of the exact request, so a changed prompt never reuses a stale response while reruns
are free.

Reasoning-on configs (reasoning_effort other than "none"): ``temperature`` is omitted
(OpenAI rejects it unless effort is "none") and ``max_completion_tokens`` counts
reasoning tokens too, so those configs set a larger per-config ``max_tokens``. GPT-6
Sol/Luna support Chat Completions function calling only with reasoning_effort "none"
(developers.openai.com/api/docs/models/gpt-6-sol, checked 2026-11-01), so
:func:`load_model_specs` rejects openai configs with native_tools and reasoning on;
those use the plain-text JSON tool protocol.

Cost uses the usage details when present: cached prompt tokens at ``price_cached_in``
and cache-write tokens at ``price_cache_write`` (defaults: price_in, 1.25 x price_in).
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
    name: str = ""
    max_tokens: int | None = None
    price_cached_in: float | None = None
    price_cache_write: float | None = None

    def __post_init__(self) -> None:
        if not self.name:
            effort = f"/reasoning-{self.reasoning_effort}" if self.reasoning_effort else ""
            object.__setattr__(self, "name", f"{self.provider}/{self.model_id}{effort}")

    @property
    def reasoning_on(self) -> bool:
        return self.reasoning_effort not in (None, "none")


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


def effective_max_tokens(spec: ModelSpec, default: int) -> int:
    """Max output tokens actually sent (per-config override, else the run default)."""
    return default if spec.max_tokens is None else spec.max_tokens


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
    reasoning_tokens: int = 0
    cached_input_tokens: int = 0


class BudgetExceeded(RuntimeError):
    """Raised before a call that could push spend past the budget cap."""


@dataclass
class Budget:
    """Tracks spend against a USD cap. ``check`` refuses calls that could exceed it.

    With a ``ledger`` file the cap is cumulative: spend recorded there by earlier runs
    counts (see :meth:`from_ledger`) and every charge is written back immediately.
    """

    limit_usd: float
    spent_usd: float = 0.0
    ledger: Path | None = None

    @classmethod
    def from_ledger(cls, limit_usd: float, ledger: Path) -> Budget:
        ledger = Path(ledger)
        spent = float(json.loads(ledger.read_text())["spent_usd"]) if ledger.exists() else 0.0
        return cls(limit_usd, spent, ledger)

    def check(self, estimate_usd: float) -> None:
        if self.spent_usd + estimate_usd > self.limit_usd:
            raise BudgetExceeded(
                f"budget cap ${self.limit_usd:.2f} would be exceeded "
                f"(spent ${self.spent_usd:.4f}, next call up to ${estimate_usd:.4f})"
            )

    def charge(self, cost_usd: float) -> None:
        self.spent_usd += cost_usd
        if self.ledger is not None:
            self.ledger.parent.mkdir(parents=True, exist_ok=True)
            self.ledger.write_text(json.dumps({"spent_usd": self.spent_usd}) + "\n")


def _cached_price(spec: ModelSpec) -> float:
    return spec.price_in if spec.price_cached_in is None else spec.price_cached_in


def _write_price(spec: ModelSpec) -> float:
    return 1.25 * spec.price_in if spec.price_cache_write is None else spec.price_cache_write


def cost_usd(
    spec: ModelSpec,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """Cost of one call; prices are USD per million tokens.

    ``input_tokens`` is the total prompt tokens; ``cached_tokens`` and
    ``cache_write_tokens`` are the parts of it billed at the cached / cache-write rates.
    Output tokens include reasoning tokens (billed as output).
    """
    plain = max(input_tokens - cached_tokens - cache_write_tokens, 0)
    total = (
        plain * spec.price_in
        + cached_tokens * _cached_price(spec)
        + cache_write_tokens * _write_price(spec)
        + output_tokens * spec.price_out
    )
    return total / 1_000_000


def estimate_cost(
    spec: ModelSpec, messages: list[Message], tools: list[ToolSpec], max_tokens: int
) -> float:
    """Conservative upper bound: ~3 chars per input token, all billed at the highest
    input rate (cache write), and the full ``max_tokens`` output."""
    chars = len(json.dumps(messages)) + len(json.dumps(tools))
    tin = chars // 3 + 1
    written = tin if _write_price(spec) > spec.price_in else 0
    return cost_usd(spec, tin, max_tokens, cache_write_tokens=written)


SPEC_REQUIRED = ("provider", "model_id", "price_in", "price_out", "native_tools")
SPEC_OPTIONAL = ("reasoning_effort", "name", "max_tokens", "price_cached_in", "price_cache_write")


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
        spec = ModelSpec(
            provider=row["provider"],
            model_id=str(row["model_id"]),
            price_in=float(row["price_in"]),
            price_out=float(row["price_out"]),
            native_tools=row["native_tools"],
            reasoning_effort=effort,
            name=str(row.get("name") or ""),
            max_tokens=_opt(row, "max_tokens", int, where),
            price_cached_in=_opt(row, "price_cached_in", float, where),
            price_cache_write=_opt(row, "price_cache_write", float, where),
        )
        if spec.provider == "openai" and spec.native_tools and spec.reasoning_on:
            raise ValueError(
                f"{where}: OpenAI Chat Completions supports function calling only with "
                "reasoning_effort none; set native_tools: false (plain-text JSON tools)"
            )
        specs.append(spec)
    names = [s.name for s in specs]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise ValueError(f"{path}: duplicate config names {dupes}")
    return specs


def _opt(row: dict[str, Any], key: str, cast: Callable[[Any], Any], where: str) -> Any:
    if row.get(key) is None:
        return None
    if isinstance(row[key], bool):
        raise ValueError(f"{where}: {key} must be a number")
    try:
        return cast(row[key])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{where}: {key} must be a number") from exc


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


def iter_json_objects(text: str, *, raw_numbers: bool = False) -> list[dict[str, Any]]:
    """All top-level JSON objects found in ``text`` (fenced blocks, prose, bare JSON).

    ``raw_numbers`` keeps JSON numbers as their original tokens (str), e.g. "237.110".
    """
    decoder = (
        json.JSONDecoder(parse_float=str, parse_int=str) if raw_numbers else json.JSONDecoder()
    )
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


Turn = int | str


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)


def config_cache_dir(cache_dir: Path, spec: ModelSpec) -> Path:
    """Cache directory of one model config (provider/model/config name)."""
    return Path(cache_dir) / spec.provider / _safe(spec.model_id) / _safe(spec.name)


def _cache_path(
    cache_dir: Path,
    spec: ModelSpec,
    task_id: str,
    turn: Turn,
    trial: int,
    step: int,
    request: dict,
) -> Path:
    digest = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()[:12]
    name = f"turn{turn}_trial{trial}_step{step}_{digest}.json"
    return config_cache_dir(cache_dir, spec) / _safe(task_id) / name


_CACHE_NAME = re.compile(r"turn(\d+|probe)_trial(\d+)_step(\d+)_[0-9a-f]+\.json")


def _newest_cached(spec: ModelSpec, cache_dir: Path) -> dict[tuple[str, str, int, int], dict]:
    """Newest cached response per (task, turn, trial, step) slot of ``spec``."""
    newest: dict[tuple[str, str, int, int], tuple[float, dict]] = {}
    for f in config_cache_dir(cache_dir, spec).glob("*/*.json"):
        m = _CACHE_NAME.fullmatch(f.name)
        if not m:
            continue
        key = (f.parent.name, m.group(1), int(m.group(2)), int(m.group(3)))
        mtime = f.stat().st_mtime
        if key in newest and newest[key][0] >= mtime:
            continue
        newest[key] = (mtime, json.loads(f.read_text())["response"])
    return {k: v[1] for k, v in newest.items()}


def _response_cost(spec: ModelSpec, resp: dict) -> float:
    """Cost of a cached response at the spec's current prices (cache-hit share kept)."""
    tin, tout = int(resp["input_tokens"]), int(resp["output_tokens"])
    return cost_usd(spec, tin, tout, int(resp.get("cached_input_tokens", 0) or 0))


def cached_episode_usage(spec: ModelSpec, cache_dir: Path) -> list[tuple[int, int, float]]:
    """Measured (input_tokens, output_tokens, cost_usd) per cached episode of ``spec``.

    Reads only the local cache, never the network. If a (task, turn, trial, step)
    slot has several cached requests (e.g. after a prompt change), the newest file is
    used. Only episodes that reached turn 2 count. Cost is at the spec's prices.
    """
    episodes: dict[tuple[str, int], list[float]] = {}
    turns: dict[tuple[str, int], set[str]] = {}
    for (task, turn, trial, _), resp in _newest_cached(spec, cache_dir).items():
        if turn == "probe":
            continue
        tot = episodes.setdefault((task, trial), [0, 0, 0.0])
        tot[0] += int(resp["input_tokens"])
        tot[1] += int(resp["output_tokens"])
        tot[2] += _response_cost(spec, resp)
        turns.setdefault((task, trial), set()).add(turn)
    return [
        (int(t[0]), int(t[1]), float(t[2])) for k, t in sorted(episodes.items()) if "2" in turns[k]
    ]


def cached_probe_usage(spec: ModelSpec, cache_dir: Path) -> list[tuple[int, int, float]]:
    """Measured (input_tokens, output_tokens, cost_usd) per cached probe call of ``spec``."""
    return [
        (int(r["input_tokens"]), int(r["output_tokens"]), _response_cost(spec, r))
        for (_, turn, _, _), r in sorted(_newest_cached(spec, cache_dir).items())
        if turn == "probe"
    ]


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
    pdet = getattr(usage, "prompt_tokens_details", None)
    cdet = getattr(usage, "completion_tokens_details", None)
    cached = int(getattr(pdet, "cached_tokens", 0) or 0)
    written = int(getattr(pdet, "cache_write_tokens", 0) or 0)
    reasoning = int(getattr(cdet, "reasoning_tokens", 0) or 0)
    return ModelResponse(
        text,
        calls,
        tin,
        tout,
        cost_usd(spec, tin, tout, cached, written),
        reasoning_tokens=reasoning,
        cached_input_tokens=cached,
    )


def _as_dict(x: Any) -> dict[str, Any]:
    return x if isinstance(x, dict) else {"_raw": x}


def complete(
    spec: ModelSpec,
    messages: list[Message],
    tools: list[ToolSpec],
    *,
    task_id: str = "adhoc",
    turn: Turn = 0,
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
    ``spec.max_tokens``, when set, overrides ``max_tokens`` (reasoning tokens count as
    output, so reasoning-on configs need more).

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
    if spec.max_tokens is not None:
        max_tokens = spec.max_tokens
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
            "config": spec.name,
            "settings": settings,
            "request": request,
            "response": asdict(response),
        }
        path.write_text(json.dumps(payload, indent=1, default=str))
    return response
