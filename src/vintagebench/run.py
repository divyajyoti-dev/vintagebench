"""CLI entry point (SPEC §4).

python -m vintagebench.run --models config/models.yaml --tasks tasks/pilot.jsonl
    --trials 3 [--limit N] [--sanity]
-> runs/<timestamp>/results.jsonl + summary.md

``--sanity`` runs only the four sanity agents (no network, no keys, models file not
read). Otherwise only the models in --models are run, with the budget cap from
config/run.yaml enforced before every uncached call; when the cap would be exceeded the
run stops, keeps the episodes finished so far, and exits with code 3.
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
from vintagebench.episode import Agent, run_episode
from vintagebench.tasks import Task, load_tasks

REPO = Path(__file__).resolve().parents[2]
RUN_CONFIG = REPO / "config" / "run.yaml"
RUNS_DIR = REPO / "runs"
EXIT_BUDGET = 3


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


def _write_summary(
    path: Path,
    scores: list[grader.Scores],
    tasks: list[Task],
    args: argparse.Namespace,
    note: str,
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
                        out.write(json.dumps({"scores": asdict(s), "record": asdict(rec)}) + "\n")
                        out.flush()
        except models.BudgetExceeded as exc:
            note, code = f"STOPPED at budget cap: {exc}", EXIT_BUDGET
    note += f"; spent this run ${budget.spent_usd:.4f} of ${budget.limit_usd:.2f}"
    _write_summary(run_dir / "summary.md", scores, tasks, args, note)
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
