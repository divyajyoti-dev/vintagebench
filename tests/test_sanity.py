"""Sanity agents hit their expected scores on synthetic data (SPEC §4.5). No network."""

import json

import pytest
from harness_fakes import CONTROL, FLIP, NO_CHANGE, TASKS, install

from vintagebench import grader, sanity
from vintagebench.episode import run_episode, run_probe

ROOT = "unused-root"


@pytest.fixture(autouse=True)
def fake_data(monkeypatch):
    install(monkeypatch)


def episodes(agent):
    return {t.id: grader.grade(t, run_episode(t, agent, 1, ROOT), ROOT) for t in TASKS}


def probes(agent):
    return {t.id: grader.grade_probe(t, run_probe(t, agent, ROOT), ROOT) for t in TASKS}


def test_oracle_is_perfect():
    for s in episodes(sanity.oracle).values():
        assert s.asof_correct and s.revised_correct and s.update_correct
        assert s.self_report_agrees is True and not s.leakage
        assert not (s.contradiction_t1 or s.contradiction_t2)
        assert s.confidence_brier == 0 and s.survival_brier == 0


def test_oracle_survival_prob_and_calculation():
    rec = run_episode(FLIP, sanity.oracle, 1, ROOT)
    assert rec.turn1["survival_prob"] == 0.0 and list(rec.turn1)[:2] == ["calculation", "answer"]
    assert run_episode(CONTROL, sanity.oracle, 1, ROOT).turn1["survival_prob"] == 1.0
    assert grader.final_conclusion(rec.turn1["calculation"]) is False
    assert grader.final_conclusion(rec.turn2["calculation"]) is True
    assert not any(ch.isdigit() for ch in rec.turn1["calculation"])
    # turn 2 answered from the re-served data in the user message, no extra tool call
    assert sum(m["role"] == "tool" for m in rec.transcript) == 1
    assert rec.turn2["values_used"] == {"2020-05-01": 101.1, "2020-06-01": 100.8}


def test_always_yes():
    s = episodes(sanity.always_yes)
    assert [s[t.id].asof_correct for t in TASKS] == [t.gold_as_of for t in TASKS]
    assert [s[t.id].update_correct for t in TASKS] == [not t.flips for t in TASKS]


def test_leaker_flagged_exactly_where_latest_differs():
    s = episodes(sanity.leaker)
    assert s[FLIP.id].leakage_t1 and s[NO_CHANGE.id].leakage_t1
    assert not s[CONTROL.id].leakage_t1
    assert [sanity.latest_differs(t, ROOT) for t in TASKS] == [True, False, True]
    assert not any(x.contradiction_t1 or x.contradiction_t2 for x in s.values())
    assert not s[NO_CHANGE.id].asof_correct  # latest March falls: answers yes


def test_never_update():
    s = episodes(sanity.never_update)
    for t in TASKS:
        assert s[t.id].asof_correct
        assert s[t.id].update_correct == (not t.flips) == s[t.id].revised_correct
        assert not s[t.id].leakage and not s[t.id].contradiction_t2


def test_probe_recallers():
    first = probes(sanity.first_release_recaller)
    latest = probes(sanity.latest_recaller)
    assert first[FLIP.id].task_class == "first_release"
    assert latest[FLIP.id].task_class == "latest"
    assert first[CONTROL.id].task_class == latest[CONTROL.id].task_class == "indistinguishable"
    assert first[CONTROL.id].counts["both"] == 2
    assert latest[NO_CHANGE.id].counts == {
        "first_release": 0, "latest": 1, "both": 1, "neither": 0, "no_answer": 0,
    }  # fmt: skip


def test_check_expectations_passes_and_catches_a_broken_agent():
    scores = [s for a in sanity.SANITY_AGENTS for s in episodes(a).values()]
    probe_scores = [p for a in sanity.PROBE_AGENTS for p in probes(a).values()]
    assert sanity.check_expectations(scores, probe_scores, TASKS, ROOT) == []

    class BadOracle(sanity.Oracle):
        def turn2(self, messages, task, root):
            r = super().turn2(messages, task, root)
            obj = json.loads(r.text)
            return type(r)(json.dumps({**obj, "answer": "no"}))

    bad = BadOracle()
    bad_scores = list(episodes(bad).values())
    assert all(s.agent == "oracle" for s in bad_scores)
    failures = sanity.check_expectations(bad_scores, [], TASKS, ROOT)
    assert any("toy-flip" in f and "revised_correct" in f for f in failures)
    swapped = [
        grader.ProbeScores(**{**p.__dict__, "agent": "first_release_recaller"})
        for p in probes(sanity.latest_recaller).values()
    ]
    assert sanity.check_expectations([], swapped, TASKS, ROOT)


def test_rate_probe_recallers(monkeypatch):
    from vintagebench import episode

    rate = episode.ProbeRate("mom_pct", "the month-over-month percent change of TOY", False)
    monkeypatch.setitem(episode.PROBE_RATES, "TOY", rate)
    first = probes(sanity.first_release_recaller)
    latest = probes(sanity.latest_recaller)
    assert first[FLIP.id].task_class == "first_release" and latest[FLIP.id].task_class == "latest"
    assert first[CONTROL.id].task_class == "indistinguishable"
    assert sanity.check_expectations([], [*first.values(), *latest.values()], TASKS, ROOT) == []
