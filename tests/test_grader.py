"""Deterministic grader on synthetic data: answers, updating, survival, leakage,
contradictions (incl. the conclusion regex), probe classification and summaries."""

import re

import pytest
from harness_fakes import CONTROL, FLIP, NO_CHANGE, install

from vintagebench import grader
from vintagebench.episode import EpisodeRecord, ProbeRecord

ROOT = "unused-root"


@pytest.fixture(autouse=True)
def fake_data(monkeypatch):
    install(monkeypatch)


def rec(t1, t2, agent="a", trial=1, task=FLIP, cost=0.0):
    return EpisodeRecord(task.id, agent, trial, t1, t2, cost_usd=cost)


def t1(answer, calc="", conf=0.9, surv=0.6, values=None):
    return {
        "calculation": calc,
        "answer": answer,
        "confidence": conf,
        "survival_prob": surv,
        "values_used": values or {},
        "caveats": "",
    }


def t2(answer, changed, calc="", values=None):
    return {
        "calculation": calc,
        "answer": answer,
        "confidence": 0.9,
        "changed": changed,
        "values_used": values or {},
        "reason": "",
    }


# --- final_conclusion regex ----------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("June is above May. The answer is no.", False),
        ("So the answer: no", False),
        ("Change is negative; therefore, yes.", True),
        ("May 101.1 -> June 100.8 → no", False),
        ("diff = -0.3 => yes", True),
        ("Hence: yes", True),
        ("Thus **no**.", False),
        ("Answer: **Yes** (fell)", True),
        ("The answer to the question would be yes because June fell.", True),
        ("Conclusion: no", False),
        ("It fell by a small amount. Yes", True),
        ("June dropped below May, yes.", True),
        # the last explicit conclusion wins
        ("At first glance the answer is yes, but recomputing, the answer is no.", False),
        ("So yes on the old data; on these values, therefore no.", False),
        # not conclusions
        ("The question is a yes or no question about June.", None),
        ("Reply yes/no based on the data. June 101.5 vs May 101.1", None),
        ("so no decline occurred in the level of May 101.1", None),
        ("The answer is not obvious from these numbers", None),
        ("noted: values 101.1 and 101.5", None),
        ("", None),
        (None, None),
    ],
)
def test_final_conclusion(text, expected):
    assert grader.final_conclusion(text) is expected


# --- episode grading -----------------------------------------------------------------


def test_flip_update_and_survival():
    s = grader.grade(FLIP, rec(t1("no", surv=0.2), t2("yes", True)), ROOT)
    assert s.asof_correct and s.revised_correct and s.changed and s.update_correct
    assert s.self_report_agrees is True
    assert s.survived is False and s.survival_brier == pytest.approx(0.04)
    assert s.confidence_brier == pytest.approx(0.01)
    assert s.kind == "flip" and s.parsed_t1 and s.parsed_t2


def test_changed_is_actual_change_not_self_report():
    s = grader.grade(FLIP, rec(t1("no"), t2("no", True)), ROOT)
    assert s.changed is False and not s.update_correct and s.self_report_agrees is False
    s = grader.grade(CONTROL, rec(t1("yes"), t2("yes", "false"), task=CONTROL), ROOT)
    assert s.update_correct and s.self_report_agrees is True and s.survived
    s = grader.grade(CONTROL, rec(t1("yes"), t2("no", None), task=CONTROL), ROOT)
    assert s.changed and not s.update_correct and s.self_report_agrees is None


def test_unparsable_answers():
    s = grader.grade(FLIP, rec({"_error": "x", "_raw": "?"}, t2("yes", True)), ROOT)
    assert not s.asof_correct and s.changed is None and not s.update_correct
    assert not s.survived and not s.parsed_t1 and s.parsed_t2
    assert s.confidence is None and s.confidence_brier is None and s.survival_brier is None
    assert not s.contradiction_t1


