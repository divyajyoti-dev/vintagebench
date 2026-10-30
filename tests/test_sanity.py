"""Sanity agents on the TOY fixture: exact expected scores, no network."""

from pathlib import Path

import pytest

from vintagebench import episode, grader, models, sanity
from vintagebench.tasks import load_tasks

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = FIXTURES / "vintages"
TASKS = load_tasks(FIXTURES / "tasks.jsonl")  # toy-001 flip, toy-002/003 controls

# per task (toy-001, toy-002, toy-003): (asof, revised, update, leakage, brier)
EXPECTED = {
    "oracle": [(1, 1, 1, 0, 0.0), (1, 1, 1, 0, 0.0), (1, 1, 1, 0, 0.0)],
    "always_yes": [(0, 1, 0, 0, 0.25), (1, 1, 1, 0, 0.25), (0, 0, 1, 0, 0.25)],
    "leaker": [(0, 1, 0, 1, 1.0), (1, 1, 1, 1, 0.0), (1, 1, 1, 1, 0.0)],
    "never_update": [(1, 0, 0, 0, 0.0), (1, 1, 1, 0, 0.0), (1, 1, 1, 0, 0.0)],
}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("sanity agents must not call models")

    monkeypatch.setattr(models, "complete", boom)
    monkeypatch.setattr(models, "make_client", boom)
    for var in ("OPENAI_API_KEY", "TOGETHER_API_KEY"):
        monkeypatch.delenv(var, raising=False)


@pytest.mark.parametrize("agent", sanity.SANITY_AGENTS, ids=lambda a: a.name)
def test_sanity_agent_scores_on_toy(agent):
    got = []
    for task in TASKS:
        rec = episode.run_episode(task, agent, trial=1, root=ROOT)
        s = grader.grade(task, rec, ROOT)
        got.append((s.asof_correct, s.revised_correct, s.update_correct, s.leakage, s.brier))
        assert rec.cost_usd == 0 and rec.agent == agent.name
    assert got == EXPECTED[agent.name]


def test_summary_of_sanity_agents():
    scores = [
        grader.grade(t, episode.run_episode(t, a, trial, ROOT), ROOT)
        for a in sanity.SANITY_AGENTS
        for t in TASKS
        for trial in (1, 2)
    ]
    df = grader.summarize(scores)
    o = df.loc["oracle"]
    assert (o["asof_correct"], o["revised_correct"], o["update_correct"]) == (1, 1, 1)
    assert (o["leakage_rate"], o["brier"], o["pass_k"]) == (0, 0, 1)
    assert df.loc["never_update", "update_correct_control"] == 1
    assert df.loc["never_update", "update_correct_flip"] == 0
    assert df.loc["leaker", "leakage_rate"] == 1
    assert df.loc["always_yes", "asof_correct"] == pytest.approx(1 / 3)
    assert df["cost_usd"].sum() == 0


def test_oracle_reports_served_as_of_values():
    rec = episode.run_episode(TASKS[0], sanity.oracle, trial=1, root=ROOT)
    assert rec.turn1["values_used"]["2020-06-01"] == 101.5
    assert len(rec.turn1["values_used"]) == 12
    assert sum(m["role"] == "tool" for m in rec.transcript) == 2  # tool used in both turns


def test_leaker_reports_latest_vintage():
    rec = episode.run_episode(TASKS[0], sanity.leaker, trial=1, root=ROOT)
    used = rec.turn1["values_used"]
    assert (used["2020-06-01"], used["2020-11-01"], used["2020-12-01"]) == (100.8, 102.7, 103.1)
