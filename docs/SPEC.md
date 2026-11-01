# VintageBench spec (v1)

v1 replaces the v0 data source (ALFRED/FRED, removed; see §8) with the Philadelphia Fed
Real-Time Data Set for Macroeconomists (RTDSM) and changes the episode protocol (§4).

## 1. Goal and metrics
Can an AI analyst reason correctly about provisional data that later gets revised?
- asof_correct: turn-1 answer equals the gold computed from the as-of vintage
- revised_correct: turn-2 answer equals the gold computed from the revision vintage
- update_correct: changed == flips, where changed = (turn-2 answer != turn-1 answer).
  The self-reported `changed` flag is kept only as a diagnostic (agreement rate).
- survival calibration: turn-1 `survival_prob` (probability the conclusion still holds
  after the data are fully revised) scored against survived = (turn-1 answer ==
  gold_revised); Brier score, mean survival_prob vs empirical survival rate, and a
  reliability table (bins 0-0.5, 0.5-0.8, 0.8-0.95, 0.95-1.0)
- confidence Brier: turn-1 confidence vs asof_correct
- leakage: a values_used entry matches a later vintage but not the as-of vintage
  (rounding tolerance)
- label/text contradiction: the answer label disagrees with the answer implied by the
  model's own reported values_used (gold function applied to them), or with an explicit
  final conclusion in `calculation` (regex: "answer is yes/no", "so yes/no", etc.)
- memorization probe (§4.4): share of recalled key observations matching the first
  release, the latest vintage, both (indistinguishable), or neither

## 2. Data (RTDSM)
- Source: Federal Reserve Bank of Philadelphia, Real-Time Data Set for Macroeconomists,
  https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/real-time-data-set-for-macroeconomists
  Terms and citation: data/NOTICE.md. Redistribution is not clearly granted, so the
  repository commits **no raw data** (§2.3).
- Series (RTDSM variable, file): EMPLOY (nonfarm payrolls, employMvMd.xlsx), ROUTPUT
  (real GDP, routputMvQd.xlsx), IPT (industrial production total, iptMvMd.xlsx), RUC
  (unemployment rate, rucQvMd.xlsx; quarterly vintages, low-revision control), PCPI
  (CPI; substitute for a monthly PCE price index, which RTDSM does not provide with
  monthly vintages). Mapping and verification: data/README.md.
- Vintages: RTDSM columns are periodic snapshots (monthly for EMPLOY, ROUTPUT, IPT, PCPI;
  quarterly, mid-quarter, for RUC). Each vintage label (e.g. EMPLOY18M11) is mapped to a
  vintage_date on or after the latest release it incorporates (rule per series in
  data/README.md, quoting RTDSM docs). Task as_of_date and revision_date are always
  RTDSM vintage dates.
- Range: observations from 2015 onward; vintages from 2016 onward up to the pinned last
  vintage in data/manifest.json.

### 2.1 Interfaces (data.py)
- load_vintages(series_id, root=RAW_DIR) -> DataFrame (series_id, observation_date,
  vintage, vintage_date, value), parsed from the downloaded xlsx and cached as
  parquet in data/raw/ (gitignored)
- vintage_dates(series_id, root=RAW_DIR) -> list[date] (pinned range only)
- get_as_of(series_id, as_of: date, root=RAW_DIR) -> pd.Series: the full column of the
  latest vintage with vintage_date <= as_of (index observation_date)
- first_release(series_id, obs, root) and latest_value(series_id, obs, root) for the
  memorization probe and base rates

### 2.2 Fetch and verification
- scripts/fetch_data.py downloads the five xlsx files to data/raw/ and verifies them:
  data/checksums.json (committed) stores per series the SHA-256 of the canonical parsed
  table restricted to the pinned vintages (robust to RTDSM appending new vintages each
  month) and the SHA-256 of the file as downloaded on the pin date (informational).
- Missing data/raw -> clear error telling the user to run scripts/fetch_data.py.

### 2.3 No raw values in the repository
- Not committed: xlsx, parquet, tool responses, model prompts/responses, per-episode
  results (runs/ is gitignored except runs/README.md).
