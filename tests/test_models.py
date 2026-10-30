"""models.complete with a fake OpenAI client: both tool paths, cache, retries, cost, budget."""

import json
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
    assert files[0].relative_to(tmp_path).parts[:3] == ("openai", "gpt-test", "t1")
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
