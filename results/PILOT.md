# VintageBench pilot results

Two runs on the same 2 models:

- **20-task pilot** (2026-10-30). Full run in `runs/20261030-210632/` (120 episodes),
  smoke test in `runs/20261030-210602/`, sanity agents in `runs/20261030-210554/`.
- **60-task set** (2026-10-31). Full run in `runs/20261031-041615/` (360 episodes),
  sanity agents in `runs/20261031-041250/`. The 60 tasks are the 20 pilot tasks plus 40
  new ones.

All numbers below were recomputed from `results.jsonl` by a separate script (answers,
golds, and leakage against the parquet vintages). They agree with the harness's
per-episode scores and with `summary.md` in every cell.

## 1. Setup

| | |
|---|---|
| Models | `gpt-6-sol` (OpenAI, frontier) and `gpt-6-luna` (OpenAI, small/cheap), via Chat Completions |
| Settings | temperature 0, `reasoning_effort: "none"`, max 2048 output tokens per call, native tool calling (`get_series`) |
| Prices (USD per 1M tokens, in / out) | gpt-6-sol 2.00 / 10.00; gpt-6-luna 0.10 / 0.50 (`config/models.yaml`) |
| Tasks (pilot) | `tasks/pilot.jsonl`: 20 yes/no tasks, 10 flips and 10 controls (2 of them UNRATE); 5/5/5/5 on flips × as-of answer; gold Yes share 10/20 (50%) both as of and revised |
| Tasks (60-task set) | `tasks/pilot60.jsonl` ([tasks/README60.md](../tasks/README60.md)): the 20 pilot tasks verbatim plus 40 new tasks, 60 in all; 30 flips and 30 controls (6 UNRATE); 15/15/15/15 on flips × as-of answer; gold Yes share 30/60 (50%) both as of and revised; the 30 flips fall into 18 overlap clusters |
| Trials | 3 per task per model: 60 episodes per model (120 in all) on the pilot, 180 per model (360 in all) on the 60-task set |
| Order | sanity agents (free), then smoke test (1 task × 1 trial per model), then full 20-task run; later, sanity agents on 60, then the full 60-task run |
| Budget cap | $10 |

**Spend.** Total actual API spend for both runs was about **$1.53** ($0.5274 + $1.0012
= $1.5286). The sanity agents cost $0.

- **20-task run: $0.5274.** This is $0.0081 for the smoke test plus $0.5193 of new
  spend in the full run. The run's Cost column (§2) also totals $0.5274 (gpt-6-sol
  $0.5029, gpt-6-luna $0.0245). That is because it counts the cost recorded on every
  episode, including the 2 smoke-test episodes (`gdpc1-growth-above-2-2016-01`, trial 1)
  that the full run replayed from the response cache at no new cost.
- **60-task run: $1.0012 new.** This covers the 240 episodes of the 40 new tasks. The
  120 pilot-task episodes were replayed from the cache at no new cost. The run's Cost
  column (§3) totals $1.5286 (gpt-6-sol $1.4570, gpt-6-luna $0.0716). That total is the
  nominal token cost of all 360 episodes: $0.5274 for the replayed pilot episodes plus
  $1.0012 for the new ones. It is not new spend. It equals total actual spend across
  both runs only by coincidence, because the replayed episodes are exactly the ones the
  20-task run paid for.

**Deviation from SPEC §7.** SPEC §7 calls for 3 models, including one open-weight model
served by Together. Both runs used only the 2 OpenAI models: the Together open-weight
model was skipped at the user's request; no Together API key was configured. The plain-text
tool protocol (for models without native tools) was therefore not exercised against a
live model.

**Prices are unverified.** They come from search-result summaries of OpenAI's
documentation, because the pricing pages could not be fetched directly. Costs scale
linearly with these prices.

## 2. 20-task pilot: per-model results

