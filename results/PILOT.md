# VintageBench pilot results (v1, RTDSM)

Run `runs/20261102-015654/` (local only; see "Reproduce"). It covers 45 tasks, 4 model
configs and 3 trials, so 135 episodes per config and 540 in all, plus a memorization
probe of 45 calls per config. Data: Philadelphia Fed Real-Time Data Set for
Macroeconomists (data/NOTICE.md). All numbers are aggregates; no data values are
quoted (SPEC §2.3).

## 1. Setup

| | |
|---|---|
| Configs | `gpt-6-sol` (OpenAI frontier) and `gpt-6-luna` (OpenAI small), each with `reasoning_effort` "none" (temperature 0) and "medium" (temperature omitted); plain-text JSON tool protocol for all 4 (SPEC §4) |
| Tasks | `tasks/v1.jsonl`: 20 flips (the first-release conclusion differs from the latest vintage), 20 controls, 5 no-change (turn-2 data identical); as-of Yes 10/10, 10/10, 3/2 by kind; 23/45 Yes overall |
| Series | EMPLOY (payrolls), ROUTPUT (real GDP), IPT (industrial production), RUC (unemployment rate), PCPI (CPI; substitute for PCE) |
| Protocol | Turn 1: as-of date, `get_series` tool, reply `{calculation, answer, confidence, survival_prob, values_used, caveats}`. Turn 2: "Today is <revision_date>. Here is the latest data. Answer the question." plus the turn-1 requests re-served from the revision vintage. Probe: no tools; asks for the key observations from memory |
| Order | sanity agents (pass) → smoke test (1 task × 1 trial per config, run once with `low` reasoning and once with `medium`) → cost projection ($2.66, under the $8 threshold, so 3 trials and all 4 configs) → full run + probe |
| Spend | **$2.83 total** (cumulative ledger: $0.04 for smoke tests, $2.80 for the full run). Cap $10 |

`reasoning_effort: "low"` was smoke-tested first. It produced 31 reasoning tokens on
`gpt-6-sol`, so "medium" was used as the reasoning-on setting. In the full run,
reasoning-on averaged 150 (`gpt-6-sol`) and 245 (`gpt-6-luna`) reasoning tokens per
episode.

## 2. Base rate: how often first-release conclusions flip

From `tasks/BASE_RATES.md`. These are counts over every candidate instance of the 8
templates (2016–2025), before any selection. They come from data, not models.

| Comparison | All instances | Material in both vintages | Material, COVID windows excluded |
|---|---|---|---|
| first release vs latest vintage | 120/1235 (9.7%) | 88/1141 (7.7%) | 82/938 (8.7%) |
| first release vs one year later | 90/1235 (7.3%) | 67/1158 (5.8%) | 60/954 (6.3%) |

By series (first release vs latest, all instances): EMPLOY 51/348 (14.7%), IPT 18/116
(15.5%), RUC 17/115 (14.8%), ROUTPUT 7/76 (9.2%), PCPI 27/580 (4.7%). Once
immaterial (near-threshold) instances are removed, PCPI drops to 3/505 (0.6%). The
highest template rate is payroll 3-month average above 150k: 23/116 (19.8%).

So roughly 1 in 10 yes/no conclusions drawn from first-release data comes out
differently on the latest data. The task set over-samples flips (20/45) by design, so
survival on the tasks (75/135 episodes per config) is not the population rate.

## 3. survival_prob calibration

Turn 1 asks for the "probability (0-1) that this conclusion still holds after the data
is fully revised". survived = (turn-1 answer == gold on the revision vintage). AUC is
the probability that a random non-flip episode gets a higher survival_prob than a
random flip episode (0.5 = no discrimination).

| Config | Mean survival_prob, flips | Mean survival_prob, non-flips | AUC | Flip episodes with survival_prob ≥ 0.8 | Survival Brier |
|---|---|---|---|---|---|
| gpt-6-sol / off | 0.85 (n=60) | 0.88 (n=75) | 0.61 | 48/60 (80%) | 0.339 |
| gpt-6-sol / medium | 0.85 (n=60) | 0.89 (n=75) | 0.58 | 45/60 (75%) | 0.343 |
| gpt-6-luna / off | 0.86 (n=60) | 0.95 (n=75) | 0.64 | 53/60 (88%) | 0.424 |
| gpt-6-luna / medium | 0.91 (n=59) | 0.93 (n=74) | 0.60 | 54/59 (92%) | 0.374 |

- **The models' average survival_prob is near the population base rate, but it barely
  separates the conclusions that will flip from those that won't.** Mean survival_prob
  over all episodes is 0.86 to 0.92, close to the 90% survival implied by §2. On flips,
  though, it stays at 0.85 to 0.91, and the AUC is 0.58 to 0.64.
- **No config ever gave a flip survival_prob below 0.5**, except `gpt-6-luna` with
  reasoning off: 6 of 60 flip episodes. In all 6, its turn-1 reply says the data
  needed were not returned.
- **The reliability bins are not monotone.** For `gpt-6-sol` / off, empirical survival
  was 14/26 (54%) in [0.5, 0.8), 24/57 (42%) in [0.8, 0.95) and 37/52 (71%) in
  [0.95, 1].
