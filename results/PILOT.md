# VintageBench pilot results

Run date: 2026-10-30. Full run: `runs/20261030-210632/` (120 episodes). Smoke test:
`runs/20261030-210602/`. Sanity agents: `runs/20261030-210554/`. All numbers below were
recomputed from `results.jsonl` (answers, golds, leakage against the parquet vintages)
by a separate script. They agree with the harness's per-episode scores and with
`summary.md` in every cell.

## 1. Setup

| | |
|---|---|
| Models | `gpt-6-sol` (OpenAI, frontier) and `gpt-6-luna` (OpenAI, small/cheap), via Chat Completions |
| Settings | temperature 0, `reasoning_effort: "none"`, max 2048 output tokens per call, native tool calling (`get_series`) |
| Prices (USD per 1M tokens, in / out) | gpt-6-sol 2.00 / 10.00; gpt-6-luna 0.10 / 0.50 (`config/models.yaml`) |
| Tasks | `tasks/pilot.jsonl`: 20 yes/no tasks, 10 flips and 10 controls (2 of them UNRATE); 5/5/5/5 on flips × as-of answer; gold Yes share 10/20 (50%) both as of and revised |
| Trials | 3 per task per model, 60 episodes per model, 120 in all |
| Order | sanity agents (free), then smoke test (1 task × 1 trial per model), then full run |
| Budget cap | $10 |

**Spend.** Actual API spend for the pilot was **$0.5274**: $0.0081 for the smoke test
plus $0.5193 of new spend in the full run. The full run's Cost column below also
totals $0.5274 (gpt-6-sol $0.5029, gpt-6-luna $0.0245). That is because it counts the
cost recorded on every episode, including the 2 smoke-test episodes
(`gdpc1-growth-above-2-2016-01`, trial 1) that the full run replayed from the response
cache at no new cost. The sanity agents cost $0.

**Deviation from SPEC §7.** SPEC §7 calls for 3 models, including one open-weight model
served by Together. The pilot ran only the 2 OpenAI models: the Together open-weight
model was skipped at the user's request; no Together API key was configured. The plain-text
tool protocol (for models without native tools) was therefore not exercised against a
live model in this pilot.

**Prices are unverified.** They come from search-result summaries of OpenAI's
documentation, because the pricing pages could not be fetched directly. Costs scale
linearly with these prices.

## 2. Per-model results

Counts are episodes (n = 60 per agent: 30 flip episodes, 30 control episodes), except
pass^3, which counts tasks (n = 20). pass^3 counts a task only if all 3 trials were
asof_correct. Brier is the mean of (turn-1 confidence − asof_correct)², so lower is better.

| Agent | asof_correct | revised_correct | update_correct (flips) | update_correct (controls) | Leakage | Brier | pass^3 (asof) | Cost (USD) |
|---|---|---|---|---|---|---|---|---|
| openai/gpt-6-sol | 60/60 (100%) | 59/60 (98%) | 29/30 (97%) | 30/30 (100%) | 0/60 (0%) | 0.000 | 20/20 (100%) | 0.5029 |
| openai/gpt-6-luna | 42/60 (70%) | 50/60 (83%) | 18/30 (60%) | 25/30 (83%) | 0/60 (0%) | 0.299 | 12/20 (60%) | 0.0245 |
| *Reference (no API)* | | | | | | | | |
| majority class (50% Yes) | 30/60 (50%) | 30/60 (50%) | – | – | – | – | 10/20 (50%) | 0 |
| sanity: oracle | 60/60 (100%) | 60/60 (100%) | 30/30 (100%) | 30/30 (100%) | 0/60 (0%) | 0.000 | 20/20 (100%) | 0 |
| sanity: always_yes | 30/60 (50%) | 30/60 (50%) | 0/30 (0%) | 30/30 (100%) | 0/60 (0%) | 0.250 | 10/20 (50%) | 0 |
| sanity: leaker | 30/60 (50%) | 60/60 (100%) | 0/30 (0%) | 30/30 (100%) | 60/60 (100%) | 0.500 | 10/20 (50%) | 0 |
| sanity: never_update | 60/60 (100%) | 30/60 (50%) | 0/30 (0%) | 30/30 (100%) | 0/60 (0%) | 0.000 | 20/20 (100%) | 0 |

