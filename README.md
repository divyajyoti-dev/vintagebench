# VintageBench

VintageBench tests whether AI analysts reason correctly about provisional data that is
later revised. Each task fixes an "as-of" date, gives the model only the data that had
been published by then, and later hands it the revised data and asks it to re-check its
conclusion. The first test bed is real US economic data vintages (payrolls, GDP,
inflation, industrial production, unemployment) from ALFRED®, the St. Louis Fed's
archive of past data releases.

**Status:** pilot. Two OpenAI models × 3 trials on a 20-task pilot and on a
60-task set (the 20 plus 40 new). Full write-up: [results/PILOT.md](results/PILOT.md).
Interfaces, tasks and metrics: [docs/SPEC.md](docs/SPEC.md).

## What is measured

- **asof_correct:** the turn-1 answer is right using only data published by the as-of date.
- **revised_correct:** the turn-2 answer is right on the revised data.
- **update_correct:** after the revision, the model changes exactly the conclusions that
  should change. It is scored on the model's `changed` flag against the task's `flips`,
  so missed updates and unnecessary updates both count as errors.
- **leakage:** a reported value (`values_used`) matches a later vintage but not the
  as-of vintage, which would suggest memorized revised figures.
- **calibration:** Brier score of the stated turn-1 confidence.

Gold answers are computed from the two vintages by code and never labelled by hand.
Grading is deterministic and uses no LLM judge.

## What a task looks like

One task from [tasks/pilot60.jsonl](tasks/pilot60.jsonl). The `notes` field is
shortened here.

```json
{
  "id": "gdpc1-growth-above-2-2018-10",
  "series_id": "GDPC1",
  "as_of_date": "2019-02-28",
  "question": "Did real GDP grow faster than 2% (annualized) in Q4 2018, i.e. was the annualized growth rate of real GDP (GDPC1) from Q3 2018 to Q4 2018, 100 * ((level(Q4 2018) / level(Q3 2018))^4 - 1), above 2.0%?",
  "answer_type": "yes_no",
  "gold_as_of": true,
  "revision_date": "2020-03-26",
  "gold_revised": false,
  "flips": true,
  "notes": "... annualized QoQ growth (%): as-of 2.589, revised 1.09. ..."
}
```

An episode has two turns:

1. The system prompt says today is 2019-02-28. The model calls the tool
   `get_series(series_id, start, end)`, which returns GDPC1 only as published by that
   date. Q4 2018 growth was first published as 2.59% annualized, so the as-of answer is
   **Yes**. The model replies in JSON: `answer`, `confidence`, `values_used` and `caveats`.
2. The harness says: "A new data release is available as of 2020-03-26. Re-check your
   conclusion." The tool now serves the 2020-03-26 vintage, in which the same quarter
   grew 1.09%. The revised answer is **No**, and the model should report
   `changed: true`.

Tasks whose answer does not change between the two vintages (controls) are mixed in
with tasks whose answer does (flips), so a model cannot score well by always updating.

## Quickstart

Python 3.11. API keys are read from environment variables and are never logged.
Nothing loads `.env` automatically, so export the keys into the shell first.

| Key | Needed for |
|---|---|
| `FRED_API_KEY` | refetching data and `scripts/check_env.py`. Free: https://fred.stlouisfed.org/docs/api/api_key.html |
| `OPENAI_API_KEY` | model runs only (smoke test and full run) |
| `TOGETHER_API_KEY` | only if `config/models.yaml` lists a `provider: together` model; the shipped config does not |

The sanity run, `--estimate`, the tests, and regenerating tasks from the committed
vintages need no keys.

```bash
pip install -e ".[dev]"
cp .env.example .env          # fill in the keys you need
set -a; . ./.env; set +a      # export them into the shell
python scripts/check_env.py   # optional: one free request per key; reports FAIL for unset keys
pytest && ruff check .        # tests never call the network
```

**1. Data (optional; the vintages are committed in `data/vintages/`).**

```bash
python scripts/fetch_data.py            # fetches only series without a parquet file; rewrites data/README.md
python scripts/fetch_data.py --force    # refetch all 5 series (needs FRED_API_KEY)
python scripts/fetch_data.py --readme   # only rewrite data/README.md from the files
```

A `--force` refetch picks up vintages newer than the committed ones. The task files
and the published results are tied to the committed data.

**2. Tasks (optional; the task sets are committed in `tasks/`).** Both are seeded and
deterministic given the data.

```bash
python -m vintagebench.tasks    # 20-task pilot: tasks/pilot.jsonl + tasks/README.md
python -m vintagebench.tasks --extend-from tasks/pilot.jsonl --n 60 \
  --out tasks/pilot60.jsonl --readme-out tasks/README60.md --seed 0   # 60-task set
```

