# VintageBench

Economic data is provisional: payrolls, GDP and inflation are first published as
estimates and revised for months or years afterwards. VintageBench tests whether AI
analysts reason correctly about that. Each task fixes an "as-of" date and gives the model
only the data that had been published by then (using real historical vintages from
ALFRED). It then releases the revised data and asks the model to re-check. We measure
whether answers are right as of the date, whether the model leaks later revised
figures, whether its confidence is calibrated, and whether it updates exactly the
conclusions that the revision should change.

**Status:** pilot complete (2 OpenAI models × 20 tasks × 3 trials). Results:
[results/PILOT.md](results/PILOT.md). Spec: [docs/SPEC.md](docs/SPEC.md).

## How to run

Python 3.11. API keys are read from environment variables (nothing loads `.env`
automatically, so export them first) and are never logged.

```bash
pip install -e ".[dev]"
cp .env.example .env          # fill in FRED_API_KEY, OPENAI_API_KEY, TOGETHER_API_KEY
set -a; . ./.env; set +a      # export them into the shell
python scripts/check_env.py   # checks each key with one free request
# check_env reports FAIL for TOGETHER_API_KEY when it is unset. That key is needed only
# if config/models.yaml lists a Together model; the pilot needs only FRED and OpenAI keys.
pytest && ruff check .        # tests never call the network

# 1. Fetch ALFRED vintages into data/vintages/ (already committed; needs FRED_API_KEY)
python scripts/fetch_data.py            # add --force to refetch, --readme to only rewrite data/README.md

# 2. Regenerate the pilot tasks (tasks/pilot.jsonl + tasks/README.md; seeded, deterministic)
python -m vintagebench.tasks

# 3. Sanity agents (no API calls, no keys)
python -m vintagebench.run --tasks tasks/pilot.jsonl --trials 3 --sanity

# 4. Smoke test: 1 task x 1 trial per model in config/models.yaml (paid, a few cents)
python -m vintagebench.run --models config/models.yaml --tasks tasks/pilot.jsonl --trials 1 --limit 1

# 5. Estimate the cost of the full run (no API calls; averages tokens over all cached
#    episodes in runs/cache/ for each model, which now include the full pilot run)
python -m vintagebench.run --models config/models.yaml --tasks tasks/pilot.jsonl --trials 3 --estimate

# 6. Full run (paid; stops at the budget cap in config/run.yaml)
python -m vintagebench.run --models config/models.yaml --tasks tasks/pilot.jsonl --trials 3
```

Each run writes `runs/<timestamp>/results.jsonl` and `summary.md`. Every model
request/response is cached in `runs/cache/`, so reruns of the same episodes are free.

## Pilot results

Full run `runs/20261030-210632/`: 20 tasks (10 flips, 10 controls) × 3 trials per model,
temperature 0, reasoning off. Total API spend $0.53 (smoke test included). The pilot
ran 2 models instead of the 3 in SPEC §7: the Together open-weight model was skipped at
the user's request; no Together API key was configured.

| Model | asof_correct | revised_correct | update_correct (flips) | update_correct (controls) | Leakage | Brier | pass^3 (asof) | Cost (USD) |
|---|---|---|---|---|---|---|---|---|
| gpt-6-sol | 60/60 (100%) | 59/60 (98%) | 29/30 (97%) | 30/30 (100%) | 0/60 (0%) | 0.000 | 20/20 (100%) | 0.5029 |
| gpt-6-luna | 42/60 (70%) | 50/60 (83%) | 18/30 (60%) | 25/30 (83%) | 0/60 (0%) | 0.299 | 12/20 (60%) | 0.0245 |
| majority class | 30/60 (50%) | 30/60 (50%) | – | – | – | – | 10/20 (50%) | 0 |

Most errors are the yes/no answer contradicting the model's own stated calculation, not
mistakes about data vintages. The sample is small. See [results/PILOT.md](results/PILOT.md)
for the setup, failure examples, findings and limitations.

## Data attribution

Data come from FRED® and ALFRED® (ArchivaL Federal Reserve Economic Data), Federal
Reserve Bank of St. Louis, https://fred.stlouisfed.org/ and https://alfred.stlouisfed.org/.
This product uses the FRED® API but is not endorsed or certified by the Federal Reserve
Bank of St. Louis.