Counts are episodes (n = 60 per agent: 30 flip episodes, 30 control episodes), except
pass^3, which counts tasks (n = 20). pass^3 counts a task only if all 3 trials were
asof_correct. Brier is the mean of (turn-1 confidence − asof_correct)², so lower is
better. gpt-6-sol's Brier is about 0.0001 (6 × 10⁻⁵) on both runs, shown as 0.000.

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

## 3. 60-task set: per-model results

Run `runs/20261031-041615/`. Counts are episodes (n = 180 per agent: 90 flip episodes,
90 control episodes), except pass^3, which counts tasks (n = 60).

| Agent | asof_correct | revised_correct | update_correct (flips) | update_correct (controls) | Leakage | Brier | pass^3 (asof) | Cost (USD) |
|---|---|---|---|---|---|---|---|---|
| openai/gpt-6-sol | 180/180 (100%) | 179/180 (99%) | 89/90 (99%) | 90/90 (100%) | 0/180 (0%) | 0.000 | 60/60 (100%) | 1.4570 |
| openai/gpt-6-luna | 141/180 (78%) | 157/180 (87%) | 65/90 (72%) | 84/90 (93%) | 0/180 (0%) | 0.216 | 41/60 (68%) | 0.0716 |
| *Reference (no API)* | | | | | | | | |
| majority class (50% Yes) | 90/180 (50%) | 90/180 (50%) | – | – | – | – | 30/60 (50%) | 0 |
| sanity: oracle | 180/180 (100%) | 180/180 (100%) | 90/90 (100%) | 90/90 (100%) | 0/180 (0%) | 0.000 | 60/60 (100%) | 0 |
| sanity: always_yes | 90/180 (50%) | 90/180 (50%) | 0/90 (0%) | 90/90 (100%) | 0/180 (0%) | 0.250 | 30/60 (50%) | 0 |
| sanity: leaker | 90/180 (50%) | 180/180 (100%) | 0/90 (0%) | 90/90 (100%) | 180/180 (100%) | 0.500 | 30/60 (50%) | 0 |
| sanity: never_update | 180/180 (100%) | 90/180 (50%) | 0/90 (0%) | 90/90 (100%) | 0/180 (0%) | 0.000 | 60/60 (100%) | 0 |

The Cost column is the recorded cost of all 360 episodes, not new spend (see §1). The
majority-class baseline is 30/60 (50%) per task for both golds. The sanity agents
(`runs/20261031-041250/`) again behave as SPEC §4 expects.

### 3.1 Pilot 20 vs new 40 within the 60-task run

| Agent | subset | asof_correct | revised_correct | update_correct (flips) | update_correct (controls) | Leakage | Brier | pass^3 (asof) | Cost (USD) |
|---|---|---|---|---|---|---|---|---|---|
| openai/gpt-6-sol | pilot 20 | 60/60 (100%) | 59/60 (98%) | 29/30 (97%) | 30/30 (100%) | 0/60 (0%) | 0.000 | 20/20 (100%) | 0.5029 |
| openai/gpt-6-sol | new 40 | 120/120 (100%) | 120/120 (100%) | 60/60 (100%) | 60/60 (100%) | 0/120 (0%) | 0.000 | 40/40 (100%) | 0.9541 |
| openai/gpt-6-luna | pilot 20 | 42/60 (70%) | 50/60 (83%) | 18/30 (60%) | 25/30 (83%) | 0/60 (0%) | 0.299 | 12/20 (60%) | 0.0245 |
| openai/gpt-6-luna | new 40 | 99/120 (82%) | 107/120 (89%) | 47/60 (78%) | 59/60 (98%) | 0/120 (0%) | 0.175 | 29/40 (72%) | 0.0471 |

The pilot-20 rows equal the 20-task table in §2 cell for cell. All 120 pilot-task
episodes in the 60-task run have the same turn-1 reply, turn-2 reply and cost as in
the 20-task run, because they were replayed from the response cache. They are
therefore not a replication. The new-40 Cost column ($0.9541 + $0.0471 = $1.0012) is
the 60-task run's new spend. gpt-6-luna does better on the new 40 than on the pilot
20, but the sets differ in composition. The new 40 has 8 INDPRO flips (where
gpt-6-luna is perfect) and 4 more UNRATE controls. They also have only 1 new PCE task, the
template where it does worst.