The majority-class baseline is 10/20 (50%) per task for both the as-of and revised
golds; the row shows it at episode scale. The sanity agents behave as SPEC §4 expects:
the oracle is perfect, always_yes scores the 50% Yes share, the leaker is flagged on
every episode, and never_update gets update_correct only on controls.

**How update_correct is defined.** Per SPEC §4, update_correct compares the model's
self-reported turn-2 `changed` flag with the task's `flips`. In 7 of gpt-6-luna's 60
episodes, `changed` disagrees with whether its turn-1 and turn-2 answers actually
differ (gpt-6-sol: 0 of 60). Defining "changed" as "the two answers differ" would give
gpt-6-luna 20/30 (67%) on flips and 24/30 (80%) on controls, and leave gpt-6-sol
unchanged.

Other diagnostics (from `summary.md`): every turn-1 and turn-2 reply parsed as JSON
(120/120), and every tool call returned data. gpt-6-sol averaged 2.5 tool calls per
episode and gpt-6-luna 2.0.

## 3. Failure examples

All three are real episodes from `runs/20261030-210632/results.jsonl`. Quotes are verbatim.

### 3.1 gpt-6-sol, `gdpc1-growth-above-2-2018-10`, trial 3: missed update on a flip

- **Question:** Did real GDP grow faster than 2% (annualized) in Q4 2018 (GDPC1, Q3→Q4 2018)?
- **Gold:** as of 2019-02-28 **Yes** (2.59%); revised as of 2020-03-26 **No** (1.09%). This is a flip.
- **Values used:** as-of 2018-07-01 = 18664.973 and 2018-10-01 = 18784.632; revised 18732.72 and 18783.548.
- **Model:** turn 1 answered "yes" (confidence 0.99), which is correct. Turn 2 answered
  **"yes"**, with `changed: false` and confidence 0.99. Its stated reason was: *"Revised
  GDPC1 levels for Q3 and Q4 2018 imply approximately 1.09% annualized growth, below
  2.0%."*
- **Why wrong:** the arithmetic and the conclusion in the reason are right, but the answer
  field and the `changed` flag contradict them. This is gpt-6-sol's only failure in 60
  episodes. Trials 1 and 2 of the same task answered "no" with `changed: true`.
  gpt-6-luna made the same slip on this task in trial 2 ("…approximately 1.09%, below
  2.0%, so the conclusion changes from yes to no", but it answered "yes" with
  `changed: false`).

### 3.2 gpt-6-luna, `pcepi-yoy-above-2.5-2018-10`, trials 1–3: wrong as-of answer, then an update on a control

- **Question:** Is PCE inflation (year over year) above 2.5% for October 2018 (PCEPI)?
- **Gold:** as of 2018-11-29 **No** (1.98%); revised as of 2019-12-20 **No** (2.04%). This is a control.
- **Values used:** 2017-10-01 = 106.664 and 2018-10-01 = 108.772; revised 106.538 and 108.71.
- **Model, turn 1:** answered **"yes"** with confidence 1 in all 3 trials. Its caveat
  was: *"The 12-month increase is approximately 1.98%, which is below 2.5%."* (trial 1;
  trials 2–3 near-identical)
- **Model, turn 2:** answered "no" with `changed: true` in all 3 trials. Its reason was:
  *"…the October 2017–October 2018 increase is about 2.04%, below 2.5%."* (trial 1;
  trials 2–3 near-identical)
- **Why wrong:** the turn-1 answer contradicts the model's own calculation. Turn 2 then
  "corrects" it, and that counts as an unnecessary update on a control, even though the
  data did not change the conclusion. This control is one of the easiest in the set: it
  is about 0.5pp from the threshold in both vintages. It cost gpt-6-luna 3 asof_correct
  episodes, 3 update_correct episodes and a pass^3 task.

