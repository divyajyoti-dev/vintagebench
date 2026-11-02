# Runs

Each `python -m vintagebench.run` invocation writes `runs/<timestamp>/` with
`results.jsonl` (one graded episode per line) and `summary.md` (aggregate tables).
Model responses are cached in `runs/cache/` so reruns are free, and the cumulative spend
ledger is `runs/cache/spend_ledger.json`.

**Nothing under `runs/` except this file is committed.** Tool responses, prompts and
`values_used` contain RTDSM data values, and the Philadelphia Fed terms do not clearly
permit redistributing them (data/NOTICE.md). The committed results are the aggregate
metrics in [results/PILOT.md](../results/PILOT.md). To reproduce them, fetch the data
(`python scripts/fetch_data.py`) and rerun the commands listed there. Reruns call the
API again because the cache is not shipped.
