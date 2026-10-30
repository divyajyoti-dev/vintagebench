"""Sanity agents on the TOY fixture: exact expected scores, no network."""

from pathlib import Path

import pandas as pd
import pytest

from vintagebench import episode, grader, models, sanity
from vintagebench.tasks import Task, load_tasks

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


# --- leaker: episode-level checks on a tmp fixture -----------------------------------

MONTHS = [f"2020-{m:02d}-01" for m in range(1, 13)]
FIRST = [100.0 + i / 10 for i in range(12)]


def _write_series(root, revisions):
    """LEAK series: first vintage 2021-01-15 with all 2020 months, plus later rows."""

    def d(s):
        return pd.Timestamp(s).date()

    rows = [("LEAK", d(m), d("2021-01-15"), v) for m, v in zip(MONTHS, FIRST, strict=True)]
    rows += [("LEAK", d(obs), d(vint), v) for vint, obs, v in revisions]
    cols = ["series_id", "observation_date", "vintage_date", "value"]
    pd.DataFrame(rows, columns=cols).to_parquet(root / "LEAK.parquet", index=False)


def _leak_task():
    return Task(
        id="leak-1", series_id="LEAK", as_of_date="2021-01-15",
        question="Did LEAK fall in June 2020 versus the prior month?", answer_type="yes_no",
        gold_as_of=False, revision_date="2021-02-15", gold_revised=False, flips=False,
    )  # fmt: skip


def _leaker_leakage(root):
    task = _leak_task()
    rec = episode.run_episode(task, sanity.leaker, trial=1, root=root)
    return grader.grade(task, rec, root).leakage, rec.turn1["values_used"]


def test_leaker_not_flagged_when_latest_equals_as_of(tmp_path):
    _write_series(tmp_path, [])  # single vintage: latest == as-of
    leakage, used = _leaker_leakage(tmp_path)
    assert len(used) == 12 and leakage is False


def test_leaker_not_flagged_when_later_vintage_repeats_as_of_values(tmp_path):
    _write_series(tmp_path, [("2021-02-15", "2020-06-01", FIRST[5])])  # unchanged value
    assert _leaker_leakage(tmp_path)[0] is False


def test_leaker_flagged_when_latest_differs(tmp_path):
    _write_series(tmp_path, [("2021-02-15", "2020-06-01", 99.9)])
    leakage, used = _leaker_leakage(tmp_path)
    assert used["2020-06-01"] == 99.9 and leakage is True


def test_leaker_flagged_for_observation_unpublished_at_as_of(tmp_path):
    # the window ends on as_of_date; 2021-01-01 was first published after as_of
    _write_series(tmp_path, [("2021-02-05", "2021-01-01", 101.5)])
    leakage, used = _leaker_leakage(tmp_path)
    assert "2021-01-01" in used and leakage is True