### 3.3 gpt-6-luna, `payems-weakest-12m-2021-12`, trials 1–3: a genuine reasoning error

- **Question:** Was December 2021 the weakest of the 12 months ending in December 2021
  for payroll growth (PAYEMS monthly change below each of January–November 2021)?
- **Gold:** as of 2022-01-07 **Yes**. December's change was +199k, and the smallest of
  the prior 11 months was +233k (January). Revised as of 2023-02-03 **No**: December was
  +569k against a minimum of +286k (April). This is a flip.
- **Values used:** all 13 levels from 2020-12-01 to 2021-12-01, for example
  2021-11-01 = 148752 and 2021-12-01 = 148951 as of; 149173 and 149742 revised.
- **Model, turn 1:** answered **"no"** with confidence 1 in all 3 trials. Its caveat
  was: *"December's increase was 199 thousand jobs; November's was 249 thousand, so
  December was not the weakest month."*
- **Model, turn 2:** answered "no" (correct) with `changed: false`.
- **Why wrong:** this is the only wrong yes/no answer in the pilot whose label agrees
  with the model's own text. The reasoning itself is wrong: December (199k) is below November
  (249k) and below every other month, yet the model concludes it was "not the weakest".
  It therefore misses the as-of Yes and reports no change on a task that flips. In
  trial 1, turn 2 also shows confused arithmetic: *"…greater than November's 614?
  Actually December is lower than November…"*.

## 4. Findings

- **Most errors are the answer field contradicting the model's own calculation, not
  wrong reasoning about vintages.** All 11 wrong turn-2 answers (gpt-6-luna 10, gpt-6-sol 1)
  and 15 of gpt-6-luna's 18 turn-1 errors fit this pattern: the caveats or reason state
  a figure on the correct side of the threshold, but `answer` says the opposite. Some
  replies correct themselves mid-text, for example *"Wait, using the specified formula
  it is approximately 1.06%, so it is not above 2.0%"* next to `"answer": "yes"`. The
  only other wrong answers are the 3 turn-1 answers in the 3 trials of `payems-weakest-12m-2021-12` (§3.3).
  So 15 of gpt-6-luna's 18 turn-1 errors are such slips. We hypothesize that the reply
  schema, which puts `answer` first, likely contributed: with reasoning off, the model
  may commit to a label before it does the arithmetic in `caveats`/`reason`. The pilot
  did not test this.
- **gpt-6-sol is at or near the ceiling on this set.** It scored 60/60 asof_correct and
  20/20 pass^3, and its single error was the label slip in §3.1. With 20 tasks, the
  pilot cannot separate it from the oracle.
- **gpt-6-luna's errors cluster by template, though the counts are small.** It was
  perfect on INDPRO (12/12 on all three correctness metrics, 4 tasks), UNRATE (6/6,
  2 tasks), GDP shrink (3/3) and payrolls above 100k (6/6). It was weak on PCE YoY
  (asof 4/12, revised 6/12, update 3/12; 4 tasks) and GDP growth above 2% (asof 7/12;
  4 tasks). By flip direction, its revised_correct was 6/15 on No→Yes flips versus 14/15
  on Yes→No flips. However, the No→Yes group holds the two PCE flips and two GDP-growth
  flips where its label slips concentrate, so this is not evidence of a directional bias.
- **gpt-6-luna is overconfident.** Its mean confidence on its 18 wrong turn-1 answers
  was 0.998 (it stated 1.0 in 52 of 60 episodes). gpt-6-sol's calibration cannot be
  assessed, because it made no turn-1 errors. Turn-1 confidence was 0.99–1.0 in all 120
  episodes, so Brier mostly tracks accuracy.
  gpt-6-luna's 0.299 is worse than the 0.250 of always_yes at a constant 0.5.
