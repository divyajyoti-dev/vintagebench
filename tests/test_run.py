"""CLI end to end on fixtures; output goes to tmp_path. No network."""

import json
from pathlib import Path

import pytest
from test_models import FakeClient, completion, native_call

from vintagebench import models, run
from vintagebench.tasks import Task

FIXTURES = Path(__file__).parent / "fixtures"
REPO = Path(__file__).parents[1]


def cli(tmp_path, *extra):
    return [
        "--models", str(REPO / "config" / "models.yaml"),
        "--tasks", str(FIXTURES / "tasks.jsonl"),
        "--data-root", str(FIXTURES / "vintages"),
        "--out-dir", str(tmp_path / "runs"),
        *extra,
    ]  # fmt: skip


def only_run_dir(tmp_path):
    dirs = [d for d in (tmp_path / "runs").iterdir() if d.name != "cache"]
    assert len(dirs) == 1
    return dirs[0]


def test_parse_args_defaults():
    a = run.parse_args(["--tasks", "t.jsonl"])
    assert a.trials is None and a.limit is None and not a.sanity
    assert a.data_root == run.data.DATA_DIR
    a = run.parse_args(["--models", "m.yaml", "--tasks", "t.jsonl", "--trials", "3",
                        "--limit", "1", "--sanity"])  # fmt: skip
    assert (a.trials, a.limit, a.sanity, a.models) == (3, 1, True, Path("m.yaml"))


def test_run_config_loads():
    cfg = run.load_run_config(REPO / "config" / "run.yaml")
    assert cfg["budget_usd"] == 10 and cfg["trials"] == 3 and cfg["temperature"] == 0