@pytest.mark.parametrize(
    "raw,expected",
    [
        (0.7, 0.7),
        ("80%", 0.8),
        ("0.3", 0.3),
        (1.5, None),
        ("high", None),
        (None, None),
        (True, None),
    ],
)
def test_parse_prob(raw, expected):
    got = grader.parse_prob(raw)
    assert got == (pytest.approx(expected) if expected is not None else None)


def test_leakage_per_turn():
    as_of = {"2020-05-01": 101.1, "2020-06-01": 101.5}
    revision = {"2020-05-01": 101.1, "2020-06-01": 100.8}
    latest = {"2020-05-01": 101.1, "2020-06-01": 100.7}
    ok = grader.grade(FLIP, rec(t1("no", values=as_of), t2("yes", True, values=revision)), ROOT)
    assert not ok.leakage_t1 and not ok.leakage_t2 and not ok.leakage
    bad1 = grader.grade(FLIP, rec(t1("yes", values=revision), t2("yes", False)), ROOT)
    assert bad1.leakage_t1 and not bad1.leakage_t2
    bad2 = grader.grade(FLIP, rec(t1("no"), t2("yes", True, values=latest)), ROOT)
    assert not bad2.leakage_t1 and bad2.leakage_t2 and bad2.leakage
    # rounded consistently with both vintages: not leakage ("101" matches 101.1 within 0.5)
    assert not grader.leaked(FLIP, {"2020-06": "101"}, ROOT)
    # unpublished as of as_of but present later: leakage
    assert not grader.leaked(FLIP, {"2020-09-01": 1.0}, ROOT)  # never published anywhere
    assert grader.leaked(FLIP, {"2020-06-01": 100.8}, ROOT, as_of="2021-01-15")
    assert not grader.leaked(FLIP, {"2020-06-01": 100.8}, ROOT, as_of="2021-02-15")


def test_contradiction_numbers_and_text():
    asof = {"2020-05-01": 101.1, "2020-06-01": 101.5}  # implies "no" (did not fall)
    s = grader.grade(FLIP, rec(t1("yes", values=asof), t2("yes", True)), ROOT)
    assert s.contradiction_numbers_t1 and not s.contradiction_text_t1 and s.contradiction_t1
    s = grader.grade(
        FLIP, rec(t1("no", calc="so the answer is yes.", values=asof), t2("yes", True)), ROOT
    )
    assert not s.contradiction_numbers_t1 and s.contradiction_text_t1
    s = grader.grade(
        FLIP, rec(t1("no", calc="therefore, no.", values=asof), t2("yes", True, calc="→ no")), ROOT
    )
    assert not s.contradiction_t1 and s.contradiction_text_t2 and not s.contradiction_numbers_t2
    # incomplete values: implied answer not computable, no numbers contradiction
    s = grader.grade(FLIP, rec(t1("yes", values={"2020-06-01": 101.5}), t2("yes", True)), ROOT)
    assert not s.contradiction_numbers_t1


def test_implied_tolerates_bad_entries():
    assert grader.implied(FLIP, {"2020-05": "101.1", "2020-06-01": "100.8", "x": "y"}) is True
    assert grader.implied(FLIP, "not a dict") is None


# --- probe ---------------------------------------------------------------------------


def test_classify_recall_rules():
    c = grader.classify_recall
    assert c(None, 101.5, 100.7, 0.1) == "no_answer"
    assert c(101.5, 101.5, 100.7, 0.1) == "first_release"
    assert c(101.45, 101.5, 100.7, 0.1) == "first_release"  # within one unit
    assert c(100.7, 101.5, 100.7, 0.1) == "latest"
    assert c(101.1, 101.5, 100.7, 0.1) == "neither"
    assert c(101.1, 101.1, 101.1, 0.1) == "both"
    assert c(105.0, 101.1, 101.1, 0.1) == "neither"
    assert c(100.05, 100.0, 100.15, 0.1) == "first_release"  # within both: nearer wins
    assert c(100.12, 100.0, 100.15, 0.1) == "latest"
    # relative part: unit 1, level 150000 -> tolerance 15
    assert c(150_010, 150_000, 150_100, 1.0) == "first_release"
    assert grader.probe_tolerance(1.0, 150_000) == pytest.approx(15.0)
    assert grader.probe_tolerance(0.1, 4.0) == 0.1


