"""Two-turn episodes on the TOY fixture, with scripted agents and a fake OpenAI client."""

import json
from dataclasses import asdict
from pathlib import Path

import pytest
from test_models import FakeClient, completion, native_call

from vintagebench import episode, grader
from vintagebench.models import ModelResponse, ModelSpec
from vintagebench.tasks import load_tasks

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = FIXTURES / "vintages"
TASKS = {t.id: t for t in load_tasks(FIXTURES / "tasks.jsonl")}
TOY1 = TASKS["toy-001"]
JUNE_ARGS = {"series_id": "TOY", "start": "2020-05-01", "end": "2020-06-01"}


class Scripted:
    """Sanity-agent-shaped stub replaying responses and recording what it was shown."""

    name = "scripted"

    def __init__(self, *responses):
        self.responses = list(responses)
        self.seen = []

    def __call__(self, messages, tools, *, task, root):
        self.seen.append([dict(m) for m in messages])
        return self.responses.pop(0)


def tool(args):
    return ModelResponse("", [{"id": "c1", "name": "get_series", "arguments": args}])


def text(obj):
    return ModelResponse(obj if isinstance(obj, str) else json.dumps(obj))


T1 = {"answer": "no", "confidence": 0.8, "values_used": {"2020-06-01": 101.5}, "caveats": ""}
T2 = {"answer": "yes", "confidence": 0.9, "changed": True, "reason": "June revised"}


def test_get_series_serves_only_as_of_data_within_range():
    r = episode.get_series(JUNE_ARGS, "2021-01-15", ROOT)
    assert r["observations"] == [
        {"date": "2020-05-01", "value": 101.0},
        {"date": "2020-06-01", "value": 101.5},
    ]
    r2 = episode.get_series(JUNE_ARGS, "2021-02-15", ROOT)
    assert r2["observations"][1] == {"date": "2020-06-01", "value": 100.8}
    assert len(episode.get_series({"series_id": "toy"}, "2021-01-15", ROOT)["observations"]) == 12


def test_get_series_errors_are_returned_not_raised():
    assert "error" in episode.get_series({"series_id": "NOPE"}, "2021-01-15", ROOT)
    assert "error" in episode.get_series({"start": "2020-01-01"}, "2021-01-15", ROOT)
    bad = {"series_id": "TOY", "start": "not a date"}
    assert "error" in episode.get_series(bad, "2021-01-15", ROOT)
    # nothing published yet
    assert episode.get_series({"series_id": "TOY"}, "2020-06-01", ROOT)["observations"] == []


def test_two_turns_serve_as_of_then_revision_data():
    agent = Scripted(tool(JUNE_ARGS), text(T1), tool(JUNE_ARGS), text(T2))
    rec = episode.run_episode(TOY1, agent, trial=1, root=ROOT)
    assert rec.turn1 == T1 and rec.turn2 == T2
    assert (rec.task_id, rec.agent, rec.trial) == ("toy-001", "scripted", 1)
    system, user1 = rec.transcript[0], rec.transcript[1]
    assert system["role"] == "system" and system["content"].startswith("Today is 2021-01-15.")
    assert TOY1.question in user1["content"]
    tool_msgs = [json.loads(m["content"]) for m in rec.transcript if m["role"] == "tool"]
    assert [t["as_of"] for t in tool_msgs] == ["2021-01-15", "2021-02-15"]
    assert tool_msgs[0]["observations"][1]["value"] == 101.5
    assert tool_msgs[1]["observations"][1]["value"] == 100.8
    turn2_user = [m for m in rec.transcript if m["role"] == "user"][1]
    assert turn2_user["content"] == (
        "A new data release is available as of 2021-02-15. Re-check your conclusion."
    )
    s = grader.grade(TOY1, rec, ROOT)
    assert s.asof_correct and s.revised_correct and s.update_correct and not s.leakage


def test_prompts_never_reveal_gold_notes_or_later_values():
    agent = Scripted(tool({"series_id": "TOY"}), text(T1), tool({"series_id": "TOY"}), text(T2))
    for task in TASKS.values():
        agent.responses = [
            tool({"series_id": "TOY"}),
            text(T1),
            tool({"series_id": "TOY"}),
            text(T2),
        ]
        rec = episode.run_episode(task, agent, trial=1, root=ROOT)
        prompts = " ".join(m["content"] for m in rec.transcript if m["role"] in ("system", "user"))
        assert task.notes not in prompts and task.id not in prompts
        for word in ("gold", "flips", "notes", "revised"):
            assert word not in prompts.lower()
        assert task.revision_date not in prompts.split("A new data release")[0]
        assert task.as_of_date in prompts and task.revision_date in prompts
        # turn-1 tool output carries no later-vintage values
        turn1 = rec.transcript[: [m["role"] for m in rec.transcript].index("user", 2)]
        turn1_tool = " ".join(m["content"] for m in turn1 if m["role"] == "tool")
        for later in ("100.8", "103.2", "103.1", "102.7"):
            assert later not in turn1_tool
        # exactly what the agent saw is the transcript
        assert agent.seen[-1] == [dict(m) for m in rec.transcript[: len(agent.seen[-1])]]


