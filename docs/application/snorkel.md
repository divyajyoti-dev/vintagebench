# Snorkel application draft: VintageBench

DRAFT. Do not merge. Every pilot number comes from `results/PILOT.md` and
`tasks/BASE_RATES.md` (v1, Philadelphia Fed RTDSM data). Word counts are listed at the
end and printed by `python docs/application/wordcount.py`.

## Artifact

VintageBench (github.com/divyajyoti-dev/vintagebench-release) is an open benchmark and
harness. It tests whether AI analyst agents reason correctly about provisional
economic data that are later revised. Dated vintages from the Philadelphia Fed
Real-Time Data Set for Macroeconomists are served through a tool. Gold answers are
computed by code, grading is deterministic, and it ships with sanity agents, a
memorization probe and base-rate tables.

Alternative version: ANLP-ESG, a public NLP pipeline for ESG report PDFs. It does
layout-aware extraction with OCR fallback; topic modeling with LDA, NMF and BERTopic;
and claim/evidence detection with a 350-sentence adjudicated gold set, Cohen's kappa
and a DistilBERT classifier.

## Title

VintageBench: Do AI Analysts Update Correctly When the Data Are Revised?

## Benchmark

**Problem.** Analysts, and now AI agents, draw conclusions from provisional data:
first-release GDP, payrolls, industrial production. Statistical agencies later revise
these figures. A trustworthy analyst agent must answer from the data available on the
date in question, judge how fragile that conclusion is, and update when, and only
when, revisions change it.

**Task format.** Each task is a plain yes/no question ("Did US real GDP shrink in 2022
Q2?") with an as-of date. In turn 1 a tool serves only data published by that date.
The agent returns its calculation, its answer, its confidence, and the probability that
the conclusion survives full revision. In turn 2 it receives the latest vintage with a
neutral prompt: "Here is the latest data. Answer the question." Tasks are flips (the
conclusion changes on revision), controls, and no-change tasks (identical data).

**Grading.** Gold answers are computed from the vintages by code, with no human labels
and no LLM judge. Metrics:
- as-of and revised accuracy;
- update correctness, from the actual answer change;
- calibration and discrimination of the survival probability;
- leakage of later-vintage values;
- label/text contradictions;
- a no-tools memorization probe that classifies recalled values as first-release,
  latest or neither.

Sanity agents (oracle, leaker, never-update) validate the grader.

**Data.** Vintages come from the Philadelphia Fed Real-Time Data Set for
Macroeconomists: BLS, BEA and Federal Reserve Board series. A checksummed script fetches
them, and the repository stores only task definitions. A v0 prototype used ALFRED.

**Pilot lessons.**
- **Base rate.** Across 1,235 candidate questions, 120 (9.7%) first-release conclusions
  differ on the latest vintage. For one payroll template it is 23 of 116 (19.8%).
- **Calibration.** Four OpenAI configurations (frontier and small, reasoning off and on;
  540 episodes) gave mean survival probabilities of 0.86–0.92, close to the roughly 90% survival
  that the base rate implies.
  But they barely separated conclusions that later flipped from those that held (AUC
  0.58–0.64), and rated 45–54 of the 59–60 flip episodes at 0.8 or higher.
- **Memorization.** Without tools, recalls that matched a vintage matched first-release
  values far more often than latest values: 71 against 17 of 324 distinguishable
  values. Many of those matches are on low-precision quantities, where a match can be
  chance.
- **Accuracy.** v0 showed that frontier models ace questions that spell out the formula.
  On v1's plain questions the frontier model still scored 135/135. The small model
  with reasoning off failed mainly at data gathering (20 of its 26 wrong answers). So
  v1 tests judgement under revision, which arithmetic accuracy does not capture.

**Expected outputs.** An open benchmark of about 600 tasks over more series, revision
horizons and multi-step analyses; the tool-serving harness; base-rate tables;
leaderboard results for frontier and open-weight models; and a paper.

**Impact.** Agents used in economic, financial and policy analysis need to know when
their conclusions are provisional. VintageBench measures this on real revisions,
cheaply and reproducibly.

**Generalization.** The design carries over to any domain with dated, revised records:
corporate earnings restatements, clinical data whose lab values or diagnoses are
corrected, and data-pipeline backfills that rewrite history.

## Differences

Total Recall? Evaluating the Macroeconomic Knowledge of Large Language Models (Crane,
Karra & Soto, Federal Reserve Board FEDS 2025-044, June 2025) shows two things. LLM
recall of macroeconomic data mixes first-print values with later revisions, and LLMs
often believe they have data that have not yet been released. That paper probes
memory. VintageBench tests agents working from dated, tool-served vintages: do they
answer from what was available, judge whether the conclusion will survive revision,
and update correctly when revised data arrive? ExAnte (arXiv:2505.19533) and
Look-Ahead-Bench (arXiv:2601.13770) measure temporal leakage and look-ahead bias, not
revision-aware updating. LongDS-Bench (arXiv:2605.30434) tests long-horizon analytical
state, and TrustDABench (arXiv:2608.24145) tests reliability under table
perturbations. None of them uses real data vintages.

## Methodology

**Expert data.** Economists and statistical-agency analysts will:
- review templates and gold conventions;
- write harder multi-step questions with programmatic gold, such as recession calls;
- rate which revisions an expert would have anticipated, giving a human baseline for
  the survival probability.

**Snorkel support.** Engineering help to scale task generation, hosting and a
leaderboard, and to extend the harness to restatement and clinical-data vintages.

**Credits.** The v1 pilot cost $2.83. The costliest configuration spent $1.52 on 135
episodes, or $0.0113 per episode. At that rate, one pass of 600 tasks × 3 trials × 10
configurations costs about $203. We request $2,000: five passes for development,
ablations and final results ($1,017), doubled for the longer agentic tasks in the new
domains.

**Milestones.**
- Nov 2026: expert review; more series.
- Dec 2026–Jan 2027: 600 tasks; open-weight models.
- Feb 2027: restatement and clinical pilots.
- Mar 2027: human baseline; leaderboard.
- Apr 2027: paper and public release.

## Team

Divya Jyoti (lead): MIMS (AI & Data Science), UC Berkeley. About 3 years of software
engineering in quantitative finance at UBS. Built an evaluation framework for a
text-to-SQL data-analysis agent during an industry internship. Open to a Snorkel
co-advisor.

## Duration

6 months, November 2026 to April 2027.