- **Series-level priors partly track the base rates.** PCPI, the lowest-revision
  series in §2, gets mean survival_prob 0.94–0.97, the highest in 3 of 4 configs. But RUC gets
  0.91–0.98, although its first-release conclusions flip in 17/115 (14.8%) instances.
- **Reasoning on did not improve calibration.** AUC fell from 0.61 to 0.58
  (`gpt-6-sol`) and from 0.64 to 0.60 (`gpt-6-luna`).

## 4. Memorization probe (no tools)

Each config was asked from memory for the key observations of each task. That is 96
values per config: levels for EMPLOY, RUC and PCPI, and the deciding growth rate for
ROUTPUT and IPT. A recall matches a vintage if it is within half a published unit. 81
of the 96 values differ between first release and latest vintage (distinguishable).
The counts below are over those 81.

| Config | first release | latest | neither | no answer |
|---|---|---|---|---|
| gpt-6-sol / off | 20 (25%) | 1 (1%) | 32 (40%) | 28 (35%) |
| gpt-6-sol / medium | 23 (28%) | 8 (10%) | 35 (43%) | 15 (19%) |
| gpt-6-luna / off | 14 (17%) | 4 (5%) | 60 (74%) | 3 (4%) |
| gpt-6-luna / medium | 14 (17%) | 4 (5%) | 59 (73%) | 4 (5%) |
| pooled | 71/324 (22%) | 17/324 (5%) | 186/324 (57%) | 50/324 (15%) |

- **Recall that matches a vintage matches the first release much more often than the
  latest vintage.** Pooled, that is 71 first-release matches against 17 latest. Most
  recalls match neither.
- **Most first-release matches are on low-precision quantities**: IPT month-over-month
  growth (29 of 32 IPT values) and the RUC rate (22 of 28). There a plausible guess
  can match by chance, so these matches are weak evidence of memorization.
- **On high-precision levels, exact matches are rare.** EMPLOY: 6/144 first release,
  0 latest. PCPI: 11/88 first release, 6/88 latest, all 6 latest matches from
  `gpt-6-sol` / medium.
- **The probe result is consistent with first-print values in training data**, but it
  does not show that the episodes used memory. With tools, leakage was 0/540 in both
  turns.

## 5. Accuracy and updating

| Config | asof_correct | revised_correct | update_correct (flip) | update_correct (control) | update_correct (no-change) | pass^3 (asof) | Cost (USD) |
|---|---|---|---|---|---|---|---|
| gpt-6-sol / off | 135/135 (100%) | 135/135 (100%) | 60/60 (100%) | 60/60 (100%) | 15/15 (100%) | 45/45 (100%) | 0.97 |
| gpt-6-sol / medium | 135/135 (100%) | 135/135 (100%) | 60/60 (100%) | 60/60 (100%) | 15/15 (100%) | 45/45 (100%) | 1.52 |
| gpt-6-luna / off | 109/135 (81%) | 118/135 (87%) | 41/60 (68%) | 58/60 (97%) | 15/15 (100%) | 34/45 (76%) | 0.05 |
| gpt-6-luna / medium | 133/135 (99%) | 134/135 (99%) | 59/60 (98%) | 59/60 (98%) | 15/15 (100%) | 43/45 (96%) | 0.07 |

The Cost column covers episodes only, not the probe. Sanity agents (no API) met every
SPEC §4.5 expectation:
- oracle: 135/135 on every metric, Briers 0;
- always_yes: 69/135 asof_correct;
- leaker: flagged in 123/135 turn-1 episodes;
- never_update: correct only on non-flips;
- probe recallers: 81/81 distinguishable values classified correctly.

- **`gpt-6-sol` is at ceiling with reasoning off and on.** At temperature 0 its outcome
  never varied across trials. The v1 task set does not separate it from the oracle on
  accuracy. It separates it only on survival_prob (§3).
- **`gpt-6-luna` with reasoning off mostly fails at data gathering.** 19 of its 26
  wrong turn-1 answers say the data needed were not returned. Typically it asked for
  too short a window, e.g. without the prior quarter. In 18 of those 19 it then
  answered "no" by default. Reasoning on fixes almost all of this: 26 → 2 wrong turn-1
  answers.
- **Missed updates follow from turn 1.** `gpt-6-luna` / off missed 19 of 60 flip
  updates. In 13 of them the turn-1 answer was wrong and the turn-2 answer, the same
  label, was right. In 16 of the 19 its turn-1 reply says data needed were not
  returned.

## 6. Diagnostics

| Config | Label/text contradiction turn 1 | turn 2 | Leakage t1 / t2 | Self-report `changed` agrees | Reply parse failures t1 / t2 |
|---|---|---|---|---|---|
| gpt-6-sol / off | 0/135 | 0/135 | 0 / 0 | 135/135 | 0 / 0 |
| gpt-6-sol / medium | 0/135 | 0/135 | 0 / 0 | 135/135 | 0 / 0 |
| gpt-6-luna / off | 0/135 | 1/135 | 0 / 0 | 135/135 | 0 / 0 |
| gpt-6-luna / medium | 0/135 | 0/135 | 0 / 0 | 133/133 | 2 / 1 |

