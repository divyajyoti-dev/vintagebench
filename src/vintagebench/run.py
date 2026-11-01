"""CLI entry point (SPEC §4.6, §7).

python -m vintagebench.run --models config/models.yaml --tasks tasks/v1.jsonl
    --trials 3 [--limit N] [--sanity] [--probe] [--project-cost]
-> runs/<timestamp>/results.jsonl (local only; runs/ is gitignored) + summary.md
   (aggregate metrics only: no data values, no model text).

- ``--sanity`` runs only the no-API sanity agents (oracle, always_yes, leaker,
  never_update; with ``--probe`` also first_release_recaller and latest_recaller),
  checks their expected scores (sanity.check_expectations) and exits 4 on a mismatch.
  No network, no keys, models file not read.
- Otherwise the model configs in --models run. Before any paid call the sanity agents
  are run in memory on the same tasks (1 trial); if any expected score is missed the
  run aborts with exit 4 and calls no API.
- ``--probe`` also runs the memorization probe (1 call per task and config, trial 1).
- ``--project-cost`` prints and writes runs/<timestamp>/projection.md: projected cost
  per config of the run described by the other arguments (tasks x trials episodes +
  probe), from measured per-episode / per-probe cost in the response cache (i.e. after
  the smoke test), falling back to PRIOR_* estimates. Calls no API.
- Budget: the cap in config/run.yaml is cumulative over all runs sharing the cache dir
  (ledger <cache>/spend_ledger.json). It is enforced before every uncached call; when
  it would be exceeded the run stops, keeps what finished, and exits 3.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from vintagebench import data, grader, models, sanity
from vintagebench.episode import Agent, EpisodeRecord, ProbeRecord, run_episode, run_probe
from vintagebench.tasks import Task, load_tasks

REPO = Path(__file__).resolve().parents[2]
RUN_CONFIG = REPO / "config" / "run.yaml"
RUNS_DIR = REPO / "runs"
DATA_ROOT: Path = getattr(data, "RAW_DIR", getattr(data, "DATA_DIR", REPO / "data" / "raw"))
LEDGER_NAME = "spend_ledger.json"
EXIT_BUDGET = 3
EXIT_SANITY = 4
# Prior (input, output) token estimates when nothing is cached yet. Episodes: about 4
# calls of ~1-2.5k input; reasoning-on adds reasoning tokens (billed as output).
PRIOR_EPISODE_TOKENS = {False: (6_000, 800), True: (6_000, 4_000)}
PRIOR_PROBE_TOKENS = {False: (300, 100), True: (300, 1_500)}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    p = argparse.ArgumentParser(prog="python -m vintagebench.run", description=__doc__)
    p.add_argument("--models", type=Path, default=REPO / "config" / "models.yaml")
    p.add_argument("--tasks", type=Path, required=True)
    p.add_argument("--trials", type=int, default=None, help="default: trials in run.yaml")
    p.add_argument("--limit", type=int, default=None, help="only the first N tasks")
    p.add_argument("--sanity", action="store_true", help="run only the no-API sanity agents")
    p.add_argument("--probe", action="store_true", help="also run the memorization probe")
    p.add_argument(
        "--project-cost", action="store_true", help="project the run's cost; call no API"
    )
    p.add_argument("--data-root", type=Path, default=DATA_ROOT)
    p.add_argument("--run-config", type=Path, default=RUN_CONFIG)
    p.add_argument("--out-dir", type=Path, default=RUNS_DIR, help="parent of runs/<timestamp>")
    p.add_argument("--cache-dir", type=Path, default=None, help="default: <out-dir>/cache")
    return p.parse_args(argv)


def load_run_config(path: Path) -> dict[str, Any]:
    cfg = yaml.safe_load(Path(path).read_text()) or {}
    return {
        "budget_usd": float(cfg.get("budget_usd", 10)),
        "trials": int(cfg.get("trials", 3)),
        "temperature": float(cfg.get("temperature", 0)),
        "max_tokens": int(cfg.get("max_tokens", 2048)),
        "projection_threshold_usd": float(cfg.get("projection_threshold_usd", 8)),
        "fallback_trials": int(cfg.get("fallback_trials", 2)),
        "fallback_drop": list(cfg.get("fallback_drop") or []),
    }


def _new_run_dir(out_dir: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir, i = out_dir / stamp, 1
    while run_dir.exists():
        run_dir, i = out_dir / f"{stamp}-{i}", i + 1
    run_dir.mkdir(parents=True)
    return run_dir


def _cache_dir(args: argparse.Namespace) -> Path:
    return args.cache_dir or args.out_dir / "cache"


def _share(flags: list[bool]) -> str:
    return f"{sum(flags)}/{len(flags)} ({sum(flags) / len(flags):.0%})" if flags else "n/a"


def task_mix_line(tasks: list[Task]) -> str:
    """Task counts by kind and the Yes share of the golds (counts only)."""
    kinds = Counter(t.kind for t in tasks)
    mix = ", ".join(f"{k} {kinds.get(k, 0)}" for k in grader.KINDS)
    asof = [bool(t.gold_as_of) for t in tasks]
    rev = [bool(t.gold_revised) for t in tasks]
    return (
        f"- tasks by kind: {mix} (total {len(tasks)}); gold_as_of = Yes {_share(asof)}, "
        f"gold_revised = Yes {_share(rev)}"
    )


def _rate(n: int, d: int) -> str:
    return f"{n}/{d} ({n / d:.0%})" if d else "n/a"


def settings_markdown(agents: list[Agent], cfg: dict[str, Any]) -> str:
    """Effective request settings per config."""
    lines = [
        "| Config | Model ID | temperature sent | reasoning_effort | max output tokens "
        "| tool protocol | price in / out (USD per 1M) |",
        "|---|---|---|---|---|---|---|",
    ]
    for a in agents:
        if not isinstance(a, models.ModelSpec):
            lines.append(f"| {a.name} | n/a (no API) | n/a | n/a | n/a | native loop | 0 |")
            continue
        st = models.effective_settings(a, cfg["temperature"])
        temp = f"yes ({st['temperature']:g})" if st["temperature_sent"] else "no (omitted)"
        effort = st["reasoning_effort"] or "not sent"
        proto = "native" if a.native_tools else "plain-text JSON"
        mx = models.effective_max_tokens(a, cfg["max_tokens"])
        lines.append(
            f"| {a.name} | {a.model_id} | {temp} | {effort} | {mx} | {proto} "
            f"| {a.price_in:g} / {a.price_out:g} |"
        )
    return "\n".join(lines)


def episode_diagnostics(rec: EpisodeRecord) -> dict[str, Any]:
    """Tool calls (ok vs error), re-served requests, tokens and cost of one episode."""
    tool_results = [json.loads(m["content"]) for m in rec.transcript if m["role"] == "tool"]
    errors = sum(1 for r in tool_results if isinstance(r, dict) and "error" in r)
    return {
        "tool_calls": len(tool_results),
        "tool_errors": errors,
        "turn1_requests": len(rec.turn1_requests),
        "input_tokens": rec.input_tokens,
        "output_tokens": rec.output_tokens,
        "reasoning_tokens": rec.reasoning_tokens,
        "cost_usd": rec.cost_usd,
    }


def diagnostics_markdown(records: list[EpisodeRecord]) -> str:
    """Per config: tool-call success, tool calls, re-served requests, tokens, cost."""
    lines = [
        "| Config | Episodes | Tool calls returning data | Avg tool calls / episode "
        "| Episodes with no turn-1 request | Avg input tokens / episode | Avg output tokens "
        "/ episode | Avg reasoning tokens / episode | Avg cost / episode (USD) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    by_agent: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        by_agent.setdefault(rec.agent, []).append(episode_diagnostics(rec))
    for agent, ds in by_agent.items():
        n = len(ds)
        calls = sum(d["tool_calls"] for d in ds)
        ok = calls - sum(d["tool_errors"] for d in ds)
        none = sum(d["turn1_requests"] == 0 for d in ds)
        lines.append(
            f"| {agent} | {n} | {_rate(ok, calls)} | {calls / n:.1f} | {_rate(none, n)} "
            f"| {sum(d['input_tokens'] for d in ds) / n:,.0f} "
            f"| {sum(d['output_tokens'] for d in ds) / n:,.0f} "
            f"| {sum(d['reasoning_tokens'] for d in ds) / n:,.0f} "
            f"| {sum(d['cost_usd'] for d in ds) / n:.5f} |"
        )
    return "\n".join(lines)


# --- cost projection -----------------------------------------------------------------


def _per_call_cost(
    spec: models.ModelSpec, usage: list[tuple[int, int, float]], prior: tuple[int, int]
) -> tuple[float, float, str]:
    """(mean cost, max cost, basis) from measured usage, else the prior."""
    if usage:
        costs = [u[2] for u in usage]
        return sum(costs) / len(costs), max(costs), f"measured (n={len(usage)})"
    c = models.cost_usd(spec, *prior)
    return c, c, "prior estimate"


def project_costs(
    specs: list[models.ModelSpec], n_tasks: int, trials: int, cache_dir: Path
) -> list[dict[str, Any]]:
    """Per-config projection: per-episode cost x tasks x trials + per-probe cost x tasks."""
    rows = []
    for spec in specs:
        ep, ep_high, ep_basis = _per_call_cost(
            spec,
            models.cached_episode_usage(spec, cache_dir),
            PRIOR_EPISODE_TOKENS[spec.reasoning_on],
        )
        pr, pr_high, pr_basis = _per_call_cost(
            spec, models.cached_probe_usage(spec, cache_dir), PRIOR_PROBE_TOKENS[spec.reasoning_on]
        )
        episodes = n_tasks * trials
        rows.append(
            {
                "config": spec.name,
                "episode_basis": ep_basis,
                "probe_basis": pr_basis,
                "cost_per_episode": ep,
                "cost_per_probe": pr,
                "episodes": episodes,
                "probes": n_tasks,
                "projected": ep * episodes + pr * n_tasks,
                "projected_high": ep_high * episodes + pr_high * n_tasks,
            }
        )
    return rows


def _projection_table(rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| Config | Episode basis | Cost / episode | Probe basis | Cost / probe "
        "| Episodes | Probes | Projected (mean) | Projected (high = max) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['config']} | {r['episode_basis']} | ${r['cost_per_episode']:.4f} "
            f"| {r['probe_basis']} | ${r['cost_per_probe']:.5f} | {r['episodes']} "
            f"| {r['probes']} | ${r['projected']:.2f} | ${r['projected_high']:.2f} |"
        )
    total = sum(r["projected"] for r in rows)
    high = sum(r["projected_high"] for r in rows)
    lines += ["", f"Total: ${total:.2f} mean, ${high:.2f} high."]
    return lines


def projection_markdown(
    specs: list[models.ModelSpec],
    n_tasks: int,
    trials: int,
    cache_dir: Path,
    cfg: dict[str, Any],
    spent_usd: float,
) -> tuple[str, float]:
    """Projection text (plan per SPEC §7) and the projected mean total of the full plan."""
    rows = project_costs(specs, n_tasks, trials, cache_dir)
    total = sum(r["projected"] for r in rows)
    cap, thr = cfg["budget_usd"], cfg["projection_threshold_usd"]
    lines = [
        "# Projected cost (no API calls made)",
        "",
        f"- plan: {n_tasks} tasks x {trials} trials per config + memorization probe "
        f"({n_tasks} calls per config)",
        f"- budget cap ${cap:.2f} (cumulative); already spent ${spent_usd:.4f}; "
        f"remaining ${cap - spent_usd:.4f}",
        f"- SPEC §7 threshold ${thr:.2f}: projected mean ${total:.2f} is "
        + ("within it." if total <= thr else "ABOVE it; fallback plan below."),
        "- cached episodes rerun for free, so actual new spend can be lower.",
        "",
        "## Full plan",
        "",
        *_projection_table(rows),
    ]
    if total > thr:
        keep = [s for s in specs if s.name not in cfg["fallback_drop"]]
        fb = project_costs(keep, n_tasks, cfg["fallback_trials"], cache_dir)
        dropped = ", ".join(cfg["fallback_drop"]) or "none"
        lines += [
            "",
            f"## Fallback: {cfg['fallback_trials']} trials, dropping {dropped}",
            "",
            *_projection_table(fb),
        ]
    return "\n".join(lines) + "\n", total


# --- running -------------------------------------------------------------------------


def _write_summary(
    path: Path,
    scores: list[grader.Scores],
    probes: list[grader.ProbeScores],
    tasks: list[Task],
    args: argparse.Namespace,
    note: str,
    agents: list[Agent],
    records: list[EpisodeRecord],
    cfg: dict[str, Any],
    sanity_failures: list[str] | None = None,
) -> None:
    lines = [
        "# VintageBench run summary",
        "",
        "Aggregate metrics only (SPEC §2.3); per-episode results stay in results.jsonl.",
        "",
        f"- tasks file: {args.tasks}",
        f"- mode: {'sanity agents' if args.sanity else 'models'}"
        + (" + memorization probe" if args.probe else ""),
        f"- trials: {args.trials}",
        f"- status: {note}",
        task_mix_line(tasks),
    ]
    if sanity_failures is not None:
        verdict = "PASS" if not sanity_failures else f"FAIL ({len(sanity_failures)} checks)"
        lines.append(f"- sanity expectations: {verdict}")
    lines += [
        "",
        grader.summary_markdown(scores, probes),
        "",
        "## Model settings",
        "",
        settings_markdown(agents, cfg),
        "",
        "## Episode diagnostics",
        "",
        diagnostics_markdown(records),
        "",
    ]
    path.write_text("\n".join(lines))


def _model_kwargs(args: argparse.Namespace, cfg: dict[str, Any], budget: models.Budget) -> dict:
    return {
        "cache_dir": _cache_dir(args),
        "budget": budget,
        "temperature": cfg["temperature"],
        "max_tokens": cfg["max_tokens"],
    }


def run_agents(
    agents: list[Agent],
    probe_agents: list[Agent],
    tasks: list[Task],
    trials: int,
    root: Path,
    model_kwargs: dict[str, Any] | None = None,
    out: Any = None,
) -> tuple[list[grader.Scores], list[grader.ProbeScores], list[EpisodeRecord]]:
    """Run episodes for ``agents`` and the probe for ``probe_agents``, grading each.

    Rows are written to ``out`` (results.jsonl) as they finish. BudgetExceeded
    propagates; what finished is in the returned lists only if no exception occurs,
    so callers that need partial results pass ``out``.
    """
    scores: list[grader.Scores] = []
    probes: list[grader.ProbeScores] = []
    records: list[EpisodeRecord] = []

    def emit(row: dict[str, Any]) -> None:
        if out is not None:
            out.write(json.dumps(row, default=str) + "\n")
            out.flush()

    for agent in agents:
        for task in tasks:
            for trial in range(1, trials + 1):
                rec = run_episode(task, agent, trial, root, model_kwargs=model_kwargs)
                s = grader.grade(task, rec, root)
                scores.append(s)
                records.append(rec)
                emit(
                    {
                        "type": "episode",
                        "scores": asdict(s),
                        "diagnostics": episode_diagnostics(rec),
                        "record": asdict(rec),
                    }
                )
    for agent in probe_agents:
        for task in tasks:
            prec: ProbeRecord = run_probe(task, agent, root, model_kwargs=model_kwargs)
            ps = grader.grade_probe(task, prec, root)
            probes.append(ps)
            emit({"type": "probe", "scores": asdict(ps), "record": asdict(prec)})
    return scores, probes, records


def sanity_gate(tasks: list[Task], root: Path, probe: bool) -> list[str]:
    """Run the sanity agents in memory (1 trial) and return expectation failures."""
    probe_agents = list(sanity.PROBE_AGENTS) if probe else []
    scores, probes, _ = run_agents(list(sanity.SANITY_AGENTS), probe_agents, tasks, 1, root)
    return sanity.check_expectations(scores, probes, tasks, root)


class _Collector:
    """File-like sink that keeps graded rows so a budget stop keeps partial results."""

    def __init__(self, fh: Any) -> None:
        self.fh = fh
        self.rows: list[dict[str, Any]] = []

    def write(self, s: str) -> None:
        self.fh.write(s)
        if s.strip():
            self.rows.append(json.loads(s))

    def flush(self) -> None:
        self.fh.flush()


def _rebuild(rows: list[dict[str, Any]]) -> tuple[list, list, list]:
    scores = [grader.Scores(**r["scores"]) for r in rows if r["type"] == "episode"]
    probes = [grader.ProbeScores(**r["scores"]) for r in rows if r["type"] == "probe"]
    records = [EpisodeRecord(**r["record"]) for r in rows if r["type"] == "episode"]
    return scores, probes, records


def run(
    args: argparse.Namespace,
    agents: list[Agent],
    probe_agents: list[Agent],
    tasks: list[Task],
    cfg: dict[str, Any],
) -> tuple[Path, int]:
    """Run all episodes and probes; returns (run dir, exit code)."""
    run_dir = _new_run_dir(args.out_dir)
    budget = models.Budget.from_ledger(cfg["budget_usd"], _cache_dir(args) / LEDGER_NAME)
    start_spent = budget.spent_usd
    note, code = "complete", 0
    with (run_dir / "results.jsonl").open("w") as fh:
        sink = _Collector(fh)
        try:
            run_agents(
                agents,
                probe_agents,
                tasks,
                args.trials,
                args.data_root,
                _model_kwargs(args, cfg, budget),
                sink,
            )
        except models.BudgetExceeded as exc:
            note, code = f"STOPPED at budget cap: {exc}", EXIT_BUDGET
    scores, probes, records = _rebuild(sink.rows)
    failures = None
    if args.sanity:
        failures = sanity.check_expectations(scores, probes, tasks, args.data_root)
        if failures and code == 0:
            code = EXIT_SANITY
    note += (
        f"; spent this run ${budget.spent_usd - start_spent:.4f}; cumulative "
        f"${budget.spent_usd:.4f} of ${budget.limit_usd:.2f}"
    )
    _write_summary(
        run_dir / "summary.md", scores, probes, tasks, args, note, agents + probe_agents,
        records, cfg, failures,
    )  # fmt: skip
    if failures:
        (run_dir / "sanity_failures.txt").write_text("\n".join(failures) + "\n")
    return run_dir, code


def main(argv: Sequence[str] | None = None) -> int:
    """Run the benchmark, enforcing the budget cap in config/run.yaml. Returns exit code."""
    args = parse_args(argv)
    cfg = load_run_config(args.run_config)
    if args.trials is None:
        args.trials = cfg["trials"]
    tasks = load_tasks(args.tasks, args.data_root)
    if args.limit is not None:
        tasks = tasks[: args.limit]
    if args.project_cost:
        if args.sanity:
            print("sanity agents make no API calls: projected cost $0.00")
            return 0
        specs = models.load_model_specs(args.models)
        cache = _cache_dir(args)
        spent = models.Budget.from_ledger(cfg["budget_usd"], cache / LEDGER_NAME).spent_usd
        text, _ = projection_markdown(specs, len(tasks), args.trials, cache, cfg, spent)
        run_dir = _new_run_dir(args.out_dir)
        (run_dir / "projection.md").write_text(text)
        print(text)
        print(f"wrote {run_dir / 'projection.md'}")
        return 0
    if args.sanity:
        agents: list[Agent] = list(sanity.SANITY_AGENTS)
        probe_agents: list[Agent] = list(sanity.PROBE_AGENTS) if args.probe else []
    else:
        agents = list(models.load_model_specs(args.models))
        if not agents:
            print(f"no models in {args.models}")
            return 2
        probe_agents = list(agents) if args.probe else []
        failures = sanity_gate(tasks, args.data_root, args.probe)
        if failures:
            print(f"sanity agents missed {len(failures)} expected scores; no API called:")
            print("\n".join(failures[:20]))
            return EXIT_SANITY
    run_dir, code = run(args, agents, probe_agents, tasks, cfg)
    print(f"wrote {run_dir / 'results.jsonl'} and {run_dir / 'summary.md'}")
    print((run_dir / "summary.md").read_text())
    return code


if __name__ == "__main__":
    raise SystemExit(main())