**3. Sanity agents (free: no API calls, no keys).** The four reference agents (oracle,
always_yes, leaker, never_update) check the grader.

```bash
python -m vintagebench.run --tasks tasks/pilot60.jsonl --trials 3 --sanity
```

**4. Smoke test (paid, a few cents).** 1 task × 1 trial per model in
`config/models.yaml`. Always run this before a full run.

```bash
python -m vintagebench.run --models config/models.yaml --tasks tasks/pilot60.jsonl --trials 1 --limit 1
```

**5. Estimate the full run's cost (no API calls, no run directory).** This uses the
measured tokens of cached episodes for each model, or a default estimate if a model has
none. The projection does not subtract episodes already in the cache, so actual new
spend can be lower.

```bash
python -m vintagebench.run --models config/models.yaml --tasks tasks/pilot60.jsonl --trials 3 --estimate
```

**6. Full run (paid).** The run stops before any call that could exceed the budget cap
in `config/run.yaml` ($10), keeps the episodes finished so far, and exits with code 3.

```bash
python -m vintagebench.run --models config/models.yaml --tasks tasks/pilot60.jsonl --trials 3
```

Use `--tasks tasks/pilot.jsonl` for the 20-task pilot. Each run writes
`runs/<timestamp>/results.jsonl` and `summary.md`. Every model request and response is
cached in `runs/cache/`, so rerunning the same episodes costs nothing. The committed
cache holds every episode of both published runs, so with the shipped config and the
committed data, steps 4 and 6 should replay from the cache without new API calls.
Changed prompts, data or models are new requests and are paid. `python -m vintagebench.run --help` lists the other options
(`--data-root`, `--run-config`, `--out-dir`, `--cache-dir`).

## Pilot results

Two full runs with the same 2 models (OpenAI `gpt-6-sol`, frontier, and `gpt-6-luna`,
small), 3 trials per task, temperature 0, reasoning off. Counts are episodes, except
pass^3, which counts tasks where all 3 trials were asof_correct. Lower Brier is better.
Full tables, the sanity-agent rows and the run directories are in
[results/PILOT.md](results/PILOT.md).

**20-task pilot** (10 flips, 10 controls; `runs/20261030-210632/`)

| Model | asof_correct | revised_correct | update_correct (flips) | update_correct (controls) | Leakage | Brier | pass^3 (asof) | Cost (USD) |
|---|---|---|---|---|---|---|---|---|
| gpt-6-sol | 60/60 (100%) | 59/60 (98%) | 29/30 (97%) | 30/30 (100%) | 0/60 (0%) | 0.000 | 20/20 (100%) | 0.5029 |
| gpt-6-luna | 42/60 (70%) | 50/60 (83%) | 18/30 (60%) | 25/30 (83%) | 0/60 (0%) | 0.299 | 12/20 (60%) | 0.0245 |
| majority class | 30/60 (50%) | 30/60 (50%) | – | – | – | – | 10/20 (50%) | 0 |

**60-task set** (the 20 plus 40 new; 30 flips in 18 overlap clusters, 30 controls;
`runs/20261031-041615/`)

| Model | asof_correct | revised_correct | update_correct (flips) | update_correct (controls) | Leakage | Brier | pass^3 (asof) | Cost (USD) |
|---|---|---|---|---|---|---|---|---|
| gpt-6-sol | 180/180 (100%) | 179/180 (99%) | 89/90 (99%) | 90/90 (100%) | 0/180 (0%) | 0.000 | 60/60 (100%) | 1.4570 |
| gpt-6-luna | 141/180 (78%) | 157/180 (87%) | 65/90 (72%) | 84/90 (93%) | 0/180 (0%) | 0.216 | 41/60 (68%) | 0.0716 |
| majority class | 90/180 (50%) | 90/180 (50%) | – | – | – | – | 30/60 (50%) | 0 |

The 60-task Cost column is the recorded cost of all 360 episodes. The 120 pilot-task
episodes were replayed from the cache, so they are not a replication, and new spend for
that run was $1.0012. Total API spend for both runs was about $1.53.

**Findings**

- **The set separates the two models but does not challenge the frontier one.**
  gpt-6-sol is at the ceiling: its only error in 180 episodes is one turn-2 label slip.
  gpt-6-luna is below 90% on asof_correct and update_correct on both runs.
- **Most errors look like label slips, not mistakes about vintages.** 30 of gpt-6-luna's
  39 wrong turn-1 answers, and 20 of its 23 wrong turn-2 answers, have a yes/no label
  that contradicts the model's own stated calculation. We hypothesize that the
  answer-first reply schema with reasoning off contributed; neither run tested this.
  All 12 of its genuine reasoning errors are on one template (payrolls
  weakest-of-12-months).
