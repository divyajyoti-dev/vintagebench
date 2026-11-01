"""Two-turn episodes and the probe on synthetic data, with scripted agents and a fake
OpenAI client. No network."""

import json
from dataclasses import asdict

import pytest
from harness_fakes import FLIP, TASKS, V1, V2, install
from test_models import FakeClient, completion, native_call

from vintagebench import episode
from vintagebench.models import ModelResponse, ModelSpec

ROOT = "unused-root"
JUNE_ARGS = {"series_id": "TOY", "start": "2020-05-01", "end": "2020-06-01"}
T1 = {
    "calculation": "June is above May, so no.",
    "answer": "no",
    "confidence": 0.8,
    "survival_prob": 0.7,
    "values_used": {"2020-05-01": 101.1, "2020-06-01": 101.5},
    "caveats": "",
}
T2 = {
    "calculation": "June is now below May; the answer is yes.",
    "answer": "yes",
    "confidence": 0.9,
    "changed": True,
    "values_used": {"2020-05-01": 101.1, "2020-06-01": 100.8},
    "reason": "June revised",
}


@pytest.fixture(autouse=True)
def fake_data(monkeypatch):
    install(monkeypatch)


class Scripted:
    """Sanity-agent-shaped stub replaying responses and recording what it was shown."""

    name = "scripted"

    def __init__(self, *responses):
        self.responses = list(responses)
        self.seen = []
        self.tools = []

    def __call__(self, messages, tools, *, task, root):
        self.seen.append([dict(m) for m in messages])
        self.tools.append(tools)
        return self.responses.pop(0)


def tool(args, id_="c1"):
    return ModelResponse("", [{"id": id_, "name": "get_series", "arguments": args}])


def text(obj):
    return ModelResponse(obj if isinstance(obj, str) else json.dumps(obj))


def users(rec):
    return [m["content"] for m in rec.transcript if m["role"] == "user"]


# --- tool ----------------------------------------------------------------------------


def test_get_series_serves_only_as_of_data_within_range():
    r = episode.get_series(JUNE_ARGS, "2021-01-15", ROOT)
    assert r["observations"] == [
        {"date": "2020-05-01", "value": 101.1},
        {"date": "2020-06-01", "value": 101.5},
    ]
    assert r["as_of"] == "2021-01-15"
    r2 = episode.get_series(JUNE_ARGS, "2021-02-15", ROOT)
    assert r2["observations"][1] == {"date": "2020-06-01", "value": 100.8}
    assert len(episode.get_series({"series_id": "toy"}, "2021-01-15", ROOT)["observations"]) == 8


def test_get_series_metadata_from_data_series():
    r = episode.get_series(JUNE_ARGS, "2021-01-15", ROOT)
    assert list(r) == ["series_id", "as_of", "metadata", "observations"]
    assert r["metadata"] == {
        "title": "Toy activity index",
        "units": "index",
        "frequency": "Monthly",
        "seasonal_adjustment": "seasonally adjusted",
    }  # rounding unit is internal, not shown
    assert r["metadata"] == episode.get_series(JUNE_ARGS, "2022-03-15", ROOT)["metadata"]


def test_get_series_errors_are_returned_not_raised():
    assert (
        "unknown series" in episode.get_series({"series_id": "NOPE"}, "2021-01-15", ROOT)["error"]
    )
    assert "error" in episode.get_series({"start": "2020-01-01"}, "2021-01-15", ROOT)
    bad = {"series_id": "TOY", "start": "not a date"}
    assert "error" in episode.get_series(bad, "2021-01-15", ROOT)
    assert episode.get_series({"series_id": "TOY"}, "2020-06-01", ROOT)["observations"] == []


# --- prompts -------------------------------------------------------------------------


def test_system_prompt_key_order_and_survival_wording():
    sp = episode.system_prompt(FLIP)
    assert sp.startswith("Today is 2021-01-15.")
    assert "ONLY data as published as of today" in sp
    assert episode.SURVIVAL_WORDING == (
        "Probability (0-1) that this conclusion still holds after the data is fully revised"
    )
    assert episode.SURVIVAL_WORDING in sp
    first, second = sp.split("If you are later told")
    keys1 = ["calculation", "answer", "confidence", "survival_prob", "values_used", "caveats"]
    keys2 = ["calculation", "answer", "confidence", "changed", "values_used", "reason"]
    for block, keys in ((first, keys1), (second, keys2)):
        pos = [block.index(f'"{k}"') for k in keys]
        assert pos == sorted(pos), keys
    assert "re-check" not in sp.lower() and "recheck" not in sp.lower()


def test_turn2_message_reserves_distinct_requests_as_of_revision():
    reqs = [JUNE_ARGS, {"series_id": "TOY", "start": "2020-01-01", "end": "2020-02-01"}]
    msg = episode.turn2_message(FLIP, reqs, ROOT)
    head, body = msg.split("\n\n", 1)
    assert head == "Today is 2021-02-15. Here is the latest data. Answer the question."
    blobs = [json.loads(line) for line in body.splitlines()]
    assert blobs == [episode.get_series(r, "2021-02-15", ROOT) for r in reqs]
    assert blobs[0]["observations"][1]["value"] == 100.8
    assert episode.turn2_message(FLIP, [], ROOT) == head


