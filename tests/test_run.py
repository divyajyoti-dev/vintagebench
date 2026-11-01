"""CLI end to end on synthetic data and fake clients; output goes to tmp_path. No network."""

import json
from pathlib import Path

import pytest
from harness_fakes import TASKS, install
from test_models import completion

from vintagebench import models, run, sanity

REPO = Path(__file__).parents[1]
T1 = {
    "calculation": "June vs May; therefore, no.",
    "answer": "no",
    "confidence": 0.9,
    "survival_prob": 0.8,
    "values_used": {"2020-05-01": 101.1, "2020-06-01": 101.5},
    "caveats": "",
}
T2 = {**T1, "changed": False, "reason": ""}
del T2["survival_prob"], T2["caveats"]


@pytest.fixture(autouse=True)
def fake_data(monkeypatch):
    install(monkeypatch)
    monkeypatch.setattr(run, "load_tasks", lambda path, root: list(TASKS))


def _boom(*a, **k):
    raise AssertionError("network")


@pytest.fixture
def no_network(monkeypatch):
    monkeypatch.setattr(models, "make_client", _boom)
    monkeypatch.setattr(models, "complete", _boom)


class Responder:
    """Fake OpenAI client answering by conversation state (text tool protocol)."""

    def __init__(self, tin=1000, tout=100):
        self.requests, self.tin, self.tout = [], tin, tout
        self.chat = type("C", (), {"completions": type("X", (), {"create": self.create})()})()

    def create(self, **kw):
        self.requests.append(kw)
        msgs = kw["messages"]
        last = msgs[-1]["content"]
        if "Today is" not in msgs[0]["content"]:  # probe
            text = json.dumps({"values": {"2020-05-01": 101.1}})
        elif last.startswith("Question:"):
            text = json.dumps({"tool": "get_series", "arguments": {"series_id": "TOY"}})
        elif last.startswith("Tool result"):
            text = json.dumps(T1)
        else:
            text = json.dumps(T2)
        return completion(text=text, tin=self.tin, tout=self.tout)


def write_models(tmp_path, price=1.0):
    p = tmp_path / "models.yaml"
    p.write_text(
        f"- {{name: fake/off, provider: openai, model_id: fake, price_in: {price}, "
        f"price_out: {price}, native_tools: false, reasoning_effort: none}}\n"
        f"- {{name: fake/low, provider: openai, model_id: fake, price_in: {price}, "
        f"price_out: {price}, native_tools: false, reasoning_effort: low, max_tokens: 500}}\n"
    )
    return p


def write_cfg(tmp_path, budget=5, trials=1):
    p = tmp_path / "run.yaml"
    p.write_text(
        f"budget_usd: {budget}\ntrials: {trials}\ntemperature: 0\nmax_tokens: 100\n"
        "projection_threshold_usd: 8\nfallback_trials: 2\nfallback_drop: [fake/low]\n"
    )
    return p


def cli(tmp_path, *extra):
    return [
        "--models", str(write_models(tmp_path)),
        "--tasks", str(tmp_path / "tasks.jsonl"),
        "--run-config", str(write_cfg(tmp_path)),
        "--data-root", str(tmp_path / "raw"),
        "--out-dir", str(tmp_path / "runs"),
        *extra,
    ]  # fmt: skip


def run_dirs(tmp_path):
    return sorted(d for d in (tmp_path / "runs").iterdir() if d.name != "cache")


def rows(d):
    return [json.loads(line) for line in (d / "results.jsonl").read_text().splitlines()]


def test_parse_args_defaults():
    a = run.parse_args(["--tasks", "t.jsonl"])
    assert a.trials is None and a.limit is None and not (a.sanity or a.probe or a.project_cost)
    a = run.parse_args(["--tasks", "t", "--trials", "3", "--limit", "1", "--sanity", "--probe",
                        "--project-cost"])  # fmt: skip
    assert (a.trials, a.limit, a.sanity, a.probe, a.project_cost) == (3, 1, True, True, True)
    with pytest.raises(SystemExit):
        run.parse_args([])


