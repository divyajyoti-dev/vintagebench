# VintageBench run summary

- tasks: tasks/pilot60.jsonl
- mode: models
- status: complete; spent this run $1.0012 of $10.00
- yes share (60 yes/no tasks): gold_as_of = Yes 30/60 (50%), gold_revised = Yes 30/60 (50%); majority-class baseline: asof_correct 30/60 (50%), revised_correct 30/60 (50%)

| Agent | Episodes | asof_correct | revised_correct | update_correct (flip) | update_correct (control) | Leakage | Brier | pass^k (asof) | Cost (USD) |
|---|---|---|---|---|---|---|---|---|---|
| openai/gpt-6-sol | 180 | 180/180 (100%) | 179/180 (99%) | 89/90 (99%) | 90/90 (100%) | 0/180 (0%) | 0.000 | 60/60 (100%) (k=3) | 1.4570 |
| openai/gpt-6-luna | 180 | 141/180 (78%) | 157/180 (87%) | 65/90 (72%) | 84/90 (93%) | 0/180 (0%) | 0.216 | 41/60 (68%) (k=3) | 0.0716 |

## Model settings

| Agent | temperature sent | reasoning_effort | max output tokens | tool protocol |
|---|---|---|---|---|
| openai/gpt-6-sol | yes (0) | none | 2048 | native |
| openai/gpt-6-luna | yes (0) | none | 2048 | native |

## Diagnostics

| Agent | Episodes | Turn-1 JSON parsed | Turn-2 JSON parsed | Tool calls returning data | Avg tool calls / episode | Avg input tokens / episode | Avg output tokens / episode | Avg cost / episode (USD) |
|---|---|---|---|---|---|---|---|---|
| openai/gpt-6-sol | 180 | 180/180 (100%) | 180/180 (100%) | 423/423 (100%) | 2.4 | 2,930 | 223 | 0.00809 |
| openai/gpt-6-luna | 180 | 180/180 (100%) | 180/180 (100%) | 360/360 (100%) | 2.0 | 2,920 | 211 | 0.00040 |