def test_grade_probe_majority_and_relative_errors():
    prec = ProbeRecord(
        FLIP.id,
        "cfg",
        ["2020-05-01", "2020-06-01"],
        {"values": {"2020-05-01": 101.1, "2020-06-01": 101.5}},
    )
    p = grader.grade_probe(FLIP, prec, ROOT)
    assert p.counts == {"first_release": 1, "latest": 0, "both": 1, "neither": 0, "no_answer": 0}
    assert p.task_class == "first_release"
    june = p.values[1]
    assert june["distinguishable"] and june["rel_err_first"] == 0
    assert june["rel_err_latest"] == pytest.approx((101.5 - 100.7) / 100.7)
    missing = grader.grade_probe(
        FLIP, ProbeRecord(FLIP.id, "cfg", prec.dates, {"values": {}}), ROOT
    )
    assert missing.task_class == "no_answer" and missing.counts["no_answer"] == 2
    ctrl = ProbeRecord(CONTROL.id, "cfg", ["2020-04-01", "2020-05-01"], {"values": {}})
    assert grader.grade_probe(CONTROL, ctrl, ROOT).task_class == "indistinguishable"


def test_task_majority_tie_is_mixed():
    assert grader.task_majority([("first_release", True), ("latest", True)]) == "mixed"
    assert grader.task_majority([("both", False)]) == "indistinguishable"
    assert grader.task_majority([("latest", True), ("latest", True), ("neither", True)]) == "latest"


# --- summaries -----------------------------------------------------------------------


def _scores():
    asof = {"2020-05-01": 101.1, "2020-06-01": 101.5}
    out = []
    for trial in (1, 2):
        out.append(
            grader.grade(
                FLIP,
                rec(t1("no", surv=0.9, values=asof), t2("yes", True), trial=trial, cost=0.01),
                ROOT,
            )
        )
        out.append(
            grader.grade(
                CONTROL,
                rec(t1("yes", surv=0.97), t2("yes", False), trial=trial, task=CONTROL),
                ROOT,
            )
        )
        out.append(
            grader.grade(
                NO_CHANGE,
                rec(t1("no", surv=0.6), t2("yes", True), trial=trial, task=NO_CHANGE),
                ROOT,
            )
        )
    return out


def test_summarize_rates():
    df = grader.summarize(_scores())
    row = df.loc["a"]
    assert (row["episodes"], row["tasks"], row["trials"]) == (6, 3, 2)
    assert row["update_correct_flip"] == 1 and row["update_correct_control"] == 1
    assert row["update_correct_no_change"] == 0
    assert row["survival_rate"] == pytest.approx(4 / 6)
    assert row["cost_usd"] == pytest.approx(0.02)


def test_summary_markdown_has_counts_and_no_values():
    probes = [
        grader.grade_probe(
            FLIP,
            ProbeRecord(
                FLIP.id, "a", ["2020-05-01", "2020-06-01"], {"values": {"2020-06-01": 100.7}}
            ),
            ROOT,
        )
    ]
    md = grader.summary_markdown(_scores(), probes)
    for heading in (
        "Accuracy and updating",
        "Calibration",
        "reliability bins",
        "Diagnostics",
        "Memorization probe",
    ):
        assert heading in md
    assert "| a | flip | 2 |" in md and "| a | no_change | 2 |" in md
    assert "[0.95, 1]" in md and "[0, 0.5)" in md
    assert "2/2 (100%)" in md  # counts with every percentage
    for pct in re.findall(r"\S+ \(\d+%\)", md):
        assert re.fullmatch(r"\d+/\d+ \(\d+%\)", pct), pct
    for value in ("101.1", "101.5", "100.7", "100.8"):
        assert value not in md
    assert grader.summary_markdown([]) == "No episodes."