def test_repo_run_config():
    cfg = run.load_run_config(REPO / "config" / "run.yaml")
    assert cfg["budget_usd"] == 10 and cfg["trials"] == 3 and cfg["temperature"] == 0
    assert cfg["projection_threshold_usd"] == 8 and cfg["fallback_trials"] == 2
    names = [s.name for s in models.load_model_specs(REPO / "config" / "models.yaml")]
    assert set(cfg["fallback_drop"]) <= set(names)


def test_sanity_run_with_probe(tmp_path, no_network):
    assert run.main(cli(tmp_path, "--sanity", "--probe", "--trials", "2")) == 0
    (d,) = run_dirs(tmp_path)
    rs = rows(d)
    assert sum(r["type"] == "episode" for r in rs) == 4 * 3 * 2
    assert sum(r["type"] == "probe" for r in rs) == 2 * 3
    summary = (d / "summary.md").read_text()
    assert "sanity expectations: PASS" in summary and "status: complete" in summary
    assert "| oracle | 6 | 6/6 (100%) | 6/6 (100%) | 6/6 (100%) | 2/2 (100%)" in summary
    assert "| first_release_recaller | 3 |" in summary
    assert "tasks by kind: flip 1, control 1, no_change 1 (total 3)" in summary
    for value in ("101.1", "101.5", "100.8", "100.7"):
        assert value not in summary


def test_sanity_failure_exit_code(tmp_path, no_network, monkeypatch):
    monkeypatch.setattr(sanity, "check_expectations", lambda *a: ["oracle broke"])
    assert run.main(cli(tmp_path, "--sanity", "--trials", "1")) == run.EXIT_SANITY
    (d,) = run_dirs(tmp_path)
    assert "FAIL (1 checks)" in (d / "summary.md").read_text()
    assert (d / "sanity_failures.txt").read_text() == "oracle broke\n"


def test_model_run_blocked_by_sanity_gate(tmp_path, monkeypatch):
    client = Responder()
    monkeypatch.setattr(models, "make_client", lambda provider: client)
    monkeypatch.setattr(sanity, "check_expectations", lambda *a: ["oracle broke"])
    assert run.main(cli(tmp_path)) == run.EXIT_SANITY
    assert client.requests == [] and not (tmp_path / "runs").exists()


def test_no_models_configured(tmp_path):
    empty = tmp_path / "empty.yaml"
    empty.write_text("[]\n")
    assert run.main(cli(tmp_path) + ["--models", str(empty)]) == 2


def test_model_run_with_probe(tmp_path, monkeypatch):
    client = Responder()
    monkeypatch.setattr(models, "make_client", lambda provider: client)
    assert run.main(cli(tmp_path, "--probe", "--limit", "1")) == 0
    off = [r for r in client.requests if r["reasoning_effort"] == "none"]
    low = [r for r in client.requests if r["reasoning_effort"] == "low"]
    assert all(r["temperature"] == 0 and r["max_completion_tokens"] == 100 for r in off)
    assert all("temperature" not in r and r["max_completion_tokens"] == 500 for r in low)
    assert all("tools" not in r for r in client.requests)
    assert len(off) == len(low) == 4  # tool call, turn-1 answer, turn-2 answer, probe
    (d,) = run_dirs(tmp_path)
    rs = rows(d)
    assert [(r["type"], r["scores"]["agent"]) for r in rs] == [
        ("episode", "fake/off"), ("episode", "fake/low"), ("probe", "fake/off"),
        ("probe", "fake/low"),
    ]  # fmt: skip
    ep = rs[0]["scores"]
    assert ep["asof_correct"] and not ep["revised_correct"] and not ep["update_correct"]
    assert ep["changed"] is False and ep["self_report_agrees"] is True
    summary = (d / "summary.md").read_text()
    assert "| fake/low | fake | no (omitted) | low | 500 | plain-text JSON | 1 / 1 |" in summary
    assert "| fake/off | 1 | 1/1 (100%) | 0/1 (0%) | 0/1 (0%) | 0/1 (0%) | n/a | n/a" in summary
    assert "## Memorization probe" in summary
    for value in ("101.1", "101.5", "100.8"):
        assert value not in summary
    # rerun is free: everything cached
    again = Responder()
    monkeypatch.setattr(models, "make_client", lambda provider: again)
    assert run.main(cli(tmp_path, "--probe", "--limit", "1")) == 0
    assert again.requests == []


