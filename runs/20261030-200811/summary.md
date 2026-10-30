# VintageBench run summary

- tasks: tasks/pilot.jsonl
- mode: sanity agents
- status: complete; spent this run $0.0000 of $10.00

| Agent | Episodes | asof_correct | revised_correct | update_correct (flip) | update_correct (control) | Leakage | Brier | pass^k (asof) | Cost (USD) |
|---|---|---|---|---|---|---|---|---|---|
| oracle | 60 | 60/60 (100%) | 60/60 (100%) | 30/30 (100%) | 30/30 (100%) | 0/60 (0%) | 0.000 | 20/20 (100%) (k=3) | 0.0000 |
| always_yes | 60 | 15/60 (25%) | 27/60 (45%) | 0/30 (0%) | 30/30 (100%) | 0/60 (0%) | 0.250 | 5/20 (25%) (k=3) | 0.0000 |
| leaker | 60 | 30/60 (50%) | 60/60 (100%) | 0/30 (0%) | 30/30 (100%) | 60/60 (100%) | 0.500 | 10/20 (50%) (k=3) | 0.0000 |
| never_update | 60 | 60/60 (100%) | 30/60 (50%) | 0/30 (0%) | 30/30 (100%) | 0/60 (0%) | 0.000 | 20/20 (100%) (k=3) | 0.0000 |
