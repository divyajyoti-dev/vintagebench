"""models.complete with a fake OpenAI client: both tool paths, cache, retries, cost, budget."""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import httpx2
import openai
import pytest

from vintagebench import models
from vintagebench.models import Budget, BudgetExceeded, ModelSpec

NATIVE = ModelSpec("openai", "gpt-test", price_in=2.0, price_out=8.0, native_tools=True)
TEXT = ModelSpec("together", "org/open-model", price_in=1.0, price_out=1.0, native_tools=False)
TOOLS = [
    {
        "type": "function",
        "function": {"name": "get_series", "description": "d", "parameters": {"type": "object"}},
    }
]
MESSAGES = [
    {"role": "system", "content": "Today is 2021-01-15."},
    {"role": "user", "content": "Question?"},
]


def completion(text="", tool_calls=None, tin=100, tout=50):
    msg = SimpleNamespace(content=text, tool_calls=tool_calls)
    usage = SimpleNamespace(prompt_tokens=tin, completion_tokens=tout)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=usage)


def native_call(name, args, id_="call_1"):
    fn = SimpleNamespace(name=name, arguments=json.dumps(args))
    return SimpleNamespace(id=id_, function=fn)


class FakeClient:
    """Mimics client.chat.completions.create; replays scripted results or exceptions."""

    def __init__(self, *results):
        self.results = list(results)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests.append(kwargs)
        r = self.results.pop(0)
        if isinstance(r, BaseException):
            raise r
        return r


def conn_error():
    return openai.APIConnectionError(request=httpx2.Request("POST", "http://fake.invalid"))


def call(spec, client, tmp_path, **kw):
    return models.complete(spec, MESSAGES, TOOLS, client=client, cache_dir=tmp_path, **kw)


def test_native_tool_call_parsed(tmp_path):
    client = FakeClient(completion(tool_calls=[native_call("get_series", {"series_id": "TOY"})]))
    r = call(NATIVE, client, tmp_path)
    assert r.tool_calls == [
        {"id": "call_1", "name": "get_series", "arguments": {"series_id": "TOY"}}
    ]
    req = client.requests[0]
    assert req["tools"] == TOOLS and req["temperature"] == 0
    assert req["model"] == "gpt-test" and req["max_completion_tokens"] == 2048
    assert req["messages"] == MESSAGES


def test_native_bad_arguments_kept_raw(tmp_path):
    bad = SimpleNamespace(id="c", function=SimpleNamespace(name="get_series", arguments="{oops"))
    r = call(NATIVE, FakeClient(completion(tool_calls=[bad])), tmp_path)
    assert r.tool_calls[0]["arguments"] == {"_raw": "{oops"}


def test_text_protocol_request_and_parse(tmp_path):
    reply = 'Sure.\n```json\n{"tool": "get_series", "arguments": {"series_id": "TOY"}}\n```'
    client = FakeClient(completion(text=reply))
    r = call(TEXT, client, tmp_path)
    assert r.tool_calls == [
        {"id": "text-0", "name": "get_series", "arguments": {"series_id": "TOY"}}
    ]
    req = client.requests[0]
    assert "tools" not in req and req["max_tokens"] == 2048
    system = req["messages"][0]
    assert system["role"] == "system" and system["content"].startswith("Today is 2021-01-15.")
    assert "get_series" in system["content"] and '"tool"' in system["content"]


def test_text_protocol_translates_tool_history():
    history = MESSAGES + [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "get_series", "arguments": '{"series_id": "TOY"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "name": "get_series", "content": '{"x": 1}'},
    ]
    out = models.to_text_protocol(history, TOOLS)
    assert [m["role"] for m in out] == ["system", "user", "assistant", "user"]
    assert json.loads(out[2]["content"]) == {
        "tool": "get_series",
        "arguments": {"series_id": "TOY"},
    }
    assert out[3]["content"] == 'Tool result (get_series):\n{"x": 1}'
    assert all("tool_calls" not in m for m in out)


def test_text_final_answer_has_no_tool_calls(tmp_path):
    r = call(TEXT, FakeClient(completion(text='{"answer": "yes", "confidence": 0.7}')), tmp_path)
    assert r.tool_calls == [] and r.text.startswith('{"answer"')