def test_turn_requests_dedupes_and_skips_errors():
    agent = Scripted(
        ModelResponse(
            "",
            [
                {"id": "a", "name": "get_series", "arguments": JUNE_ARGS},
                {"id": "b", "name": "get_series", "arguments": {**JUNE_ARGS, "series_id": "toy"}},
                {"id": "c", "name": "get_series", "arguments": {"series_id": "NOPE"}},
            ],
        ),
        text(T1),
        text(T2),
    )
    rec = episode.run_episode(FLIP, agent, trial=1, root=ROOT)
    assert rec.turn1_requests == [JUNE_ARGS]
    turn2 = users(rec)[1]
    assert turn2.count('"observations"') == 1 and '"value": 100.8' in turn2


# --- episodes ------------------------------------------------------------------------


def test_two_turns_neutral_message_and_revision_tool():
    agent = Scripted(tool(JUNE_ARGS), text(T1), tool(JUNE_ARGS, "c2"), text(T2))
    rec = episode.run_episode(FLIP, agent, trial=1, root=ROOT)
    assert rec.turn1 == T1 and rec.turn2 == T2
    assert (rec.task_id, rec.agent, rec.trial) == ("toy-flip", "scripted", 1)
    u1, u2 = users(rec)
    assert FLIP.question in u1 and "Series ID for get_series: TOY" in u1
    assert u2.startswith("Today is 2021-02-15. Here is the latest data. Answer the question.\n\n")
    assert json.loads(u2.split("\n\n", 1)[1]) == episode.get_series(JUNE_ARGS, V2.isoformat(), ROOT)
    tool_msgs = [json.loads(m["content"]) for m in rec.transcript if m["role"] == "tool"]
    assert [t["as_of"] for t in tool_msgs] == ["2021-01-15", "2021-02-15"]
    assert agent.tools == [episode.TOOLS] * 4  # tool stays available in turn 2
    assert agent.seen[-1] == [dict(m) for m in rec.transcript[: len(agent.seen[-1])]]


def test_no_turn1_request_sends_only_the_sentence():
    agent = Scripted(text(T1), text(T2))
    rec = episode.run_episode(FLIP, agent, trial=1, root=ROOT)
    assert users(rec)[1] == "Today is 2021-02-15. Here is the latest data. Answer the question."
    assert rec.turn1_requests == []


def test_prompts_never_reveal_gold_or_later_values():
    for task in TASKS:
        agent = Scripted(tool({"series_id": "TOY"}), text(T1), text(T2))
        rec = episode.run_episode(task, agent, trial=1, root=ROOT)
        prompts = " ".join(m["content"] for m in rec.transcript if m["role"] in ("system", "user"))
        for word in ("gold", "flip", "revised value", "re-check", task.kind):
            assert word not in prompts.lower()
        u1 = rec.transcript[: [m["role"] for m in rec.transcript].index("user", 2)]
        turn1_text = " ".join(str(m["content"]) for m in u1)
        assert V2.isoformat() not in turn1_text and "100.8" not in turn1_text
        assert "100.7" not in prompts  # latest vintage never served


def test_parse_reply_variants():
    assert episode.parse_reply('{"answer": "yes"}') == {"answer": "yes"}
    fenced = 'Here:\n```json\n{"calculation": "x", "answer": "no"}\n```\nThanks.'
    assert episode.parse_reply(fenced) == {"calculation": "x", "answer": "no"}
    assert episode.parse_reply("I think yes.")["_error"] == "unparsable reply"
    assert "_error" in episode.parse_reply('{"result": "yes"}')
    assert episode.parse_reply('{"values": {}}', key="values") == {"values": {}}


def test_tool_call_iterations_capped():
    agent = Scripted(*[tool(JUNE_ARGS)] * episode.MAX_STEPS, text(T2))
    rec = episode.run_episode(FLIP, agent, trial=1, root=ROOT)
    assert "_error" in rec.turn1 and rec.turn2 == T2