- **No leakage was detected (0/360), but this is weak evidence.** The models copied tool
  output into `values_used`. The check catches only reported values, so it cannot detect
  a memorized revised figure that shaped an answer without being reported.

**Caveats**

- 2 models, not the 3 in SPEC §7. The open-weight Together model was skipped, so the
  plain-text tool protocol was not tested against a live model.
- Small n: 60 tasks × 3 trials, with only 18 effective flip clusters. Trials at
  temperature 0 are far from independent. No confidence intervals are reported.
- The label-slip explanation is a hypothesis, not a tested result.
- gpt-6-luna is overconfident (mean confidence 0.999 on its wrong turn-1 answers).
  gpt-6-sol's calibration cannot be assessed because it made no turn-1 errors.
- update_correct relies on the self-reported `changed` flag. Some controls are far from
  their threshold, and the flip pool for several templates is exhausted.
- Prices in `config/models.yaml` came from search summaries of the provider's docs and
  are unverified. Token counts are measured.

See [results/PILOT.md](results/PILOT.md) §6–§7 for the full findings and limitations.

## Repo layout

```
src/vintagebench/     package (interfaces in docs/SPEC.md §5)
  data.py             load vintages; get_as_of(series, date)
  tasks.py            task templates, gold answers, seeded selection; CLI
  models.py           OpenAI-SDK client for "openai" and "together" providers
  episode.py          two-turn episode with the get_series tool
  grader.py           deterministic scoring and summaries
  sanity.py           no-API reference agents
  run.py              CLI: sanity, smoke, estimate and full runs, with budget cap
scripts/
  fetch_data.py       download ALFRED vintages via the FRED API
  check_env.py        check API keys with one free request each
config/
  models.yaml         models, providers and prices
  run.yaml            budget cap, default trials, temperature, max tokens
data/
  vintages/           <SERIES>.parquet vintage data (committed)
  README.md           per-series vintage counts and revision sizes
  NOTICE.md           data sources, copyright status and terms
tasks/
  pilot.jsonl         20-task pilot (+ README.md)
  pilot60.jsonl       60-task set (+ README60.md)
runs/                 run outputs and the committed response cache (see runs/README.md)
results/PILOT.md      pilot write-up
docs/SPEC.md          specification
tests/                pytest suite (no network; fixtures in tests/fixtures/)
```

## Data and citation

The data are real-time vintages of five series, retrieved from ALFRED® (ArchivaL
Federal Reserve Economic Data) and FRED®, Federal Reserve Bank of St. Louis, via the
FRED® API: https://alfred.stlouisfed.org/ and https://fred.stlouisfed.org/. The
original sources are:

- **PAYEMS** (All Employees, Total Nonfarm) and **UNRATE** (Unemployment Rate):
  U.S. Bureau of Labor Statistics.
- **GDPC1** (Real Gross Domestic Product) and **PCEPI** (Personal Consumption
  Expenditures: Chain-type Price Index): U.S. Bureau of Economic Analysis.
- **INDPRO** (Industrial Production: Total Index): Board of Governors of the Federal
  Reserve System (US).

This product uses the FRED® API but is not endorsed or certified by the Federal Reserve
Bank of St. Louis. Use of the data is subject to the FRED® API Terms of Use
(https://fred.stlouisfed.org/docs/api/terms_of_use.html) and the FRED® terms on the
legal page (https://fred.stlouisfed.org/legal). See [data/NOTICE.md](data/NOTICE.md)
for per-series copyright status, retrieval dates and suggested citations.

## License

The code is released under the MIT License ([LICENSE](LICENSE)). The data in
`data/vintages/`, and the data values that appear in `tasks/` and `runs/`, are not
covered by that license. They are subject to the terms of their sources; see
[data/NOTICE.md](data/NOTICE.md).

## How to cite VintageBench

If you use VintageBench, please cite it as below and also cite the data sources
(see [data/NOTICE.md](data/NOTICE.md)). Citation metadata is in
[CITATION.cff](CITATION.cff).

> Divya Jyoti. *VintageBench: do AI analysts reason correctly about provisional data
> that is later revised?* Version 0.0.1 (pre-release), 2026.
> https://github.com/divyajyoti-dev/vintagebench

```bibtex
@software{jyoti_vintagebench_2026,
  author  = {Jyoti, Divya},
  title   = {VintageBench},
  version = {0.0.1},
  year    = {2026},
  url     = {https://github.com/divyajyoti-dev/vintagebench}
}
```
