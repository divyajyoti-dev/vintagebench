# VintageBench spec

## 1. Goal and metrics
Can an AI analyst reason correctly about provisional data that later gets revised?
- asof_correct: right answer using only data published by the task's as-of date
- leakage: uses values from later vintages (e.g. memorized revised figures)
- calibration: Brier score of stated confidence on first-turn answers
- update_correct: after revised data arrives, changes exactly the conclusions that
  should change (penalizes missed AND unnecessary updates)

## 2. Data
- Series: PAYEMS, GDPC1, PCEPI, INDPRO, UNRATE (UNRATE = low-revision control).
- Observations from 2015 onward; vintages from 2016 onward. Pull via the ALFRED API
  (series/vintagedates; series/observations with realtime_start/realtime_end) or
  fredapi; verify behavior against official docs.
- Storage: data/vintages/<SERIES>.parquet, columns series_id, observation_date,
  vintage_date, value. Committed to the repo.
- get_as_of returns, per observation, the latest value with vintage_date <= as_of date.
- data/README.md: per series, number of vintages and mean absolute revision
  (first release vs latest).
- Tests: as-of never returns future vintages; two dates give different values for a
  shared observation; one documented real revision reproduced (source cited in comment).

## 3. Tasks
Schema (tasks/pilot.jsonl): id, series_id, as_of_date, question,
answer_type ("yes_no"|"number"), gold_as_of, revision_date, gold_revised, flips, notes.
- Gold answers computed programmatically from the two vintages; never hand-labeled.
- Templates (natural questions; thresholds only at round numbers):
  "Did real GDP shrink in <quarter>?"
  "Was <month> the weakest month for payroll growth in the prior 12 months?"
  "Was average monthly payroll growth over the 3 months ending <month> above 100k/150k?"
  "Did industrial production fall in <month> versus the prior month?"
  "Is PCE inflation (year over year) above 2.5% as of <month>?"
- Pilot selection: 20 tasks across 2016–2025: ~10 with flips=true, ~10 controls
  (including 2 UNRATE). Spread across series and years; no duplicates. Seeded.
- tasks/README.md: table of all tasks (question, as-of answer, revised answer, flips).

## 4. Harness
- Providers via the OpenAI Python SDK: "openai" (default base URL) and "together"
  (base_url https://api.together.xyz/v1). Provider, model ID, prices in config/models.yaml.
- If a model lacks native tool calling, use a plain-text tool protocol (model emits JSON
  tool request; harness parses and replies). Test both paths.
- temperature 0, retries with backoff, cache every request/response in runs/cache/
  keyed by (provider, model, task_id, turn, trial); track tokens and cost; stop at budget cap.
- Episode, turn 1: system prompt states today is <as_of_date>; tool
  get_series(series_id, start, end) returns ONLY data as of that date. Reply JSON:
  {answer, confidence (0-1), values_used: {date: value}, caveats}.
- Turn 2: "A new data release is available as of <revision_date>. Re-check your
  conclusion." Tool now returns data as of revision_date. Reply JSON:
  {answer, confidence, changed (bool), reason}.
- Grader (deterministic, no LLM judge): asof_correct, revised_correct, update_correct
  (changed == flips), leakage (a values_used entry matches a later vintage but not the
  as-of vintage, with rounding tolerance), Brier score.
- Sanity agents (no API): oracle (100% everything, 0 leakage), always_yes (~50%),
  leaker (reads latest vintage; leakage flagged wherever values differ),
  never_update (update_correct only on controls).
- CLI: python -m vintagebench.run --models config/models.yaml --tasks tasks/pilot.jsonl
  --trials 3 [--limit N] [--sanity] -> runs/<timestamp>/results.jsonl + summary.md

## 5. Interfaces (src/vintagebench/)
- data.py: load_vintages(series_id, root=DATA_DIR) -> DataFrame;
  vintage_dates(series_id, root=DATA_DIR) -> list[date];
  get_as_of(series_id, as_of: date, root=DATA_DIR) -> pd.Series (index observation_date)
- tasks.py: dataclass Task (fields per §3); build_candidates(series_ids, root) -> list[Task];
  select_pilot(candidates, n=20, seed=0) -> list[Task]; save_tasks(path, tasks);
  load_tasks(path) -> list[Task]
- models.py: dataclass ModelSpec(provider, model_id, price_in, price_out, native_tools);
  dataclass ModelResponse(text, tool_calls, input_tokens, output_tokens, cost_usd);
  complete(spec, messages, tools) -> ModelResponse
- episode.py: dataclass EpisodeRecord; run_episode(task, agent, trial, root) -> EpisodeRecord
  (agent = ModelSpec or sanity agent)
- grader.py: dataclass Scores; grade(task, record, root) -> Scores;
  summarize(scores) -> DataFrame
- sanity.py: oracle, always_yes, leaker, never_update (same call interface as a model:
  agent(messages, tools, *, task, root) -> ModelResponse, driven through the same
  tool-call loop; task/root are harness-side context, never shown to models)
- run.py: CLI per §4

## 6. Subagent roles (each edits only owned files + own tests)
- data-engineer: data.py, data/, scripts/fetch_data.py
- task-designer: tasks.py, tasks/
- harness-engineer: models.py, episode.py, grader.py, sanity.py, run.py, config/
- reviewer (read/run only): recomputes gold answers for sampled tasks from raw vintages,
  checks leakage logic and sanity-agent scores, checks every claim in docs against
  results files. Reports issues; does not edit.

## 7. Pilot
- 3 models: one frontier OpenAI model, one small/cheap OpenAI model, one open-weight
  Together model with tool support. Verify current IDs and prices in provider docs.
- Order: sanity agents (free) -> smoke test (1 task x 1 trial per model) -> full run
  (20 tasks x 3 trials). Budget cap $10.
- results/PILOT.md: per-model table (asof_correct, revised_correct, update_correct split
  flip/control, leakage rate, Brier, pass^3 on asof_correct, cost); 3 real failure
  examples; limitations. Report counts with percentages; don't overstate.
