# VintageBench run summary

- tasks: tasks/pilot.jsonl
- mode: models
- status: complete; spent this run $0.0081 of $10.00
- yes share (1 yes/no tasks): gold_as_of = Yes 0/1 (0%), gold_revised = Yes 0/1 (0%); majority-class baseline: asof_correct 1/1 (100%), revised_correct 1/1 (100%)

| Agent | Episodes | asof_correct | revised_correct | update_correct (flip) | update_correct (control) | Leakage | Brier | pass^k (asof) | Cost (USD) |
|---|---|---|---|---|---|---|---|---|---|
| openai/gpt-6-sol | 1 | 1/1 (100%) | 1/1 (100%) | n/a | 1/1 (100%) | 0/1 (0%) | 0.000 | 1/1 (100%) (k=1) | 0.0077 |
| openai/gpt-6-luna | 1 | 1/1 (100%) | 1/1 (100%) | n/a | 1/1 (100%) | 0/1 (0%) | 0.000 | 1/1 (100%) (k=1) | 0.0004 |

## Model settings

| Agent | temperature sent | reasoning_effort | max output tokens | tool protocol |
|---|---|---|---|---|
| openai/gpt-6-sol | yes (0) | none | 2048 | native |
| openai/gpt-6-luna | yes (0) | none | 2048 | native |

## Diagnostics

| Agent | Episodes | Turn-1 JSON parsed | Turn-2 JSON parsed | Tool calls returning data | Avg tool calls / episode | Avg input tokens / episode | Avg output tokens / episode | Avg cost / episode (USD) |
|---|---|---|---|---|---|---|---|---|
| openai/gpt-6-sol | 1 | 1/1 (100%) | 1/1 (100%) | 2/2 (100%) | 2.0 | 2,800 | 208 | 0.00768 |
| openai/gpt-6-luna | 1 | 1/1 (100%) | 1/1 (100%) | 2/2 (100%) | 2.0 | 2,822 | 194 | 0.00038 |
