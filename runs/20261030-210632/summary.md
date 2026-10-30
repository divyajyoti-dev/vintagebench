# VintageBench run summary

- tasks: tasks/pilot.jsonl
- mode: models
- status: complete; spent this run $0.5193 of $10.00
- yes share (20 yes/no tasks): gold_as_of = Yes 10/20 (50%), gold_revised = Yes 10/20 (50%); majority-class baseline: asof_correct 10/20 (50%), revised_correct 10/20 (50%)

| Agent | Episodes | asof_correct | revised_correct | update_correct (flip) | update_correct (control) | Leakage | Brier | pass^k (asof) | Cost (USD) |
|---|---|---|---|---|---|---|---|---|---|
| openai/gpt-6-sol | 60 | 60/60 (100%) | 59/60 (98%) | 29/30 (97%) | 30/30 (100%) | 0/60 (0%) | 0.000 | 20/20 (100%) (k=3) | 0.5029 |
| openai/gpt-6-luna | 60 | 42/60 (70%) | 50/60 (83%) | 18/30 (60%) | 25/30 (83%) | 0/60 (0%) | 0.299 | 12/20 (60%) (k=3) | 0.0245 |

## Model settings

| Agent | temperature sent | reasoning_effort | max output tokens | tool protocol |
|---|---|---|---|---|
| openai/gpt-6-sol | yes (0) | none | 2048 | native |
| openai/gpt-6-luna | yes (0) | none | 2048 | native |

## Diagnostics

| Agent | Episodes | Turn-1 JSON parsed | Turn-2 JSON parsed | Tool calls returning data | Avg tool calls / episode | Avg input tokens / episode | Avg output tokens / episode | Avg cost / episode (USD) |
|---|---|---|---|---|---|---|---|---|
| openai/gpt-6-sol | 60 | 60/60 (100%) | 60/60 (100%) | 147/147 (100%) | 2.5 | 3,017 | 235 | 0.00838 |
| openai/gpt-6-luna | 60 | 60/60 (100%) | 60/60 (100%) | 120/120 (100%) | 2.0 | 3,025 | 210 | 0.00041 |