### 3.2 Cluster-level view of update_correct on flips

Tasks in the same series whose computation windows overlap are grouped into one
cluster (`task_clusters`). The 30 flips fall into 18 flip clusters, and each cluster is
treated as one independent unit. "All correct" counts the clusters in which every
flip episode (all member flips × 3 trials) was update_correct. "Cluster mean" averages
each cluster's share of correct flip episodes, so every cluster has equal weight.

| Agent | flip episodes update_correct | clusters all correct | cluster mean |
|---|---|---|---|
| openai/gpt-6-sol | 89/90 (99%) | 17/18 (94%) | 98% |
| openai/gpt-6-luna | 65/90 (72%) | 9/18 (50%) | 75% |

gpt-6-sol's only imperfect cluster is `GDPC1:2018-07..2018-10`, the label slip in
§5.1. Weighting by cluster barely changes gpt-6-luna's rate (75% vs 72%), but only 9
of its 18 flip clusters are fully correct. Its worst is `PCEPI:2023-01..2024-11`, with
1/6 flip episodes correct (0.17).

### 3.3 Label slips, the `changed` flag and confidence on the 60

**Label slips.** The table counts wrong answers (episodes) whose yes/no label is the
opposite of the conclusion, or of the figure, that the model's own `caveats` (turn 1)
or `reason` (turn 2) states. Each wrong answer was classified by reading its text.
"Reasoning errors" are wrong answers whose label agrees with a wrong claim in the
text, e.g. "175 thousand, lower than each of the prior 11 monthly changes" when it
was not.

| Agent | turn | wrong answers | label slips | reasoning errors |
|---|---|---|---|---|
| gpt-6-sol | 1 | 0/180 | – | – |
| gpt-6-sol | 2 | 1/180 | 1 | 0 |
| gpt-6-luna | 1 | 39/180 | 30 (pilot 20: 15, new 40: 15) | 9 (pilot 20: 3, new 40: 6) |
| gpt-6-luna | 2 | 23/180 | 20 (pilot 20: 10, new 40: 10) | 3 (pilot 20: 0, new 40: 3) |

One case is borderline: `payems-weakest-12m-2016-01`, trial 1, turn 1. Its stated
conclusion ("below each of the prior 11 monthly changes") matches its "yes" label, but
its own figures (151k vs a 149k minimum) contradict it. It is counted as a reasoning
error; counted as a slip, gpt-6-luna's turn-1 counts would be 31 slips and 8 reasoning
errors.

All 12 reasoning errors are on the `payems-weakest-12m` template:
- turn 1: 3 trials of `-2021-12`, 2 of `-2016-01`, 2 of `-2023-03`, 2 of `-2024-04`;
- turn 2: 1 trial of `-2016-01`, 2 of `-2024-04`.

Several slips repeat a pattern seen in the pilot: the caveat ends with *"Correction:
the answer is yes"* while `answer` is "no" (e.g. `payems-avg3m-above-100k-2025-04`,
trials 1 and 3).

**`changed` flag.** In 19 of gpt-6-luna's 180 episodes (7 pilot, 12 new), `changed`
disagrees with whether its turn-1 and turn-2 answers differ (gpt-6-sol: 0 of 180).
With "changed" defined as "the two answers differ", gpt-6-luna would score 64/90 (71%)
on flips and 78/90 (87%) on controls, versus the reported 65/90 and 84/90.

**Confidence.** Turn-1 confidence was 0.99–1.0 in all 360 episodes, and gpt-6-luna
stated 1.0 in 169 of 180. Its mean confidence on its 39 wrong turn-1 answers was 0.999.
gpt-6-sol made no turn-1 errors, so its calibration cannot be assessed. gpt-6-luna's
Brier of 0.216 is slightly better than always_yes (0.250) on the 60, because its
accuracy is higher; it was worse on the pilot (0.299).