With `calculation` placed before `answer`, label/text contradictions all but vanished:
1 of 1080 turns. In v0, where the reply put `answer` first, label slips were the main
error source (§9). This is a before/after comparison on different tasks and data, so
it is suggestive, not a controlled test.

## 7. Failure examples

Numbers in quotes are redacted as [value] (SPEC §2.3). Questions are verbatim from
`tasks/v1.jsonl`.

1. **`gpt-6-luna` / off, `routput-gdp_shrink-2022q2` (flip; as-of Yes, revised No),
   all 3 trials.** It requested 2022 Q2–Q3 instead of Q1–Q2. Turn 1: *"…the returned
   data contain no [value] Q[value] observation. Without the prior quarter's value, I
   cannot determine whether GDP shrank in Q[value]"*. It answered "no" with
   survival_prob 0.99. In turn 2 it again answered "no", so it is marked
   revised_correct but missed the update. It is right on the revised data by default,
   not by reasoning.
2. **`gpt-6-luna` / off, `employ-payroll_avg3m_above-150k-2017-05` (flip), trial 1:
   window convention.** *"Monthly payroll gains were [value] from March to April and
   [value] from April to May. Their average is … The three-month span has two
   month-to-month changes."* It averaged two monthly changes instead of three, and
   answered wrongly.
3. **`gpt-6-sol` / off, `employ-payroll_avg3m_above-150k-2024-05` (flip; as-of Yes,
   revised No), trial 3: overconfident survival.** The turn-1 answer was correct, with
   survival_prob 0.97 and the caveat *"Seasonally adjusted figures as published by June
   [value]; subject to revision."* The turn-2 update was correct: *"The revised data
   show a lower three-month average than the figures available in June [value]"*. The
   model knows payrolls get revised, but it put 0.97 on a conclusion with a 19.8%
   template base rate of flipping (§2), and the conclusion did flip.

## 8. Limitations

- **Small n.** 45 tasks × 3 trials. At temperature 0 the trials are nearly
  deterministic (`gpt-6-sol`: no task varied; `gpt-6-luna`: 8 tasks off, 2 tasks on),
  so the effective sample is closer to 45 tasks. No confidence intervals are reported.
  One task is 3 episodes, about 5 points of a flip or control metric.
- **The flip pool is thin.** 82 flip-eligible candidates after the filters (12 IPT, 7
  ROUTPUT, 3 PCPI). All 5 RUC flips are rounding-boundary flips (unchanged ↔ +0.1 pp),
  the smallest possible revision.
- **Ceiling on accuracy.** The frontier model makes no accuracy errors. Without
  formula-spelled questions the set still mostly tests data gathering and arithmetic,
  and separates models only on calibration (§3).
- **Survival outcome definition.** survived is scored against the pinned latest vintage
  (September/October 2026), which is not final for recent periods.
- **Vintage dates.** EMPLOY, IPT and PCPI vintages are dated at month end, a
  conservative choice that never leaks but can lag the actual release by up to about 4
  weeks. One delayed release (ROUTPUT19M2) needed a manual override (data/README.md).
- **Memorization probe.** Matches on low-precision quantities (IPT growth, RUC) can be
  chance. The probe asks about isolated values, not whether memory influenced the
  episodes. Leakage only catches reported values.
- **Only 2 OpenAI models, one provider and one protocol.** No open-weight model: that
  is a planned milestone. All configs used the plain-text tool protocol, because GPT-6
  native function calling requires reasoning off.
- **Prices** come from OpenAI's model pages as fetched on 2026-11-01. Token counts are
  measured.
- **Data not redistributed.** Per-episode results and the response cache contain data
  values and are not committed. The reviewer recomputed these numbers locally from
  `results.jsonl`.

## 9. v0 (retired prototype on ALFRED; aggregate metrics only)

v0 used ALFRED/FRED vintages, since removed (SPEC §8), so its results cannot be
rechecked here. There were 60 tasks whose questions spelled out the formula, reasoning
off and 3 trials. `gpt-6-sol` scored asof_correct 180/180 (100%) and flip
update_correct 89/90 (99%). `gpt-6-luna` scored 141/180 (78%) and 65/90 (72%), and 30
of its 39 wrong turn-1 answers were labels that contradicted its own calculation. The
lesson: frontier models ace formula-spelled questions, so v1 asks plain questions and
adds survival_prob and the memorization probe to test judgement about revisions.

## Reproduce

```bash
python scripts/fetch_data.py
python -m vintagebench.run --tasks tasks/v1.jsonl --sanity --probe
python -m vintagebench.run --models config/models.yaml --tasks tasks/v1.jsonl --trials 1 --limit 1 --probe
python -m vintagebench.run --models config/models.yaml --tasks tasks/v1.jsonl --trials 3 --probe
```

The full run was graded once and then re-graded from the response cache at no cost,
after grader-only fixes (probe tolerance, the contradiction regex and leakage decimals)
that left prompts unchanged.
