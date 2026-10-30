"""Deterministic grader: answers, update, leakage tolerance, Brier, summarize."""

import math
from dataclasses import replace
from pathlib import Path

import pytest

from vintagebench import grader
from vintagebench.episode import EpisodeRecord
from vintagebench.grader import Scores
from vintagebench.tasks import load_tasks

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = FIXTURES / "vintages"
TASKS = {t.id: t for t in load_tasks(FIXTURES / "tasks.jsonl")}
TOY1, TOY2, TOY3 = TASKS["toy-001"], TASKS["toy-002"], TASKS["toy-003"]


def record(turn1, turn2, task_id="toy-001", agent="a", trial=1, cost=0.0):
    return EpisodeRecord(task_id, agent, trial, turn1, turn2, cost_usd=cost)


@pytest.mark.parametrize(
    "answer,expected",
    [
        ("no", True), ("No.", True), (False, True), ("false", True), ("NO - it rose", True),
        ("yes", False), (True, False), ("maybe", False), (None, False), (0, False),
    ],
)  # fmt: skip
def test_yes_no_answers(answer, expected):
    assert grader.answer_correct(answer, False, "yes_no") is expected


@pytest.mark.parametrize(
    "answer,expected",
    [
        (0.4, True), ("0.4", True), (0.4000000000000057, True), (0.44, True), ("+0.4%", True),
        (0.46, False), (0.3, False), ("yes", False), (None, False), (True, False),
        (float("nan"), False),
    ],
)  # fmt: skip
def test_number_answers(answer, expected):
    assert grader.answer_correct(answer, 0.4, "number") is expected


def test_number_tolerance_relative_for_large_values():
    assert grader.answer_correct("150,123", 150000.0, "number")  # within 1%
    assert not grader.answer_correct(152000, 150000.0, "number")


def leak(values, task=TOY1):
    return grader.leaked(task, values, ROOT)


def test_leakage_exact_values():
    assert not leak({"2020-06-01": 101.5})  # as-of value
    assert leak({"2020-06-01": 100.8})  # revised in the 2021-02-15 vintage
    assert leak({"2020-11-01": 102.7})  # revised in a later (2021-03-15) vintage
    assert leak({"2020-12-01": 103.2})  # an intermediate later vintage counts too
    assert leak({"2020-01-01": 100.0, "2020-06-01": 100.8})  # any one entry suffices
    assert not leak({"2020-06-01": 99.0})  # matches nothing: wrong, but not leakage
    assert not leak({}) and not leak(None) and not leak("101.5")


def test_leakage_key_and_value_formats():
    assert leak({"2020-06": "100.80"})
    assert leak({"June 2020": "100.8"})
    assert not leak({"not a date": 100.8, "2020-06-01": "n/a"})


def test_leakage_rounding_tolerance():
    # tolerance: half a unit in the last decimal place the agent reported
    assert not leak({"2020-06-01": 101})  # |101 - 101.5| <= 0.5: consistent with as-of
    assert not leak({"2020-12-01": 103})  # consistent with as-of 103.0
    assert leak({"2020-12-01": "103.20"})  # 2 decimals: only the later 103.2 matches
    assert not leak({"2020-06-01": 100.84})  # tol 0.005: matches no vintage
    assert grader.decimals(101) == 0 and grader.decimals("100.80") == 2
    assert grader.decimals(0.1 + 0.2) == grader.MAX_DECIMALS


def test_leakage_for_values_not_yet_published():
    before_release = replace(TOY1, as_of_date="2021-01-01")
    assert leak({"2020-06-01": 101.5}, before_release)


def test_grade_full_episode():
    t1 = {"answer": "no", "confidence": 0.8, "values_used": {"2020-06-01": 101.5}}
    t2 = {"answer": "yes", "confidence": 0.9, "changed": True, "reason": ""}
    s = grader.grade(TOY1, record(t1, t2, cost=0.01), ROOT)
    assert s == Scores(
        "toy-001", "a", 1, True, True, True, True, False, pytest.approx(0.04), 0.01, "yes_no"
    )


def test_update_correct_is_changed_equals_flips():
    t1 = {"answer": "yes", "confidence": 1}
    for changed, flip_ok in [(True, True), (False, False), ("true", True), (None, False)]:
        t2 = {"answer": "yes", "changed": changed}
        assert grader.grade(TOY1, record(t1, t2), ROOT).update_correct is flip_ok
        control = grader.grade(TOY2, record(t1, t2, "toy-002"), ROOT).update_correct
        assert control is (changed is not None and not flip_ok)


def test_brier():
    def brier(task, answer, conf):
        return grader.grade(task, record({"answer": answer, "confidence": conf}, {}), ROOT).brier

    assert brier(TOY1, "no", 0.7) == pytest.approx(0.09)  # right, conf 0.7
    assert brier(TOY1, "yes", 0.7) == pytest.approx(0.49)  # wrong, conf 0.7
    assert brier(TOY3, 0.4, 0.6) == pytest.approx(0.16)  # number task: same rule
    assert brier(TOY1, "no", 1.7) == 0.0  # clipped to [0, 1]
    assert brier(TOY1, "yes", None) == 1.0  # missing confidence counts as 1
    assert brier(TOY1, "no", "80%") == pytest.approx(0.04)  # percent strings are /100


def _s(agent, task, trial, flips, asof, upd, leak=False, brier=0.0, cost=0.0):
    return Scores(task, agent, trial, flips, asof, asof, upd, leak, brier, cost)


def test_summarize():
    scores = [
        _s("m", "t1", 1, True, True, True, cost=0.5),
        _s("m", "t1", 2, True, False, False, leak=True, brier=1.0),
        _s("m", "t2", 1, False, True, True),
        _s("m", "t2", 2, False, True, False),
        _s("o", "t1", 1, True, True, True),
    ]
    df = grader.summarize(scores)
    assert list(df.index) == ["m", "o"] and list(df.columns) == grader.SUMMARY_COLUMNS
    m = df.loc["m"]
    assert (m["episodes"], m["tasks"], m["trials"]) == (4, 2, 2)
    assert m["asof_correct"] == 0.75 and m["update_correct"] == 0.5
    assert m["update_correct_flip"] == 0.5 and m["update_correct_control"] == 0.5
    assert m["leakage_rate"] == 0.25 and m["brier"] == 0.25
    assert m["pass_k"] == 0.5 and m["cost_usd"] == 0.5
    assert math.isnan(df.loc["o", "update_correct_control"])
    assert grader.summarize([]).empty


def test_summary_markdown():
    md = grader.summary_markdown([_s("m", "t1", 1, True, True, False)])
    assert md.splitlines()[0].startswith("| Agent |")
    assert "| m | 1 | 1/1 (100%) |" in md and "n/a" in md
