# VintageBench

VintageBench tests whether AI analysts reason correctly about provisional data that is
later revised. Each task fixes an "as-of" date and serves the model, through a tool,
only the data published by then. A second turn then serves the revised data. The data
are real-time vintages of US macroeconomic series (payrolls, real GDP, industrial
production, the unemployment rate, CPI) from the **Real-Time Data Set for
Macroeconomists (RTDSM) of the Federal Reserve Bank of Philadelphia**.

**Status:** v1 pilot: 45 tasks, 2 OpenAI models × reasoning off/on, 3 trials. Results:
[results/PILOT.md](results/PILOT.md). Interfaces, tasks and metrics:
[docs/SPEC.md](docs/SPEC.md).

## What is measured

- **asof_correct / revised_correct:** the turn-1 (turn-2) answer is right using only
  the data published as of the as-of (revision) date.
- **update_correct:** the answer changes between turns exactly when the conclusion
  should change (`flips`). Missed and unnecessary updates both count as errors.
- **survival calibration:** in turn 1 the model also states the probability that its
  conclusion still holds after the data are fully revised. This is scored against what
  actually happened.
- **leakage, label/text contradiction, memorization probe:** reported values matching
  later vintages; answer labels that contradict the model's own numbers; and, with no
  tools, whether the model's recall matches first-release or latest-vintage values.

Gold answers are computed from the vintages by code, never labelled by hand. Grading
is deterministic and uses no LLM judge.

## Task format

Tasks state the question in plain words, e.g. *"Did US industrial production fall in
<month>?"* or *"Did US real GDP grow faster than a 2% annual rate in <quarter>?"*.
`tasks/v1.jsonl` stores definitions only (series, template, period, threshold, as-of
and revision dates, kind). The 45 tasks are 20 flips (the first-release conclusion
differs from the latest vintage), 20 controls and 5 no-change tasks (the turn-2 data
are identical). See [tasks/README.md](tasks/README.md); base rates of conclusion flips
are in [tasks/BASE_RATES.md](tasks/BASE_RATES.md).

## Quickstart

```bash
pip install -e ".[dev]"
python scripts/fetch_data.py          # download RTDSM files to data/raw/ and verify checksums
python -m pytest -q && ruff check .
python -m vintagebench.run --tasks tasks/v1.jsonl --sanity --probe   # no API calls
python -m vintagebench.run --models config/models.yaml --tasks tasks/v1.jsonl --trials 1 --limit 1 --probe   # smoke test
python -m vintagebench.run --models config/models.yaml --tasks tasks/v1.jsonl --trials 3 --probe --project-cost
python -m vintagebench.run --models config/models.yaml --tasks tasks/v1.jsonl --trials 3 --probe
```

Paid runs need `OPENAI_API_KEY` in the environment and stop at the cumulative budget
cap in `config/run.yaml`.

## Repo layout

```
config/    model configs and run settings (budget cap)
data/      NOTICE.md (terms, citation), README.md (variable mapping), checksums, manifest
           data/raw/ is local only (gitignored)
docs/      SPEC.md
results/   PILOT.md (aggregate results)
runs/      local run outputs and response cache (gitignored)
scripts/   fetch_data.py, check_env.py
src/vintagebench/  data, tasks, models, episode, grader, sanity, run
tasks/     v1.jsonl (definitions), README.md, BASE_RATES.md
tests/     offline tests with synthetic fixtures
```

## Data and credit

Data: Federal Reserve Bank of Philadelphia, Real-Time Data Set for Macroeconomists,
https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/real-time-data-set-for-macroeconomists
(variables EMPLOY, ROUTPUT, IPT, RUC, PCPI). The original sources are the U.S. Bureau
of Labor Statistics, the U.S. Bureau of Economic Analysis and the Board of Governors of
the Federal Reserve System. Please cite Croushore, Dean, and Tom Stark, "A Real-Time
Data Set for Macroeconomists," *Journal of Econometrics* 105 (November 2001),
pp. 111-130.

The Philadelphia Fed's terms allow use "for informational, educational, and research
purposes only". They grant no explicit right to redistribute, so **this repository
contains no RTDSM data**: you download it yourself with `scripts/fetch_data.py`.
The Federal Reserve Bank of Philadelphia and the source agencies do not sponsor or
endorse VintageBench. Details and verbatim terms: [data/NOTICE.md](data/NOTICE.md).

## License

Code: MIT ([LICENSE](LICENSE)). The license does not cover the data.

## How to cite VintageBench

See [CITATION.cff](CITATION.cff).