def test_parse_reply_variants():
    assert episode.parse_reply('{"answer": "yes"}') == {"answer": "yes"}
    fenced = 'Here you go:\n```json\n{"answer": "no", "confidence": 0.6}\n```\nThanks.'
    assert episode.parse_reply(fenced) == {"answer": "no", "confidence": 0.6}
    prose = 'Reasoning... {"note": 1} then {"answer": 0.4, "confidence": 1}'
    assert episode.parse_reply(prose)["answer"] == 0.4
    assert episode.parse_reply("I think yes.")["_error"] == "unparsable reply"
    assert "_error" in episode.parse_reply('{"result": "yes"}')
    assert "_error" in episode.parse_reply("")


def test_unparsable_replies_are_recorded_and_graded_wrong():
    agent = Scripted(text("yes, it fell"), text("still yes"))
    rec = episode.run_episode(TOY1, agent, trial=1, root=ROOT)
    assert rec.turn1["_raw"] == "yes, it fell" and "_error" in rec.turn2
    s = grader.grade(TOY1, rec, ROOT)
    assert not (s.asof_correct or s.revised_correct or s.update_correct or s.leakage)
    assert s.brier == 1.0


def test_tool_call_iterations_capped():
    agent = Scripted(*[tool(JUNE_ARGS)] * episode.MAX_STEPS, text(T2))
    rec = episode.run_episode(TOY1, agent, trial=1, root=ROOT)
    assert "_error" in rec.turn1 and rec.turn2 == T2
    assert sum(m["role"] == "tool" for m in rec.transcript) == episode.MAX_STEPS


def test_unknown_tool_gets_error_result():
    bad = ModelResponse("", [{"id": "x", "name": "web_search", "arguments": {}}])
    agent = Scripted(bad, text(T1), text(T2))
    rec = episode.run_episode(TOY1, agent, trial=1, root=ROOT)
    assert "error" in json.loads(rec.transcript[3]["content"]) and rec.turn1 == T1


def test_native_model_episode_with_fake_client(tmp_path):
    spec = ModelSpec("openai", "gpt-test", 1.0, 2.0, native_tools=True)
    client = FakeClient(
        completion(tool_calls=[native_call("get_series", JUNE_ARGS)], tin=100, tout=10),
        completion(text=json.dumps(T1), tin=200, tout=20),
        completion(tool_calls=[native_call("get_series", JUNE_ARGS, "c2")], tin=300, tout=10),
        completion(text="```json\n" + json.dumps(T2) + "\n```", tin=400, tout=20),
    )
    kw = {"client": client, "cache_dir": tmp_path}
    rec = episode.run_episode(TOY1, spec, trial=1, root=ROOT, model_kwargs=kw)
    assert rec.agent == "openai/gpt-test" and rec.turn1 == T1 and rec.turn2 == T2
    assert (rec.input_tokens, rec.output_tokens) == (1000, 60)
    assert rec.cost_usd == pytest.approx((1000 * 1.0 + 60 * 2.0) / 1e6)
    assert client.requests[0]["tools"] == episode.TOOLS
    # turn-2 tool result reached the model as a native tool message
    last = client.requests[3]["messages"][-1]
    assert last["role"] == "tool" and json.loads(last["content"])["as_of"] == "2021-02-15"
    json.dumps(asdict(rec))  # record is JSON-serialisable
    # rerun is fully cached: no client calls
    rerun = episode.run_episode(
        TOY1, spec, trial=1, root=ROOT, model_kwargs={"client": FakeClient(), "cache_dir": tmp_path}
    )
    assert rerun.turn1 == T1 and rerun.turn2 == T2


def test_text_protocol_model_episode_with_fake_client(tmp_path):
    spec = ModelSpec("together", "org/open", 0.5, 0.5, native_tools=False)
    req = json.dumps({"tool": "get_series", "arguments": JUNE_ARGS})
    client = FakeClient(
        completion(text=req),
        completion(text="Answer:\n" + json.dumps(T1)),
        completion(text="```json\n" + req + "\n```"),
        completion(text=json.dumps(T2)),
    )
    rec = episode.run_episode(
        TOY1, spec, trial=1, root=ROOT, model_kwargs={"client": client, "cache_dir": tmp_path}
    )
    assert rec.turn1 == T1 and rec.turn2 == T2
    for r in client.requests:
        assert "tools" not in r
        assert all(m["role"] in ("system", "user", "assistant") for m in r["messages"])
    tool_result = client.requests[1]["messages"][-1]
    assert tool_result["role"] == "user" and tool_result["content"].startswith("Tool result")
    assert '"value": 101.5' in tool_result["content"]
    assert '"value": 100.8' in client.requests[3]["messages"][-1]["content"]
