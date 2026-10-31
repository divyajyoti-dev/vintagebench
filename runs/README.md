# Runs

Each directory `runs/<timestamp>/` is one invocation of `python -m vintagebench.run`
and holds `results.jsonl` (one graded episode per line) and `summary.md` (per-agent
tables, model settings and diagnostics). Results are discussed in
[results/PILOT.md](../results/PILOT.md).

| Directory | Run | Tasks | Agents | Episodes | New API spend |
|---|---|---|---|---|---|
| `20261030-210554/` | sanity agents | `tasks/pilot.jsonl` (20) | oracle, always_yes, leaker, never_update × 3 trials | 240 | $0 (no API) |
| `20261030-210602/` | smoke test | first pilot task | gpt-6-sol, gpt-6-luna × 1 trial | 2 | $0.0081 |
| `20261030-210632/` | full 20-task run | `tasks/pilot.jsonl` (20) | gpt-6-sol, gpt-6-luna × 3 trials | 120 | $0.5193 |
| `20261031-041250/` | sanity agents on 60 | `tasks/pilot60.jsonl` (60) | the 4 sanity agents × 3 trials | 720 | $0 (no API) |
| `20261031-041615/` | full 60-task run | `tasks/pilot60.jsonl` (60) | gpt-6-sol, gpt-6-luna × 3 trials | 360 | $1.0012 |

The full 20-task run replayed the 2 smoke-test episodes from the cache. The 60-task run
replayed all 120 pilot-task episodes from the cache, so only its 240 new-task episodes
cost anything.

## `runs/cache/`

`runs/cache/<provider>/<model>/<task_id>/` holds one JSON file per model call
(`turn<T>_trial<N>_step<S>_<hash>.json`) with the request sent (model, settings,
messages, tool definitions) and the response received (text, tool calls, token counts,
cost). Before each model call the harness looks for a matching file and reuses it, so
rerunning an episode with the same prompts and data costs nothing. The cache is
committed for that reason, and so the published results can be checked.

The cache contains model prompts and responses only. It holds no API keys or request
headers. The prompts include data values served by the `get_series` tool, which are
subject to the data terms in [data/NOTICE.md](../data/NOTICE.md).