- Tasks store only definitions (series, template, period, threshold, dates, kind);
  golds and margins are computed at load time from the local data.
- Committed results are aggregate metrics only. Docs never quote data values; quoted
  model text has numbers redacted as [value].
- Tests use small synthetic fixtures, never RTDSM values.

## 3. Tasks
- Schema (tasks/v1.jsonl): id, series_id, template, period, threshold, as_of_date,
  revision_date, question, answer_type ("yes_no"), kind ("flip"|"control"|"no_change"),
  notes. load_tasks(path, root) recomputes gold_as_of, gold_revised, flips and margins
  and fails if they disagree with kind.
- Questions state the question, not the formula (e.g. "Did US real GDP shrink in
  2018 Q4?"). Conventions used for gold (documented in tasks/README.md): GDP growth =
  annualized quarter-over-quarter percent change of the level; payroll change = level
  difference in thousands; IP fell = month-over-month level decline; inflation =
  12-month percent change of CPI (seasonally adjusted index, as in RTDSM); CPI monthly
  change = one-month percent change (template added because 12-month CPI conclusions
  essentially never flip); unemployment rose = month-over-month increase of the rate
  at its published 0.1 precision.
- Periods 2016-2025 whose first release is after the baseline vintage; as_of_date =
  first vintage containing the period. flip/control revision_date = pinned latest
  vintage; no_change revision_date = last vintage of the unbroken run of vintages with
  an identical computation window.
- Gold answers computed programmatically from the two vintages; never hand-labeled;
  every gold function has a unit test.
- Selection (select_v1(candidates, seed=0)): 45 tasks = 20 flips, 20 controls,
  5 no-change. As-of answer balanced Yes/No within each kind (10/10, 10/10, 3/2 or
  2/3). Spread across series and years; minimal same-series computation-window
  overlap.
  - Materiality: deciding quantity clears its threshold by at least the margin
    (~half a publication unit) in both vintages.
  - Controls (tighter than v0): |distance| <= per-template cap in BOTH vintages.
  - No-change tasks: every observation in the computation window is identical in the
    as-of and revision vintages (turn-2 data identical); revision_date is a later
    vintage.
  - COVID exclusion: no task (any kind) whose computation window touches 2020-02..
    2021-03 (2020 Q1..2021 Q1 for GDP).
  - revision_date - as_of_date >= 365 days for flips and controls.
- Base rates (tasks/BASE_RATES.md, aggregate counts only): over ALL candidates
  (before and after the margin/materiality filters), how often the conclusion from the
  first-release vintage differs from the conclusion in the pinned latest vintage, and
  from the conclusion one year later; by series and template, with counts.

## 4. Harness
- Providers via the OpenAI Python SDK ("openai"; "together" kept, untested in v1).
  Model configs (provider, model ID, reasoning_effort, prices) in config/models.yaml.
- GPT-6 models allow Chat Completions function calling only with reasoning_effort
  "none", so all v1 configs use the plain-text JSON tool protocol (native_tools false)
  so that reasoning off/on are compared under one protocol.
- temperature 0 where supported (reasoning-on configs omit it), retries with backoff,
  cache every request/response in runs/cache/ keyed by (provider, model, config,
  task_id, turn, trial); track tokens and cost; stop at budget cap (config/run.yaml).
  The cap is cumulative across runs (ledger runs/cache/spend_ledger.json). Before any
  paid run the sanity agents run in memory on the same tasks; any missed expectation
  exits with code 4 and no API call.

### 4.1 Turn 1
System prompt: today is <as_of_date>; tool get_series(series_id, start, end) returns
ONLY data as of that date. Reply JSON, keys in this order:
{calculation, answer, confidence (0-1), survival_prob (0-1), values_used: {date: value},
caveats}. The prompt asks for survival_prob as: "Probability (0-1) that this conclusion
still holds after the data is fully revised".

### 4.2 Turn 2 (neutral)
User message: "Today is <revision_date>. Here is the latest data. Answer the question."
followed by the get_series results for the turn-1 tool requests, re-served as of
revision_date (deduplicated; if turn 1 made no successful request, only the sentence
is sent). The tool stays available and serves revision_date data. Reply JSON:
{calculation, answer, confidence, changed (bool), values_used, reason}.

### 4.3 Grader
Deterministic, no LLM judge: asof_correct, revised_correct, update_correct (actual
change), self_report_agrees, leakage per turn (a value matching a vintage after that
turn's date but not the vintage as of it), contradiction per turn, confidence Brier,
survival Brier. Missing or out-of-range probabilities are excluded from Briers and
counted as missing.

### 4.4 Memorization probe
Per task and model config, one call with no tools: ask for the values of the task's
key observations (the observations its gold depends on) as JSON {date: value}. Each
recalled value is classified by tolerance tol = max(rounding unit, 1e-4 x |ref|):
"both" if first release and latest are indistinguishable and the recall matches,
otherwise first_release / latest (nearer if both) / neither; null = no_answer. Per task,
the majority over distinguishable observations ("mixed" on a tie). ROUTPUT and IPT are
probed on the deciding growth rate rather than levels, because their base year changes
across vintages. Cached and budgeted like
episodes.

### 4.5 Sanity agents (no API)
oracle (100%, 0 leakage, survival_prob = 1 if not flips else 0), always_yes, leaker
(reads latest vintage), never_update, and for the probe first_release_recaller and
latest_recaller (must classify 100% first-release / latest on distinguishable values).

### 4.6 CLI
python -m vintagebench.run --models config/models.yaml --tasks tasks/v1.jsonl
--trials 3 [--limit N] [--sanity] [--probe] [--project-cost] ->
runs/<timestamp>/results.jsonl (local only) + summary.md (aggregates only).

## 5. Interfaces (src/vintagebench/)
- data.py: §2.1
- tasks.py: dataclass Task (fields per §3 plus computed gold_as_of, gold_revised,
  flips, margin_as_of, margin_revised); build_candidates(series_ids, root);
  select_v1(candidates, seed=0); base_rates(candidates, root); save_tasks(path, tasks);
  load_tasks(path, root); for the harness: implied_answer(task, values) -> bool | None,
  key_observations(task) -> list[date], computation_window(task) -> tuple[date, ...],
  task_clusters(tasks) -> dict[id, label]. CLI: python -m vintagebench.tasks --build |
  --base-rates
- models.py: ModelSpec(provider, model_id, price_in, price_out, native_tools,
  reasoning_effort, name); ModelResponse; complete(spec, messages, tools)
- episode.py: run_episode(task, agent, trial, root) -> EpisodeRecord;
  run_probe(task, agent, root) -> ProbeRecord
- grader.py: grade(task, record, root) -> Scores; grade_probe; summarize(scores)
- sanity.py: §4.5, same call interface as a model
- run.py: §4.6

## 6. Subagent roles (each edits only owned files + own tests)
- data-engineer: data.py, data/, scripts/fetch_data.py
- task-designer: tasks.py, tasks/
- harness-engineer: models.py, episode.py, grader.py, sanity.py, run.py, config/
- reviewer (read/run only): recomputes gold answers and base rates from raw vintages,
  checks leakage logic and sanity-agent scores, checks every claim in docs against
  results files. Reports issues; does not edit.

## 7. Run (v1)
- Configs: OpenAI frontier and small model, each with reasoning off and on (4 configs).
  Open-weight model: planned milestone, not in this run.
- Order: sanity agents -> smoke test (1 task x 1 trial per config) -> projected cost ->
  full run (45 tasks x 3 trials; 2 trials, then drop frontier reasoning-on, if the
  projection exceeds $8) + memorization probe. Budget cap $10.

## 8. v0 (retired)
v0 used ALFRED/FRED vintages of PAYEMS, GDPC1, PCEPI, INDPRO, UNRATE with 20/60 tasks.
FRED's terms prohibit storing/caching FRED content and using the API in connection with
ML/LLM development, so all v0 data, tasks with values and run caches were removed;
results/PILOT.md keeps v0 aggregate metrics only.