- **Trials at temperature 0 are not independent, but they do differ.** gpt-6-luna gave
  the same (turn-1 answer, turn-2 answer, `changed`) triple in all 3 trials on 13 of 20
  tasks (gpt-6-sol 19 of 20). For example, on `gdpc1-growth-above-2-2016-04` gpt-6-luna's
  turn-1 answers were no/yes/yes. pass^3 is informative, but 3 trials are much less
  than 3 independent samples.
- **No leakage was detected (0/120), which is weak evidence.** All 372 `values_used`
  entries equal the values the tool returned in turn 1: the models copied tool
  output. The leakage check flags only a reported value that matches a later vintage and
  not the as-of one. It would miss a memorized revised figure that shaped the answer
  without being reported, and it cannot detect memorization at all when the model
  reports the tool's values.

## 5. Limitations

- **Small n.** 20 tasks × 3 trials, with 10 flips and 10 controls, 2–5 tasks per series
  and 1–4 per template. One task (3 episodes) is 5 points of a 60-episode metric and 10
  points of a 30-episode flip or control metric. No confidence intervals are reported. Treat
  differences of a few episodes as noise.
- **2 models instead of 3.** No open-weight or Together model was run, and the
  plain-text tool protocol was not tested against a live model.
- **Reasoning off.** `reasoning_effort: "none"` was used to keep temperature 0 and
  native tools. We hypothesize that this, combined with the answer-first schema, likely
  contributed to the label slips that dominate the errors (untested). **Recommendation for the next run:** add a
  `calculation`/`reasoning` field *before* `answer` in both reply schemas (turn 1 and
  turn 2), and/or run a reasoning-enabled configuration. Report label/text
  contradictions as a separate diagnostic.
- **Unverified prices.** Costs use prices taken from search summaries of OpenAI's docs
  that could not be fetched directly. Token counts are measured; dollar figures may be off.
- **Memorization of revised figures.** The tasks are 2016–2025 US macro data that are
  likely in training data. The leakage metric only catches reported values (see §4), so
  memorization cannot be ruled out. Both models used the tool values throughout.
- **update_correct relies on the self-reported `changed` flag** (SPEC §4). It disagrees
  with the actual answer change in 7 gpt-6-luna episodes (§2). It also penalizes a model
  that fixes a wrong turn-1 answer on a control (§3.2), so update_correct is not
  independent of asof_correct.
- **Control difficulty is uneven.** The 2 UNRATE controls are not revised at all at 0.1
  precision (+0.2pp and −0.2pp in both vintages), and both models scored 6/6 on them.
  Several other controls are far from their thresholds:
  - `gdpc1-growth-above-2-2016-01` is 7.3 and 5.8 margins away (as of / revised; cap 10).
  - `pcepi-yoy-above-2.5-2018-10` is 10.5 and 9.2 margins away (cap 10). It is kept
    because the cap excludes a control only if it exceeds the cap in both vintages.
  - `payems-avg3m-above-100k-2019-03` is 80.3 and 39.0 margins away (cap 40).
  - `indpro-mom-fall-2017-08` is 18.0 and 8.2 margins away (cap 10).

  None of these listed controls is close to its threshold, so they test arithmetic more
  than judgement about revisions. Other controls are close in at least one vintage
  (distance in margins, as of / revised):
  - `gdpc1-qoq-shrink-2025-01`: 1.38 / 3.25.
  - `payems-avg3m-above-150k-2019-08`: 5.67 as of.
  - `pcepi-yoy-above-2.5-2024-08`: 1.74 revised.
  - `indpro-mom-fall-2020-02`: 2.05 revised.
- **Questions spell out the formula and the turn-2 prompt invites a re-check.** The task
  is mostly arithmetic on tool-served data. The models are not asked to anticipate
  revisions or to hedge on provisional data, and the "Re-check your conclusion" prompt
  itself hints that something may have changed.
- **Single seed, single task draw.** The tasks are one seeded draw (`seed=0`). Template
  coverage is uneven: 1 GDP-shrink task, 1 payrolls-above-150k task, 0 flips for GDP
  shrink.