**Other diagnostics** (`summary.md`): every reply parsed as JSON (360/360 per turn) and
every tool call returned data. All 1042 `values_used` entries equal the values the tool
returned in turn 1. On the 60 tasks, gpt-6-luna gave the same (turn-1 answer, turn-2
answer, `changed`) triple in all 3 trials on 40 tasks, and gpt-6-sol on 59.

## 4. Phase 4 decision gate

The set counts as **SATURATED** if every model scores ≥ 90% on asof_correct AND on
update_correct (flips and controls pooled), AND has leakage == 0.

| Run | Agent | asof_correct | update_correct | Leakage | ≥ 90% / 0 leakage? |
|---|---|---|---|---|---|
| 20-task | gpt-6-sol | 60/60 (100%) | 59/60 (98%) | 0/60 | yes |
| 20-task | gpt-6-luna | 42/60 (70%) | 43/60 (72%) | 0/60 | **no** (asof, update) |
| 60-task | gpt-6-sol | 180/180 (100%) | 179/180 (99%) | 0/180 | yes |
| 60-task | gpt-6-luna | 141/180 (78%) | 149/180 (83%) | 0/180 | **no** (asof, update) |

**Verdict: NOT SATURATED on either run.** gpt-6-luna is below 90% on both asof_correct
and update_correct. That is why the 20-task pilot was expanded to 60. On the 60 it
is still below 90% on both. gpt-6-sol alone clears the gate on both runs and is at the
ceiling. The set therefore separates the two models, but it does not challenge the
frontier model. Most of gpt-6-luna's shortfall is label slips (§3.3) rather than
vintage reasoning, so the gate result says little about vintage reasoning itself.

## 5. Failure examples

These three come from the 20-task run, `runs/20261030-210632/results.jsonl`. The same
episodes appear unchanged in the 60-task run, because they were replayed from the cache.
Quotes are verbatim.

### 5.1 gpt-6-sol, `gdpc1-growth-above-2-2018-10`, trial 3: missed update on a flip

- **Question:** Did real GDP grow faster than 2% (annualized) in Q4 2018 (GDPC1, Q3→Q4 2018)?
- **Gold:** as of 2019-02-28 **Yes** (2.59%); revised as of 2020-03-26 **No** (1.09%). This is a flip.
- **Values used:** as-of 2018-07-01 = 18664.973 and 2018-10-01 = 18784.632; revised 18732.72 and 18783.548.
- **Model:** turn 1 answered "yes" (confidence 0.99), which is correct. Turn 2 answered
  **"yes"**, with `changed: false` and confidence 0.99. Its stated reason was: *"Revised
  GDPC1 levels for Q3 and Q4 2018 imply approximately 1.09% annualized growth, below
  2.0%."*
- **Why wrong:** the arithmetic and the conclusion in the reason are right, but the answer
  field and the `changed` flag contradict them. This is gpt-6-sol's only failure in 60
  episodes, and in 180 on the 60-task set. Trials 1 and 2 of the same task answered "no" with `changed: true`.
  gpt-6-luna made the same slip on this task in trial 2 ("…approximately 1.09%, below
  2.0%, so the conclusion changes from yes to no", but it answered "yes" with
  `changed: false`).

### 5.2 gpt-6-luna, `pcepi-yoy-above-2.5-2018-10`, trials 1–3: wrong as-of answer, then an update on a control

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

### 5.3 gpt-6-luna, `payems-weakest-12m-2021-12`, trials 1–3: a genuine reasoning error

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
- **Why wrong:** this is the only wrong yes/no answer in the 20-task pilot whose label
  agrees with the model's own text. On the 60, all 12 such reasoning errors are on this
  template (§3.3). The reasoning itself is wrong: December (199k) is below November
  (249k) and below every other month, yet the model concludes it was "not the weakest".
  It therefore misses the as-of Yes and reports no change on a task that flips. In
  trial 1, turn 2 also shows confused arithmetic: *"…greater than November's 614?
  Actually December is lower than November…"*.