def test_cost_math():
    assert models.cost_usd(NATIVE, 1_000_000, 0) == pytest.approx(2.0)
    assert models.cost_usd(NATIVE, 1000, 500) == pytest.approx((1000 * 2 + 500 * 8) / 1e6)


def test_tokens_and_cost_recorded(tmp_path):
    r = call(NATIVE, FakeClient(completion(text="hi", tin=1000, tout=500)), tmp_path)
    assert (r.input_tokens, r.output_tokens) == (1000, 500)
    assert r.cost_usd == pytest.approx(0.006) and not r.cached


def test_cache_hit_makes_no_client_call(tmp_path):
    first = call(NATIVE, FakeClient(completion(text="hi")), tmp_path, task_id="t1", turn=1, trial=2)
    files = list(Path(tmp_path).rglob("*.json"))
    assert len(files) == 1
    assert files[0].relative_to(tmp_path).parts[:4] == (
        "openai",
        "gpt-test",
        "openai_gpt-test",
        "t1",
    )
    assert files[0].name.startswith("turn1_trial2_step0_")
    empty = FakeClient()  # would raise IndexError if called
    again = call(NATIVE, empty, tmp_path, task_id="t1", turn=1, trial=2)
    assert empty.requests == [] and again.cached
    assert (again.text, again.cost_usd) == (first.text, first.cost_usd)


def test_cache_keyed_by_trial_and_request(tmp_path):
    call(NATIVE, FakeClient(completion(text="a")), tmp_path, task_id="t1", trial=1)
    other_trial = FakeClient(completion(text="b"))
    assert call(NATIVE, other_trial, tmp_path, task_id="t1", trial=2).text == "b"
    other_msgs = FakeClient(completion(text="c"))
    r = models.complete(
        NATIVE, MESSAGES[:1], TOOLS, client=other_msgs, cache_dir=tmp_path, task_id="t1", trial=1
    )
    assert r.text == "c" and len(other_msgs.requests) == 1


def test_cache_file_has_no_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-do-not-store")
    call(NATIVE, FakeClient(completion(text="hi")), tmp_path)
    for f in Path(tmp_path).rglob("*.json"):
        assert "sk-secret" not in f.read_text()


def test_retries_with_exponential_backoff(tmp_path):
    sleeps = []
    client = FakeClient(conn_error(), conn_error(), completion(text="ok"))
    r = call(NATIVE, client, tmp_path, sleep=sleeps.append, backoff_s=1.0)
    assert r.text == "ok" and len(client.requests) == 3 and sleeps == [1.0, 2.0]


def test_retries_exhausted_raises(tmp_path):
    client = FakeClient(*[conn_error() for _ in range(3)])
    with pytest.raises(openai.APIConnectionError):
        call(NATIVE, client, tmp_path, sleep=lambda s: None, max_retries=2)
    assert len(client.requests) == 3


def test_non_retryable_error_not_retried(tmp_path):
    client = FakeClient(ValueError("bad request"), completion(text="never"))
    with pytest.raises(ValueError):
        call(NATIVE, client, tmp_path, sleep=lambda s: None)
    assert len(client.requests) == 1


def test_budget_stops_before_call(tmp_path):
    client = FakeClient(completion(text="hi"))
    budget = Budget(limit_usd=0.001)  # max output alone: 2048 * 8 / 1e6 = 0.016
    with pytest.raises(BudgetExceeded):
        call(NATIVE, client, tmp_path, budget=budget)
    assert client.requests == [] and budget.spent_usd == 0


def test_budget_charged_but_not_on_cache_hit(tmp_path):
    budget = Budget(limit_usd=1.0)
    call(NATIVE, FakeClient(completion(text="hi", tin=1000, tout=500)), tmp_path, budget=budget)
    assert budget.spent_usd == pytest.approx(0.006)
    call(NATIVE, FakeClient(), tmp_path, budget=budget)
    assert budget.spent_usd == pytest.approx(0.006)


