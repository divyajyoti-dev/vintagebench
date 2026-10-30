"""CLI entry point (SPEC §4).

python -m vintagebench.run --models config/models.yaml --tasks tasks/pilot.jsonl
    --trials 3 [--limit N] [--sanity]
-> runs/<timestamp>/results.jsonl + summary.md

``--sanity`` runs only the four sanity agents (no network, no keys, models file not
read). Otherwise only the models in --models are run, with the budget cap from
config/run.yaml enforced before every uncached call; when the cap would be exceeded the
run stops, keeps the episodes finished so far, and exits with code 3.

``--estimate`` prints the projected cost of the run described by the other arguments
and exits without calling any API or writing a run directory. It uses measured
per-episode tokens from the response cache when that model has cached episodes
(e.g. after the smoke test), otherwise DEFAULT_EPISODE_TOKENS.

summary.md also has a "Model settings" section (temperature actually sent,
reasoning_effort, max output tokens, tool protocol) and a "Diagnostics" section (JSON
parse rate per turn, tool-call success, tool calls, tokens and cost per episode).
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from vintagebench import data, grader, models, sanity
from vintagebench.episode import Agent, EpisodeRecord, run_episode
from vintagebench.tasks import Task, load_tasks

REPO = Path(__file__).resolve().parents[2]
RUN_CONFIG = REPO / "config" / "run.yaml"
RUNS_DIR = REPO / "runs"
EXIT_BUDGET = 3
# Prior per-episode (input, output) token estimates from the episode.py prompts with
# reasoning off: typical = 4 calls (~410/1060/1290/1940 input, ~500 output in all);
# high = 6 calls with ~1k output each.
DEFAULT_EPISODE_TOKENS = {"typical": (5_000, 500), "high": (12_000, 6_000)}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    p = argparse.ArgumentParser(prog="python -m vintagebench.run", description=__doc__)
    p.add_argument("--models", type=Path, default=REPO / "config" / "models.yaml")
    p.add_argument("--tasks", type=Path, required=True)
    p.add_argument("--trials", type=int, default=None, help="default: trials in run.yaml")
    p.add_argument("--limit", type=int, default=None, help="only the first N tasks")
    p.add_argument("--sanity", action="store_true", help="run only the no-API sanity agents")
    p.add_argument("--data-root", type=Path, default=data.DATA_DIR)
    p.add_argument("--run-config", type=Path, default=RUN_CONFIG)
    p.add_argument("--out-dir", type=Path, default=RUNS_DIR, help="parent of runs/<timestamp>")
    p.add_argument("--cache-dir", type=Path, default=None, help="default: <out-dir>/cache")
    p.add_argument("--estimate", action="store_true", help="print the projected cost; call no API")
    return p.parse_args(argv)


def load_run_config(path: Path) -> dict[str, Any]:
    cfg = yaml.safe_load(Path(path).read_text()) or {}
    return {
        "budget_usd": float(cfg.get("budget_usd", 10)),
        "trials": int(cfg.get("trials", 3)),
        "temperature": float(cfg.get("temperature", 0)),
        "max_tokens": int(cfg.get("max_tokens", 2048)),
    }


def _new_run_dir(out_dir: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir, i = out_dir / stamp, 1
    while run_dir.exists():
        run_dir, i = out_dir / f"{stamp}-{i}", i + 1
    run_dir.mkdir(parents=True)
    return run_dir


def _share(flags: list[bool]) -> str:
    return f"{sum(flags)}/{len(flags)} ({sum(flags) / len(flags):.0%})"


def yes_share_line(tasks: list[Task]) -> str:
    """Share of yes/no tasks whose gold is Yes, as of and revised, plus the
    majority-class baseline (always giving the more common as-of / revised answer)."""
    yn = [t for t in tasks if t.answer_type == "yes_no"]
    if not yn:
        return "- yes share: no yes/no tasks"
    asof = [bool(t.gold_as_of) for t in yn]
    rev = [bool(t.gold_revised) for t in yn]
    base_asof = asof if sum(asof) * 2 >= len(asof) else [not x for x in asof]
    base_rev = rev if sum(rev) * 2 >= len(rev) else [not x for x in rev]
    return (
        f"- yes share ({len(yn)} yes/no tasks): gold_as_of = Yes {_share(asof)}, "
        f"gold_revised = Yes {_share(rev)}; majority-class baseline: "
        f"asof_correct {_share(base_asof)}, revised_correct {_share(base_rev)}"
    )


def _rate(n: int, d: int) -> str:
    return f"{n}/{d} ({n / d:.0%})" if d else "n/a"


def settings_markdown(agents: list[Agent], cfg: dict[str, Any]) -> str:
    """Effective request settings per agent."""
    lines = [
        "| Agent | temperature sent | reasoning_effort | max output tokens | tool protocol |",
        "|---|---|---|---|---|",
    ]
    for a in agents:
        if not isinstance(a, models.ModelSpec):
            lines.append(f"| {a.name} | n/a (no API) | n/a | n/a | native loop |")
            continue
        st = models.effective_settings(a, cfg["temperature"])
        temp = f"yes ({st['temperature']:g})" if st["temperature_sent"] else "no (omitted)"
        effort = st["reasoning_effort"] or "not sent"
        proto = "native" if a.native_tools else "plain-text JSON"
        lines.append(f"| {a.name} | {temp} | {effort} | {cfg['max_tokens']} | {proto} |")
    return "\n".join(lines)


def episode_diagnostics(rec: EpisodeRecord) -> dict[str, Any]:
    """Parse success per turn, tool calls (ok vs error), tokens and cost of one episode."""
    tool_results = [json.loads(m["content"]) for m in rec.transcript if m["role"] == "tool"]
    errors = sum(1 for r in tool_results if isinstance(r, dict) and "error" in r)
    return {
        "turn1_parsed": "_error" not in rec.turn1,
        "turn2_parsed": "_error" not in rec.turn2,
        "tool_calls": len(tool_results),
        "tool_errors": errors,
        "input_tokens": rec.input_tokens,
        "output_tokens": rec.output_tokens,
        "cost_usd": rec.cost_usd,
    }


def diagnostics_markdown(records: list[EpisodeRecord]) -> str:
    """Per-agent JSON parse rate per turn, tool-call success, tool calls, tokens, cost."""
    lines = [
        "| Agent | Episodes | Turn-1 JSON parsed | Turn-2 JSON parsed | Tool calls returning "
        "data | Avg tool calls / episode | Avg input tokens / episode | Avg output tokens "
        "/ episode | Avg cost / episode (USD) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    by_agent: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        by_agent.setdefault(rec.agent, []).append(episode_diagnostics(rec))
    for agent, ds in by_agent.items():
        n = len(ds)
        calls = sum(d["tool_calls"] for d in ds)
        ok = calls - sum(d["tool_errors"] for d in ds)
        lines.append(
            f"| {agent} | {n} | {_rate(sum(d['turn1_parsed'] for d in ds), n)} "
            f"| {_rate(sum(d['turn2_parsed'] for d in ds), n)} | {_rate(ok, calls)} "
            f"| {calls / n:.1f} | {sum(d['input_tokens'] for d in ds) / n:,.0f} "
            f"| {sum(d['output_tokens'] for d in ds) / n:,.0f} "
            f"| {sum(d['cost_usd'] for d in ds) / n:.5f} |"
        )
    return "\n".join(lines)


def estimate_markdown(
    specs: list[models.ModelSpec], episodes: int, cache_dir: Path, budget_usd: float
) -> tuple[str, float]:
    """Projected cost table for ``episodes`` episodes per model; returns (text, typical total).

    Measured basis: mean (typical) and max (high) per-episode tokens from the cache.
    Prior basis: DEFAULT_EPISODE_TOKENS. Costs use the spec's current prices.
    """
    lines = [
        f"Projected cost: {episodes} episodes per model (no API calls made).",
        "",
        "| Model | Basis | Tokens / episode in, out (typical) | Cost / episode (typical) "
        "| Projected (typical) | Projected (high) |",
        "|---|---|---|---|---|---|",
    ]
    total = total_high = 0.0
    for spec in specs:
        usage = models.cached_episode_usage(spec, cache_dir)
        if usage:
            n = len(usage)
            typ = (sum(u[0] for u in usage) / n, sum(u[1] for u in usage) / n)
            high = max(usage, key=lambda u: models.cost_usd(spec, u[0], u[1]))
            basis = f"measured ({n} cached episode{'s' if n > 1 else ''}; high = max)"
        else:
            typ, high = DEFAULT_EPISODE_TOKENS["typical"], DEFAULT_EPISODE_TOKENS["high"]
            basis = "prior estimate"
        per_ep = models.cost_usd(spec, typ[0], typ[1])
        proj, proj_high = per_ep * episodes, models.cost_usd(spec, *high) * episodes
        total, total_high = total + proj, total_high + proj_high
        lines.append(
            f"| {spec.name} | {basis} | {typ[0]:,.0f}, {typ[1]:,.0f} | ${per_ep:.4f} "
            f"| ${proj:.2f} | ${proj_high:.2f} |"
        )
    verdict = "within" if total_high <= budget_usd else "the high case EXCEEDS"
    lines += [
        "",
        f"Total: ${total:.2f} typical, ${total_high:.2f} high; budget cap ${budget_usd:.2f} "
        f"({verdict} the cap; the run stops before exceeding it). Episodes already in the "
        "cache rerun for free, so actual new spend can be lower.",
    ]
    return "\n".join(lines), total


def _write_summary(
    path: Path,
    scores: list[grader.Scores],
    tasks: list[Task],
    args: argparse.Namespace,
    note: str,
    agents: list[Agent],
    records: list[EpisodeRecord],
    cfg: dict[str, Any],
) -> None:
    lines = [
        "# VintageBench run summary",
        "",
        f"- tasks: {args.tasks}",
        f"- mode: {'sanity agents' if args.sanity else 'models'}",
        f"- status: {note}",
        yes_share_line(tasks),
        "",
        grader.summary_markdown(scores),
        "",
        "## Model settings",
        "",
        settings_markdown(agents, cfg),
        "",
        "## Diagnostics",
        "",
        diagnostics_markdown(records),
        "",
    ]
    path.write_text("\n".join(lines))


def run(
    args: argparse.Namespace, agents: list[Agent], tasks: list[Task], cfg: dict[str, Any]
) -> tuple[Path, int]:
    """Run all (agent, task, trial) episodes; returns (run dir, exit code)."""
    run_dir = _new_run_dir(args.out_dir)
    budget = models.Budget(cfg["budget_usd"])
    model_kwargs = {
        "cache_dir": args.cache_dir or args.out_dir / "cache",
        "budget": budget,
        "temperature": cfg["temperature"],
        "max_tokens": cfg["max_tokens"],
    }
    scores: list[grader.Scores] = []
    records: list[EpisodeRecord] = []
    note, code = "complete", 0
    with (run_dir / "results.jsonl").open("w") as out:
        try:
            for agent in agents:
                for task in tasks:
                    for trial in range(1, args.trials + 1):
                        rec = run_episode(
                            task, agent, trial, args.data_root, model_kwargs=model_kwargs
                        )
                        s = grader.grade(task, rec, args.data_root)
                        scores.append(s)
                        records.append(rec)
                        row = {
                            "scores": asdict(s),
                            "diagnostics": episode_diagnostics(rec),
                            "record": asdict(rec),
                        }
                        out.write(json.dumps(row) + "\n")
                        out.flush()
        except models.BudgetExceeded as exc:
            note, code = f"STOPPED at budget cap: {exc}", EXIT_BUDGET
    note += f"; spent this run ${budget.spent_usd:.4f} of ${budget.limit_usd:.2f}"
    _write_summary(run_dir / "summary.md", scores, tasks, args, note, agents, records, cfg)
    return run_dir, code


def main(argv: Sequence[str] | None = None) -> int:
    """Run the benchmark, enforcing the budget cap in config/run.yaml. Returns exit code."""
    args = parse_args(argv)
    cfg = load_run_config(args.run_config)
    if args.trials is None:
        args.trials = cfg["trials"]
    tasks = load_tasks(args.tasks)
    if args.limit is not None:
        tasks = tasks[: args.limit]
    if args.estimate:
        if args.sanity:
            print("sanity agents make no API calls: projected cost $0.00")
            return 0
        specs = models.load_model_specs(args.models)
        episodes = len(tasks) * args.trials
        cache_dir = args.cache_dir or args.out_dir / "cache"
        text, _ = estimate_markdown(specs, episodes, cache_dir, cfg["budget_usd"])
        print(text)
        return 0
    if args.sanity:
        agents: list[Agent] = list(sanity.SANITY_AGENTS)
    else:
        agents = list(models.load_model_specs(args.models))
        if not agents:
            print(f"no models in {args.models}")
            return 2
    run_dir, code = run(args, agents, tasks, cfg)
    print(f"wrote {run_dir / 'results.jsonl'} and {run_dir / 'summary.md'}")
    print((run_dir / "summary.md").read_text())
    return code


if __name__ == "__main__":
    raise SystemExit(main())
