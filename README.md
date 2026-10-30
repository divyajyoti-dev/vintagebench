# VintageBench

Economic data is provisional: payrolls, GDP and inflation are first published as
estimates and revised for months or years afterwards. VintageBench tests whether AI
analysts reason correctly about that. Each task fixes an "as-of" date and gives the model
only the data that had been published by then (using real historical vintages from
ALFRED). It then releases the revised data and asks the model to re-check. We measure
whether answers are right as of the date, whether the model leaks later revised
figures, whether its confidence is calibrated, and whether it updates exactly the
conclusions that the revision should change.

**Status:** pilot in progress. Interfaces are stubbed; see [docs/SPEC.md](docs/SPEC.md).

## How to run

_Placeholder: not implemented yet._

```bash
pip install -e ".[dev]"
cp .env.example .env   # fill in FRED_API_KEY, OPENAI_API_KEY, TOGETHER_API_KEY
python scripts/check_env.py
pytest && ruff check .
# python -m vintagebench.run --models config/models.yaml --tasks tasks/pilot.jsonl --trials 3 --limit 1
```

## Data attribution

Data come from FRED® and ALFRED® (ArchivaL Federal Reserve Economic Data), Federal
Reserve Bank of St. Louis, https://fred.stlouisfed.org/ and https://alfred.stlouisfed.org/.
This product uses the FRED® API but is not endorsed or certified by the Federal Reserve
Bank of St. Louis.