def test_native_model_episode_with_fake_client(tmp_path):
    spec = ModelSpec("openai", "gpt-test", 1.0, 2.0, native_tools=True, name="test/native")
    client = FakeClient(
        completion(tool_calls=[native_call("get_series", JUNE_ARGS)], tin=100, tout=10),
        completion(text=json.dumps(T1), tin=200, tout=20),
        completion(text="```json\n" + json.dumps(T2) + "\n```", tin=400, tout=20),
    )
    kw = {"client": client, "cache_dir": tmp_path}
    rec = episode.run_episode(FLIP, spec, trial=1, root=ROOT, model_kwargs=kw)
    assert rec.agent == "test/native" and rec.turn1 == T1 and rec.turn2 == T2
    assert (rec.input_tokens, rec.output_tokens) == (700, 50)
    assert rec.cost_usd == pytest.approx((700 * 1.0 + 50 * 2.0) / 1e6)
    assert client.requests[0]["tools"] == episode.TOOLS
    assert client.requests[2]["tools"] == episode.TOOLS
    last = client.requests[2]["messages"][-1]
    assert last["role"] == "user" and '"as_of": "2021-02-15"' in last["content"]
    json.dumps(asdict(rec))
    names = sorted(p.name.split("_step")[0] for p in tmp_path.rglob("*.json"))
    assert names == ["turn1_trial1", "turn1_trial1", "turn2_trial1"]
    rerun = episode.run_episode(
        FLIP, spec, trial=1, root=ROOT, model_kwargs={"client": FakeClient(), "cache_dir": tmp_path}
    )
    assert rerun.turn1 == T1 and rerun.turn2 == T2


def test_text_protocol_reasoning_episode_with_fake_client(tmp_path):
    spec = ModelSpec(
        "openai", "gpt-r", 1.0, 2.0, native_tools=False, reasoning_effort="low", max_tokens=8192
    )
    req = json.dumps({"tool": "get_series", "arguments": JUNE_ARGS})
    client = FakeClient(
        completion(text=req),
        completion(text="Answer:\n" + json.dumps(T1)),
        completion(text=json.dumps(T2)),
    )
    rec = episode.run_episode(
        FLIP, spec, trial=1, root=ROOT, model_kwargs={"client": client, "cache_dir": tmp_path}
    )
    assert rec.turn1 == T1 and rec.turn2 == T2 and rec.turn1_requests == [JUNE_ARGS]
    for r in client.requests:
        assert "tools" not in r and "temperature" not in r
        assert r["reasoning_effort"] == "low" and r["max_completion_tokens"] == 8192
        assert all(m["role"] in ("system", "user", "assistant") for m in r["messages"])
    tool_result = client.requests[1]["messages"][-1]
    assert (
        tool_result["content"].startswith("Tool result")
        and '"value": 101.5' in tool_result["content"]
    )
    t2 = client.requests[2]["messages"][-1]["content"]
    assert t2.startswith("Today is 2021-02-15.") and '"value": 100.8' in t2


# --- probe ---------------------------------------------------------------------------


def test_probe_prompt_has_no_date_or_tools(tmp_path):
    spec = ModelSpec("openai", "gpt-test", 1.0, 2.0, native_tools=True, name="cfg")
    reply = {"values": {"2020-05-01": 101.1, "2020-06-01": 100.7}}
    client = FakeClient(completion(text=json.dumps(reply), tin=80, tout=12))
    rec = episode.run_probe(
        FLIP, spec, ROOT, model_kwargs={"client": client, "cache_dir": tmp_path}
    )
    assert rec.reply == reply and rec.dates == ["2020-05-01", "2020-06-01"]
    assert rec.agent == "cfg" and (rec.input_tokens, rec.output_tokens) == (80, 12)
    sent = client.requests[0]
    assert "tools" not in sent
    prompt = " ".join(m["content"] for m in sent["messages"])
    assert "Today is" not in prompt and V1.isoformat() not in prompt
    assert V2.isoformat() not in prompt and FLIP.question not in prompt
    assert "US toy activity index (seasonally adjusted; index; Monthly)" in prompt
    assert "- 2020-05-01\n- 2020-06-01" in prompt and '{"values"' in prompt
    assert "first day of the observation month" in prompt
    (f,) = tmp_path.rglob("*.json")
    assert f.name.startswith("turnprobe_trial1_step0_")
    again = episode.run_probe(
        FLIP, spec, ROOT, model_kwargs={"client": FakeClient(), "cache_dir": tmp_path}
    )
    assert again.reply == reply


def test_probe_with_scripted_agent_gets_no_tools():
    agent = Scripted(text("no idea"))
    rec = episode.run_probe(FLIP, agent, ROOT)
    assert agent.tools == [[]] and "_error" in rec.reply


def test_metadata_is_neutral_about_revisions():
    assert episode.neutral("index, SA; base period varies by vintage") == "index, SA"
    assert episode.neutral("percent, SA") == "percent, SA"
    assert episode.neutral("revised often") == ""


def test_real_series_metadata_and_rounding(monkeypatch):
    """data.SERIES holds SeriesInfo dataclasses (title, units, frequency, decimals)."""
    from vintagebench import grader

    monkeypatch.undo()  # back to the real data module attributes
    real = getattr(episode.data, "SERIES", {})
    if "EMPLOY" not in real:
        pytest.skip("data.SERIES not yet available")
    for sid in real:
        text = json.dumps(episode.tool_metadata(sid)) + episode.describe_series(sid)
        assert "vintage" not in text.lower() and "revis" not in text.lower()
        assert grader.rounding_unit(sid) > 0
    assert episode.describe_series("EMPLOY").startswith("US nonfarm payroll employment")