## 6. Findings

Counts are for the 60-task set unless marked "pilot". The pilot-20 subset of the 60 is
identical to the 20-task run.

- **Most errors are the answer field contradicting the model's own calculation, not
  wrong reasoning about vintages.**
  - gpt-6-luna: 30 of its 39 wrong turn-1 answers and 20 of its 23 wrong turn-2
    answers are label slips (pilot: 15 of 18 and 10 of 10).
  - gpt-6-sol: its only wrong answer is a slip (§5.1).
  - Some replies correct themselves mid-text but keep the wrong label, e.g. *"Wait,
    using the specified formula it is approximately 1.06%, so it is not above 2.0%"*
    next to `"answer": "yes"`.

  We hypothesize that the reply schema, which puts `answer` first, likely contributed:
  with reasoning off, the model may commit to a label before it does the arithmetic in
  `caveats`/`reason`. Neither run tested this.
- **The genuine reasoning errors are all on one template.** All 12 of gpt-6-luna's
  reasoning errors (9 turn-1, 3 turn-2) are on `payems-weakest-12m`, where it must
  compare one month with 11 others. It often compares with just one other month, or
  misstates which month was lowest (§5.3). gpt-6-luna scored asof_correct 8/18 on this template (6 tasks).
- **gpt-6-sol is at the ceiling.** It scored 180/180 asof_correct, 60/60 pass^3 and
  17/18 flip clusters fully correct, and was perfect on all 40 new tasks. Its single
  error is the pilot label slip. These tasks cannot separate it from the oracle.
- **gpt-6-luna's errors cluster by template; the counts are larger than in the pilot
  but still small.**
  - Perfect on INDPRO: 51/51 on all three correctness metrics, 17 tasks including 10
    flips.
  - Also perfect on UNRATE (18/18, 6 tasks) and GDP shrink (9/9, 3 tasks).
  - Weakest on PCE YoY (asof 5/15, 5 tasks), payrolls weakest-of-12 (asof 8/18) and
    GDP growth above 2% (asof 13/21, 7 tasks).
  - By flip direction, its revised_correct was 30/45 on No→Yes flips versus 40/45 on
    Yes→No. This is confounded with template, so it is not evidence of a directional
    bias.
- **gpt-6-luna is overconfident.** Its mean confidence on its 39 wrong turn-1 answers
  was 0.999, and it stated 1.0 in 169 of 180 episodes. gpt-6-sol's calibration cannot
  be assessed, because it made no turn-1 errors. Brier mostly tracks accuracy.
- **Trials at temperature 0 are not independent, but they do differ.** gpt-6-luna gave
  the same triple in all 3 trials on 40 of 60 tasks, and gpt-6-sol on 59 of 60. pass^3
  is informative, but 3 trials are much less than 3 independent samples.
- **No leakage was detected (0/360), which is weak evidence.** All 1042 `values_used`
  entries equal the values the tool returned in turn 1: the models copied tool
  output. The leakage check flags only a reported value that matches a later vintage and
  not the as-of one. It cannot detect a memorized revised figure that shaped the answer
  without being reported.

## 7. Limitations

- **n is still small.**
  - 60 tasks × 3 trials, with 30 flips that form only 18 effective flip clusters.
  - The pilot 20 inside the 60 are cache replays, so they add no new samples.
  - The 60-task set has 5–22 tasks per series and 3–17 per template; the pilot had
    2–5 per series and 1–4 per template.
  - No confidence intervals are reported. On the 60, one task (3 episodes) is about 2
    points of a 180-episode metric and about 3 points of a 90-episode flip or control
    metric.