def test_budget_cap_is_cumulative_across_runs(tmp_path, monkeypatch):
    client = Responder(tin=1000, tout=100)
    monkeypatch.setattr(models, "make_client", lambda provider: client)
    mfile = tmp_path / "m.yaml"
    mfile.write_text(
        "- {name: pricey, provider: openai, model_id: fake, price_in: 1000, price_out: 1000, "
        "native_tools: false, reasoning_effort: none}\n"
    )
    args = cli(tmp_path, "--limit", "1") + ["--models", str(mfile)]
    # each call costs (1000 + 100) * 1000 / 1e6 = 1.1, budget 5: 3 calls = 1 episode
    assert run.main(args) == 0
    assert len(client.requests) == 3
    ledger = json.loads((tmp_path / "runs" / "cache" / run.LEDGER_NAME).read_text())
    assert ledger["spent_usd"] == pytest.approx(3.3)
    args2 = cli(tmp_path, "--limit", "2") + ["--models", str(mfile)]
    assert run.main(args2) == run.EXIT_BUDGET  # task 1 cached; 1 more call fits, not 2
    assert len(client.requests) == 4
    d = run_dirs(tmp_path)[-1]
    assert sum(r["type"] == "episode" for r in rows(d)) == 1
    summary = (d / "summary.md").read_text()
    assert "STOPPED at budget cap" in summary and "cumulative $4.4000 of $5.00" in summary


def test_project_cost_from_smoke_cache(tmp_path, monkeypatch, capsys):
    client = Responder(tin=1000, tout=100)
    monkeypatch.setattr(models, "make_client", lambda provider: client)
    assert run.main(cli(tmp_path, "--probe", "--limit", "1", "--trials", "1")) == 0  # smoke
    monkeypatch.setattr(models, "make_client", _boom)
    monkeypatch.setattr(models, "complete", _boom)
    assert run.main(cli(tmp_path, "--project-cost", "--trials", "3")) == 0
    out = capsys.readouterr().out
    per_ep, per_probe = 3 * 1100 / 1e6, 1100 / 1e6
    assert f"${per_ep:.4f}" in out and "measured (n=1)" in out
    assert "| 9 | 3 |" in out  # 3 tasks x 3 trials, 3 probes
    total = 2 * (per_ep * 9 + per_probe * 3)
    assert f"Total: ${total:.2f} mean" in out and "within it" in out
    proj = run_dirs(tmp_path)[-1] / "projection.md"
    assert proj.read_text().startswith("# Projected cost (no API calls made)")


def test_projection_fallback_when_over_threshold(tmp_path):
    specs = models.load_model_specs(write_models(tmp_path, price=1000))
    cfg = run.load_run_config(write_cfg(tmp_path))
    text, total = run.projection_markdown(specs, 45, 3, tmp_path / "cache", cfg, 1.5)
    assert total > 8 and "ABOVE it" in text and "prior estimate" in text
    assert "## Fallback: 2 trials, dropping fake/low" in text
    fallback = text.split("## Fallback")[1]
    assert "fake/off" in fallback and "fake/low |" not in fallback
    assert "already spent $1.5000; remaining $3.5000" in text