def test_sanity_run_writes_results_and_summary(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network")

    monkeypatch.setattr(models, "make_client", boom)
    monkeypatch.setattr(models, "complete", boom)
    assert run.main(cli(tmp_path, "--trials", "2", "--sanity")) == 0
    d = only_run_dir(tmp_path)
    rows = [json.loads(line) for line in (d / "results.jsonl").read_text().splitlines()]
    assert len(rows) == 4 * 3 * 2
    assert {r["record"]["agent"] for r in rows} == {
        "oracle",
        "always_yes",
        "leaker",
        "never_update",
    }
    summary = (d / "summary.md").read_text()
    assert "| oracle | 6 | 6/6 (100%) | 6/6 (100%) | 2/2 (100%) | 4/4 (100%) | 0/6 (0%)" in summary
    assert "| leaker |" in summary and "status: complete" in summary


def test_limit_and_default_trials(tmp_path):
    cfg = tmp_path / "run.yaml"
    cfg.write_text("budget_usd: 1\ntrials: 1\ntemperature: 0\n")
    assert run.main(cli(tmp_path, "--sanity", "--limit", "1", "--run-config", str(cfg))) == 0
    rows = (only_run_dir(tmp_path) / "results.jsonl").read_text().splitlines()
    assert len(rows) == 4  # 4 agents x 1 task x 1 trial


def test_no_models_configured(tmp_path):
    empty = tmp_path / "models.yaml"
    empty.write_text("[]\n")
    assert run.main(cli(tmp_path) + ["--models", str(empty)]) == 2


def test_model_run_stops_at_budget_cap(tmp_path, monkeypatch):
    mfile = tmp_path / "models.yaml"
    mfile.write_text(
        "- {provider: openai, model_id: fake, price_in: 1000, price_out: 1000, "
        "native_tools: true}\n"
    )
    cfg = tmp_path / "run.yaml"
    cfg.write_text("budget_usd: 5\ntrials: 1\ntemperature: 0\nmax_tokens: 100\n")
    answer = json.dumps({"answer": "no", "confidence": 0.5, "values_used": {}, "caveats": ""})
    client = FakeClient(*[completion(text=answer, tin=1000, tout=100) for _ in range(50)])
    monkeypatch.setattr(models, "make_client", lambda provider: client)
    code = run.main(cli(tmp_path, "--models", str(mfile), "--run-config", str(cfg)))
    assert code == run.EXIT_BUDGET
    # each call costs (1000 + 100) * 1000 / 1e6 = 1.1; 4 calls fit under $5, not a 5th
    assert len(client.requests) == 4
    d = only_run_dir(tmp_path)
    assert len((d / "results.jsonl").read_text().splitlines()) == 2  # 2 episodes finished
    summary = (d / "summary.md").read_text()
    assert "STOPPED at budget cap" in summary and "$4.4000 of $5.00" in summary
    assert (tmp_path / "runs" / "cache").exists()


@pytest.mark.parametrize("flag", [[], ["--sanity"]])
def test_cli_rejects_missing_tasks(flag):
    with pytest.raises(SystemExit):
        run.parse_args(flag)


def _task(i, asof, rev, answer_type="yes_no"):
    return Task(f"t{i}", "TOY", "2021-01-15", "q?", answer_type, asof, "2021-02-15", rev,
                asof != rev)  # fmt: skip


def test_yes_share_line():
    tasks = [_task(1, False, True), _task(2, True, True), _task(3, 0.4, 0.4, "number")]
    assert run.yes_share_line(tasks) == (
        "- yes share (2 yes/no tasks): gold_as_of = Yes 1/2 (50%), gold_revised = Yes "
        "2/2 (100%); majority-class baseline: asof_correct 1/2 (50%), revised_correct "
        "2/2 (100%)"
    )
    skewed = [_task(i, i == 0, i < 3) for i in range(4)]  # as-of 1/4 yes, revised 3/4 yes
    line = run.yes_share_line(skewed)
    assert "gold_as_of = Yes 1/4 (25%)" in line and "asof_correct 3/4 (75%)" in line
    assert "revised_correct 3/4 (75%)" in line
    assert run.yes_share_line([_task(1, 0.4, 0.4, "number")]) == "- yes share: no yes/no tasks"


def test_summary_has_yes_share(tmp_path):
    assert run.main(cli(tmp_path, "--trials", "1", "--sanity")) == 0
    summary = (only_run_dir(tmp_path) / "summary.md").read_text()
    assert "- yes share (2 yes/no tasks): gold_as_of = Yes 1/2 (50%)" in summary


# --- --estimate, settings and diagnostics --------------------------------------------


def _boom(*a, **k):
    raise AssertionError("network")


def test_estimate_prior_makes_no_calls_and_writes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(models, "make_client", _boom)
    monkeypatch.setattr(models, "complete", _boom)
    assert run.main(cli(tmp_path, "--trials", "3", "--estimate")) == 0
    out = capsys.readouterr().out
    assert "Projected cost: 9 episodes per model" in out
    assert "| openai/gpt-6-sol | prior estimate | 5,000, 500 | $0.0150 | $0.14 | $0.76 |" in out
    assert not (tmp_path / "runs").exists()
    assert run.main(cli(tmp_path, "--estimate", "--sanity")) == 0
    assert "$0.00" in capsys.readouterr().out


def test_estimate_uses_measured_cache(tmp_path):
    spec = models.ModelSpec("openai", "m", 2.0, 10.0, True, "none")
    for turn, (tin, tout) in [(1, (1000, 100)), (2, (3000, 300))]:
        models.complete(
            spec, [{"role": "user", "content": "q"}], [], task_id="t", turn=turn, trial=1,
            client=FakeClient(completion(text="a", tin=tin, tout=tout)), cache_dir=tmp_path,
        )  # fmt: skip
    text, total = run.estimate_markdown([spec], 60, tmp_path, budget_usd=10)
    per_ep = (4000 * 2 + 400 * 10) / 1e6
    assert "measured (1 cached episode; high = max)" in text and "4,000, 400" in text
    assert total == pytest.approx(per_ep * 60)
    assert "within the cap" in text
    _, big = run.estimate_markdown([spec], 100_000, tmp_path, budget_usd=10)
    assert "EXCEEDS" in run.estimate_markdown([spec], 100_000, tmp_path, 10)[0] and big > 10


def _model_files(tmp_path):
    mfile = tmp_path / "models.yaml"
    mfile.write_text(
        "- {provider: openai, model_id: fake, price_in: 1, price_out: 2, native_tools: true, "
        "reasoning_effort: none}\n"
    )
    cfg = tmp_path / "run.yaml"
    cfg.write_text("budget_usd: 5\ntrials: 1\ntemperature: 0\nmax_tokens: 100\n")
    return mfile, cfg


def test_model_run_summary_settings_and_diagnostics(tmp_path, monkeypatch):
    mfile, cfg = _model_files(tmp_path)
    t1 = json.dumps({"answer": "no", "confidence": 0.9, "values_used": {}, "caveats": ""})
    good, bad = (native_call("get_series", {"series_id": s}) for s in ("TOY", "NOPE"))
    client = FakeClient(
        completion(tool_calls=[good], tin=500, tout=50),
        completion(text=t1, tin=1000, tout=100),
        completion(tool_calls=[bad], tin=1500, tout=50),
        completion(text="I am not sure.", tin=2000, tout=100),
    )
    monkeypatch.setattr(models, "make_client", lambda provider: client)
    args = cli(tmp_path, "--models", str(mfile), "--run-config", str(cfg), "--limit", "1")
    assert run.main(args) == 0
    assert all(r["temperature"] == 0 and r["reasoning_effort"] == "none" for r in client.requests)
    d = only_run_dir(tmp_path)
    summary = (d / "summary.md").read_text()
    assert "| openai/fake | yes (0) | none | 100 | native |" in summary
    assert (
        "| openai/fake | 1 | 1/1 (100%) | 0/1 (0%) | 1/2 (50%) | 2.0 | 5,000 | 300 | 0.00560 |"
        in summary
    )
    row = json.loads((d / "results.jsonl").read_text().splitlines()[0])
    assert row["diagnostics"] == {
        "turn1_parsed": True, "turn2_parsed": False, "tool_calls": 2, "tool_errors": 1,
        "input_tokens": 5000, "output_tokens": 300, "cost_usd": pytest.approx(0.0056),
    }  # fmt: skip


def test_sanity_summary_diagnostics(tmp_path):
    assert run.main(cli(tmp_path, "--trials", "1", "--sanity")) == 0
    summary = (only_run_dir(tmp_path) / "summary.md").read_text()
    assert "## Model settings" in summary and "| oracle | n/a (no API) |" in summary
    assert (
        "| oracle | 3 | 3/3 (100%) | 3/3 (100%) | 6/6 (100%) | 2.0 | 0 | 0 | 0.00000 |" in summary
    )
    assert "| always_yes | 3 | 3/3 (100%) | 3/3 (100%) | n/a | 0.0 |" in summary