- **The flip pool is exhausted, and the flips are PAYEMS-heavy.**
  - The eligible flips for `gdpc1-growth-above-2` (3), `indpro-mom-fall` (11, 10
    with the revision gap) and `pcepi-yoy-above-2.5` (2) are effectively all used.
  - There are no GDP-shrink flips at all, and UNRATE flips are never drawn.
  - Of the 30 flips, 15 are PAYEMS and 10 INDPRO. Of the 20 new flips, 12 are PAYEMS,
    8 INDPRO, and 11 target 2024–2025.
  - Overlapping payroll windows make several flips near-duplicates. One cluster
    (`PAYEMS:2024-09..2025-06`) holds 5 flips.
  - Growing the set further will need new templates or series, not more draws.
- **2 models instead of 3.** The Together open-weight model was skipped at the user's
  request, and no Together API key was configured. The plain-text tool protocol was
  not tested against a live model.
- **Reasoning off.** `reasoning_effort: "none"` was used to keep temperature 0 and
  native tools. We hypothesize that this, combined with the answer-first schema, likely
  contributed to the label slips that dominate the errors (untested).
  **Recommendation for the next run:**
  - add a `calculation`/`reasoning` field *before* `answer` in both reply schemas
    (turn 1 and turn 2), and/or run a reasoning-enabled configuration;
  - report label/text contradictions as a separate diagnostic.
- **Unverified prices.** Costs use prices taken from search summaries of OpenAI's docs
  that could not be fetched directly. Token counts are measured; dollar figures may be off.
- **Memorization of revised figures.** The tasks are 2016–2025 US macro data that are
  likely in training data. The leakage metric only catches reported values (see §6), so
  memorization cannot be ruled out. Both models used the tool values throughout.
- **update_correct relies on the self-reported `changed` flag** (SPEC §4).
  - It disagrees with the actual answer change in 19 gpt-6-luna episodes on the 60
    (§3.3).
  - It also penalizes a model that fixes a wrong turn-1 answer on a control (§5.2), so
    update_correct is not independent of asof_correct.
- **Control difficulty is uneven.**
  - **UNRATE controls are easy.** The 6 UNRATE controls are compared at 0.1
    precision, and both models scored 18/18 on them. The 2 pilot UNRATE controls are
    not revised at all (+0.2pp and −0.2pp in both vintages).
  - **Some controls are easy on the as-of side.** The cap excludes a control only if
    it exceeds the cap in both vintages, so a kept control can be far from its
    threshold as of its first release. tasks/README60.md lists 7 controls whose as-of
    distance is more than 2× the cap or more than 20 margins, e.g.:
    - `payems-avg3m-above-100k-2019-03`: 80.3 / 39.0, cap 40;
    - `payems-weakest-12m-2016-01`: 67.0 / 40.0, cap 40.
  - **More pilot controls far from their threshold:**
    - `gdpc1-growth-above-2-2016-01`: 7.3 / 5.8, cap 10;
    - `pcepi-yoy-above-2.5-2018-10`: 10.5 / 9.2, cap 10;
    - `indpro-mom-fall-2017-08`: 18.0 / 8.2, cap 10.

    These test arithmetic more than judgement about revisions.
  - **Other pilot controls are close in at least one vintage** (margins, as of /
    revised):
    - `gdpc1-qoq-shrink-2025-01`: 1.38 / 3.25;
    - `payems-avg3m-above-150k-2019-08`: 5.67 as of;
    - `pcepi-yoy-above-2.5-2024-08`: 1.74 revised;
    - `indpro-mom-fall-2020-02`: 2.05 revised.
- **Questions spell out the formula and the turn-2 prompt invites a re-check.** The task
  is mostly arithmetic on tool-served data. The models are not asked to anticipate
  revisions or to hedge on provisional data, and the "Re-check your conclusion" prompt
  itself hints that something may have changed.
- **Single seed, single task draw.** Both task sets are one seeded draw (`seed=0`), and
  the new 40 were picked to minimise window overlap with already-chosen tasks. The new 40 differ in
  composition from the pilot 20 (§3.1), so the pilot-vs-new comparison is not like for
  like.
