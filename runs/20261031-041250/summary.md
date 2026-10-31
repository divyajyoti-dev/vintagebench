# VintageBench run summary

- tasks: tasks/pilot60.jsonl
- mode: sanity agents
- status: complete; spent this run $0.0000 of $10.00
- yes share (60 yes/no tasks): gold_as_of = Yes 30/60 (50%), gold_revised = Yes 30/60 (50%); majority-class baseline: asof_correct 30/60 (50%), revised_correct 30/60 (50%)

| Agent | Episodes | asof_correct | revised_correct | update_correct (flip) | update_correct (control) | Leakage | Brier | pass^k (asof) | Cost (USD) |
|---|---|---|---|---|---|---|---|---|---|
| oracle | 180 | 180/180 (100%) | 180/180 (100%) | 90/90 (100%) | 90/90 (100%) | 0/180 (0%) | 0.000 | 60/60 (100%) (k=3) | 0.0000 |
| always_yes | 180 | 90/180 (50%) | 90/180 (50%) | 0/90 (0%) | 90/90 (100%) | 0/180 (0%) | 0.250 | 30/60 (50%) (k=3) | 0.0000 |
| leaker | 180 | 90/180 (50%) | 180/180 (100%) | 0/90 (0%) | 90/90 (100%) | 180/180 (100%) | 0.500 | 30/60 (50%) (k=3) | 0.0000 |
| never_update | 180 | 180/180 (100%) | 90/180 (50%) | 0/90 (0%) | 90/90 (100%) | 0/180 (0%) | 0.000 | 60/60 (100%) (k=3) | 0.0000 |

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
| oracle | 180 | 180/180 (100%) | 180/180 (100%) | 360/360 (100%) | 2.0 | 0 | 0 | 0.00000 |
| always_yes | 180 | 180/180 (100%) | 180/180 (100%) | n/a | 0.0 | 0 | 0 | 0.00000 |
| leaker | 180 | 180/180 (100%) | 180/180 (100%) | n/a | 0.0 | 0 | 0 | 0.00000 |
| never_update | 180 | 180/180 (100%) | 180/180 (100%) | 180/180 (100%) | 1.0 | 0 | 0 | 0.00000 |
