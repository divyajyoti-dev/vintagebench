"""CLI end to end on fixtures; output goes to tmp_path. No network."""

import json
from pathlib import Path

import pytest
from test_models import FakeClient, completion

from vintagebench import models, run

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