def test_budget_never_exceeded_over_many_calls(tmp_path):
    budget = Budget(limit_usd=0.05)
    n = 0
    with pytest.raises(BudgetExceeded):
        for i in range(100):
            client = FakeClient(completion(text="x", tin=1000, tout=2048))
            call(NATIVE, client, tmp_path, budget=budget, trial=i)
            n += 1
    assert 0 < n < 100 and budget.spent_usd <= 0.05


def test_load_model_specs(tmp_path):
    p = tmp_path / "models.yaml"
    p.write_text(
        "- {provider: together, model_id: org/m, price_in: 0.2, price_out: 0.6, "
        "native_tools: false}\n"
    )
    assert models.load_model_specs(p) == [ModelSpec("together", "org/m", 0.2, 0.6, False)]
    repo_cfg = Path(__file__).parents[1] / "config" / "models.yaml"
    assert all(isinstance(s, ModelSpec) for s in models.load_model_specs(repo_cfg))
    p.write_text("- {provider: other, model_id: m, price_in: 0, price_out: 0, native_tools: true}")
    with pytest.raises(ValueError):
        models.load_model_specs(p)


def test_make_client_requires_key(monkeypatch):
    monkeypatch.delenv("TOGETHER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="TOGETHER_API_KEY"):
        models.make_client("together")


def test_iter_json_objects():
    assert models.iter_json_objects('x {"a": 1} y {"b": {"c": 2}}') == [{"a": 1}, {"b": {"c": 2}}]
    assert models.iter_json_objects('```json\n{"a": 1}\n```') == [{"a": 1}]
    assert models.iter_json_objects("no json {here") == []


# --- reasoning_effort and effective settings -----------------------------------------


def _spec(effort):
    return ModelSpec("openai", "gpt-r", 1.0, 1.0, native_tools=True, reasoning_effort=effort)


@pytest.mark.parametrize(
    "effort,temp_sent",
    [(None, True), ("none", True), ("low", False), ("medium", False)],
)
def test_reasoning_effort_and_temperature(tmp_path, effort, temp_sent):
    client = FakeClient(completion(text="hi"))
    models.complete(_spec(effort), MESSAGES, TOOLS, client=client, cache_dir=tmp_path)
    req = client.requests[0]
    assert ("temperature" in req) is temp_sent
    if temp_sent:
        assert req["temperature"] == 0
    assert req.get("reasoning_effort") == effort
    assert ("reasoning_effort" in req) is (effort is not None)
    payload = json.loads(next(Path(tmp_path).rglob("*.json")).read_text())
    assert payload["settings"] == {
        "temperature": 0.0 if temp_sent else None,
        "temperature_sent": temp_sent,
        "reasoning_effort": effort,
    }
    assert payload["request"] == req


def test_reasoning_effort_changes_cache_key(tmp_path):
    models.complete(_spec("none"), MESSAGES, TOOLS, client=FakeClient(completion(text="a")),
                    cache_dir=tmp_path)  # fmt: skip
    other = FakeClient(completion(text="b"))
    r = models.complete(_spec("low"), MESSAGES, TOOLS, client=other, cache_dir=tmp_path)
    assert r.text == "b" and len(other.requests) == 1


# --- strict models.yaml loading ------------------------------------------------------

ROW = "provider: openai, model_id: m, price_in: 1, price_out: 2, native_tools: true"
TROW = "provider: openai, model_id: m, price_in: 1, price_out: 2, native_tools: false"


def test_load_model_specs_reasoning_effort(tmp_path):
    p = tmp_path / "models.yaml"
    p.write_text(f"- {{{ROW}, reasoning_effort: none}}\n- {{{ROW}}}\n")
    a, b = models.load_model_specs(p)
    assert a.reasoning_effort == "none" and b.reasoning_effort is None


@pytest.mark.parametrize(
    "row,match",
    [
        (f"{{{ROW}, temperature: 0}}", "unknown keys \\['temperature'\\]"),
        (f"{{{ROW}, reasoning: none}}", "unknown keys"),
        ("{provider: openai, model_id: m, price_in: 1, price_out: 2}", "missing \\['native_tools'"),
        (f"{{{ROW.replace('true', 'yes please')}}}", "native_tools must be"),
        (f"{{{ROW}, reasoning_effort: 3}}", "reasoning_effort must be a string"),
        (f"{{{ROW}, reasoning_effort: low}}", "function calling only with"),
        (f"{{{TROW}, max_tokens: lots}}", "max_tokens must be a number"),
        ("just a string", "expected a mapping"),
    ],
)
def test_load_model_specs_rejects_bad_entries(tmp_path, row, match):
    p = tmp_path / "models.yaml"
    p.write_text(f"- {row}\n")
    with pytest.raises(ValueError, match=match):
        models.load_model_specs(p)


def test_load_model_specs_rejects_non_list(tmp_path):
    p = tmp_path / "models.yaml"
    p.write_text("provider: openai\n")
    with pytest.raises(ValueError, match="expected a YAML list"):
        models.load_model_specs(p)


def test_repo_models_yaml_is_the_v1_config():
    specs = models.load_model_specs(Path(__file__).parents[1] / "config" / "models.yaml")
    assert [(s.name, s.model_id, s.reasoning_effort) for s in specs] == [
        ("gpt-6-sol/reasoning-off", "gpt-6-sol", "none"),
        ("gpt-6-sol/reasoning-low", "gpt-6-sol", "low"),
        ("gpt-6-luna/reasoning-off", "gpt-6-luna", "none"),
        ("gpt-6-luna/reasoning-low", "gpt-6-luna", "low"),
    ]
    assert all(s.provider == "openai" and not s.native_tools for s in specs)
    assert [s.max_tokens for s in specs] == [None, 8192, None, 8192]
    assert [(s.price_in, s.price_out) for s in specs] == [(2.0, 10.0)] * 2 + [(0.1, 0.5)] * 2


# --- measured usage from the cache ---------------------------------------------------


def _cache(tmp_path, task, turn, trial, step, tin, tout, text="x"):
    models.complete(
        NATIVE, MESSAGES + [{"role": "user", "content": text}], TOOLS,
        client=FakeClient(completion(text="r", tin=tin, tout=tout)), cache_dir=tmp_path,
        task_id=task, turn=turn, trial=trial, step=step,
    )  # fmt: skip


def test_cached_episode_usage(tmp_path):
    _cache(tmp_path, "t1", 1, 1, 0, 100, 10)
    _cache(tmp_path, "t1", 1, 1, 1, 200, 20)
    _cache(tmp_path, "t1", 2, 1, 0, 300, 30)
    _cache(tmp_path, "t2", 1, 1, 0, 999, 99)  # never reached turn 2: excluded
    _cache(tmp_path, "t3", 1, 2, 0, 50, 5, text="old")
    _cache(tmp_path, "t3", 1, 2, 0, 70, 7, text="new")  # same slot, newer request wins
    _cache(tmp_path, "t3", 2, 2, 0, 30, 3)
    old = next(p for p in Path(tmp_path).rglob("t3/turn1_*.json") if '"old"' in p.read_text())
    os.utime(old, (1, 1))
    usage = models.cached_episode_usage(NATIVE, tmp_path)
    assert [u[:2] for u in usage] == [(600, 60), (100, 10)]
    assert usage[0][2] == pytest.approx(models.cost_usd(NATIVE, 600, 60))
    assert models.cached_episode_usage(TEXT, tmp_path) == []
    assert models.cached_episode_usage(NATIVE, tmp_path / "missing") == []


# --- v1: config names, per-config max_tokens, reasoning-on, cached-token cost ---------

LOW = ModelSpec(
    "openai", "gpt-r", 2.0, 10.0, native_tools=False, reasoning_effort="low",
    name="gpt-r/reasoning-low", max_tokens=8192, price_cached_in=0.2, price_cache_write=2.5,
)  # fmt: skip


def test_name_defaults_to_provider_model():
    assert NATIVE.name == "openai/gpt-test"
    assert LOW.name == "gpt-r/reasoning-low" and LOW.reasoning_on and not NATIVE.reasoning_on


def test_reasoning_on_text_protocol_request(tmp_path):
    client = FakeClient(completion(text='{"answer": "no"}'))
    models.complete(LOW, MESSAGES, TOOLS, client=client, cache_dir=tmp_path, max_tokens=2048)
    req = client.requests[0]
    assert "temperature" not in req and "tools" not in req
    assert req["reasoning_effort"] == "low" and req["max_completion_tokens"] == 8192
    assert models.effective_max_tokens(LOW, 2048) == 8192
    assert models.effective_max_tokens(NATIVE, 2048) == 2048


def test_cache_dir_uses_config_name(tmp_path):
    models.complete(LOW, MESSAGES, TOOLS, client=FakeClient(completion(text="a")),
                    cache_dir=tmp_path, task_id="t1", turn=1)  # fmt: skip
    (f,) = Path(tmp_path).rglob("*.json")
    assert f.relative_to(tmp_path).parts[:4] == ("openai", "gpt-r", "gpt-r_reasoning-low", "t1")
    other = ModelSpec("openai", "gpt-r", 2.0, 10.0, False, "low", name="other")
    client = FakeClient(completion(text="b"))
    models.complete(other, MESSAGES, TOOLS, client=client, cache_dir=tmp_path, task_id="t1",
                    turn=1, max_tokens=8192)  # fmt: skip
    assert len(client.requests) == 1  # same request, different config: not shared


def test_usage_details_cost_and_reasoning_tokens(tmp_path):
    c = completion(text="x", tin=1000, tout=500)
    c.usage.prompt_tokens_details = SimpleNamespace(cached_tokens=600, cache_write_tokens=100)
    c.usage.completion_tokens_details = SimpleNamespace(reasoning_tokens=300)
    r = models.complete(LOW, MESSAGES, TOOLS, client=FakeClient(c), cache_dir=tmp_path)
    expected = (300 * 2.0 + 600 * 0.2 + 100 * 2.5 + 500 * 10.0) / 1e6
    assert r.cost_usd == pytest.approx(expected)
    assert (r.reasoning_tokens, r.cached_input_tokens) == (300, 600)
    again = models.complete(LOW, MESSAGES, TOOLS, client=FakeClient(), cache_dir=tmp_path)
    assert again.cached and again.reasoning_tokens == 300


def test_estimate_uses_highest_input_rate_and_full_output():
    est = models.estimate_cost(LOW, MESSAGES, TOOLS, 8192)
    chars = len(json.dumps(MESSAGES)) + len(json.dumps(TOOLS))
    assert est == pytest.approx(((chars // 3 + 1) * 2.5 + 8192 * 10.0) / 1e6)


def test_probe_turn_cached_and_counted_separately(tmp_path):
    _cache(tmp_path, "t1", 1, 1, 0, 100, 10)
    _cache(tmp_path, "t1", 2, 1, 0, 100, 10)
    models.complete(NATIVE, MESSAGES, [], client=FakeClient(completion(text="p", tin=50, tout=5)),
                    cache_dir=tmp_path, task_id="t1", turn="probe", trial=1)  # fmt: skip
    assert any(f.name.startswith("turnprobe_trial1_step0_") for f in Path(tmp_path).rglob("*"))
    assert [u[:2] for u in models.cached_episode_usage(NATIVE, tmp_path)] == [(200, 20)]
    assert [u[:2] for u in models.cached_probe_usage(NATIVE, tmp_path)] == [(50, 5)]


def test_budget_ledger_is_cumulative(tmp_path):
    ledger = tmp_path / "ledger.json"
    b = Budget.from_ledger(1.0, ledger)
    assert b.spent_usd == 0
    b.charge(0.4)
    b2 = Budget.from_ledger(1.0, ledger)
    assert b2.spent_usd == pytest.approx(0.4)
    with pytest.raises(BudgetExceeded):
        b2.check(0.7)


def test_load_model_specs_v1_fields(tmp_path):
    p = tmp_path / "models.yaml"
    p.write_text(
        f"- {{{TROW}, name: a/low, reasoning_effort: low, max_tokens: 8192, "
        "price_cached_in: 0.1, price_cache_write: 1.25}\n"
    )
    (s,) = models.load_model_specs(p)
    assert (s.name, s.max_tokens, s.price_cached_in, s.price_cache_write) == (
        "a/low",
        8192,
        0.1,
        1.25,
    )
    p.write_text(f"- {{{TROW}, name: x}}\n- {{{TROW}, name: x}}\n")
    with pytest.raises(ValueError, match="duplicate config names"):
        models.load_model_specs(p)
