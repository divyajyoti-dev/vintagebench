# VintageBench run summary

- tasks: tasks/pilot.jsonl
- mode: sanity agents
- status: complete; spent this run $0.0000 of $10.00
- yes share (20 yes/no tasks): gold_as_of = Yes 10/20 (50%), gold_revised = Yes 10/20 (50%); majority-class baseline: asof_correct 10/20 (50%), revised_correct 10/20 (50%)

| Agent | Episodes | asof_correct | revised_correct | update_correct (flip) | update_correct (control) | Leakage | Brier | pass^k (asof) | Cost (USD) |
|---|---|---|---|---|---|---|---|---|---|
| oracle | 60 | 60/60 (100%) | 60/60 (100%) | 30/30 (100%) | 30/30 (100%) | 0/60 (0%) | 0.000 | 20/20 (100%) (k=3) | 0.0000 |
| always_yes | 60 | 30/60 (50%) | 30/60 (50%) | 0/30 (0%) | 30/30 (100%) | 0/60 (0%) | 0.250 | 10/20 (50%) (k=3) | 0.0000 |
| leaker | 60 | 30/60 (50%) | 60/60 (100%) | 0/30 (0%) | 30/30 (100%) | 60/60 (100%) | 0.500 | 10/20 (50%) (k=3) | 0.0000 |
| never_update | 60 | 60/60 (100%) | 30/60 (50%) | 0/30 (0%) | 30/30 (100%) | 0/60 (0%) | 0.000 | 20/20 (100%) (k=3) | 0.0000 |

## Model settings

| Agent | temperature sent | reasoning_effort | max output tokens | tool protocol |
|---|---|---|---|---|
| oracle | n/a (no API) | n/a | n/a | native loop |
| always_yes | n/a (no API) | n/a | n/a | native loop |
| leaker | n/a (no API) | n/a | n/a | native loop |
| never_update | n/a (no API) | n/a | n/a | native loop |

## Diagnostics

| Agent | Episodes | Turn-1 JSON parsed | Turn-2 JSON parsed | Tool calls returning data | Avg tool calls / episode | Avg input tokens / episode | Avg output tokens / episode | Avg cost / episode (USD) |
|---|---|---|---|---|---|---|---|---|
| oracle | 60 | 60/60 (100%) | 60/60 (100%) | 120/120 (100%) | 2.0 | 0 | 0 | 0.00000 |
| always_yes | 60 | 60/60 (100%) | 60/60 (100%) | n/a | 0.0 | 0 | 0 | 0.00000 |
| leaker | 60 | 60/60 (100%) | 60/60 (100%) | n/a | 0.0 | 0 | 0 | 0.00000 |
| never_update | 60 | 60/60 (100%) | 60/60 (100%) | 60/60 (100%) | 1.0 | 0 | 0 | 0.00000 |
