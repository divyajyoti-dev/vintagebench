# VintageBench: Snorkel application (draft)

DRAFT — not submitted. Numbers from results/PILOT.md and runs/20261031-041615.

## 1. Impactful research artifact shipped

**Main version**

<!-- answer:1a -->
VintageBench, github.com/divyajyoti-dev/vintagebench (repository, to be made public). I built it end to end:

- Point-in-time data layer over ALFRED vintages for five US series (PAYEMS, GDPC1, PCEPI, INDPRO, UNRATE), with tests that the as-of view never returns future vintages.
- 60 yes/no tasks whose gold answers are computed from two vintages, never hand-labeled.
- A two-turn harness with a deterministic grader (no LLM judge), four sanity agents, response caching and a budget cap.
- A 20-task and a 60-task pilot on two OpenAI models, about $1.53 of API spend in total, written up with failure examples and limitations.
<!-- /answer -->
(Word count: 98/100)

**Alternative version**

<!-- answer:1b -->
ANLP-ESG, github.com/divyajyoti-dev/ANLP-ESG (public): an end-to-end NLP pipeline for corporate ESG and sustainability report PDFs.

- Layout-aware extraction of text blocks, figures and tables with an OCR fallback, plus header/footer cleaning, producing corpora for seven companies' reports.
- Topic modeling with LDA, NMF and BERTopic, with tuning and metric comparison, and an analysis of structural shifts around COVID.
- Claim/evidence detection: sentence-level CLAIM/EVIDENCE/OTHER labels from dual annotation adjudicated into a 372-sentence gold set, a Cohen's kappa script, and DistilBERT classifier inference with checkpoint/resume.
<!-- /answer -->
(Word count: 82/100)

## 2. Project title

<!-- answer:2 -->
VintageBench: Evaluating AI Analysts on Provisional Data That Gets Revised
<!-- /answer -->
(Word count: 10)

## 3. Proposed benchmark

<!-- answer:3 -->
**Problem.** Analysts routinely act on numbers that are provisional. Payrolls, GDP and inflation are revised for months or years; companies restate earnings; clinical datasets are cleaned after interim analyses; data pipelines backfill late records. A good analyst answers with what was known at the time, says how firm that answer is, and later changes exactly the conclusions the revision overturns. The data-analysis benchmarks I have found treat data as fixed.

**Test bed.** US economic data vintages from ALFRED (St. Louis Fed) give a real, dated record of every published value. VintageBench v0 uses five series: PAYEMS, GDPC1, PCEPI, INDPRO, and UNRATE as a low-revision control.

**Task.** Turn 1 gives the model a yes/no question (for example, "Was average monthly payroll growth over the 3 months ending June 2025 above 100k?"), tells it today is the as-of date, and provides a get_series tool that returns only data published by that date. It replies in JSON: answer, confidence, the values used, and caveats. Turn 2 announces a new release; the tool now serves the revised vintage, and the model returns answer, confidence, whether its conclusion changed, and why. In this example the first print gives +149.7k (Yes); a year later the revised data give +33.7k (No).

**Grading.** Gold answers are computed programmatically from the two vintages. The grader is deterministic: asof_correct, revised_correct, update_correct (changed exactly when the gold flips, penalizing missed and unnecessary updates), leakage (a reported value matching a later vintage but not the as-of one), and Brier score on turn-1 confidence. Four no-API sanity agents (oracle, always-yes, leaker, never-update) check each metric.

**Pilot.** 60 tasks (30 flips in 18 independent clusters, 30 controls, 50% Yes), 3 trials each, reasoning off. gpt-6-sol: asof 180/180, revised 179/180, update on flips 89/90, controls 90/90, Brier 0.000, pass^3 60/60. gpt-6-luna: asof 141/180 (78%), revised 157/180 (87%), flips 65/90 (72%), controls 84/90 (93%), Brier 0.216, pass^3 41/60 (68%). By cluster, gpt-6-luna updates correctly in every episode of 9 of the 18 flip clusters; gpt-6-sol does so in 17. Of gpt-6-luna's 39 wrong turn-1 answers, 30 are label slips, where the answer field contradicts its own calculation; all 9 genuine reasoning errors come from one template. My untested hypothesis is that the answer-first schema with reasoning off contributes to the slips. Zero leakage is weak evidence: the models copied tool values. With two models and small n, these are early signals; gpt-6-sol is already at the ceiling.

**Expected outputs.** A public benchmark of several hundred expert-validated tasks, harder templates where the question does not spell out the formula and models must judge how provisional a figure is, a stronger memorization probe, a leaderboard across frontier and open-weight models, and a paper.

**Generalization.** The episode format needs only two dated versions of a dataset and a programmatic gold. The same harness applies to corporate restatements (original against amended filings), clinical data (interim against locked datasets) and pipeline backfills (a table snapshot before and after late data arrive). I plan to prototype one of these.
<!-- /answer -->
(Word count: 497/500)

## 4. Difference from existing benchmarks

<!-- answer:4 -->
ExAnte (Liu et al., arXiv:2505.19533, 2025) and Look-Ahead-Bench (Benhenda, arXiv:2601.13770, 2026) study temporal leakage: whether a model told to reason as of a date, or a point-in-time model, uses information from after its cutoff. In both, the past facts stay fixed; as far as I can tell, neither involves values that are revised after first publication. LongDS-Bench (Xu et al., arXiv:2605.30434, 2026) and TrustDABench (Shi et al., arXiv:2608.24145, 2026) study the reliability of data-analysis agents, across long multi-turn sessions and under insufficient or perturbed evidence respectively. Their data are static; changes happen within a session or are synthetic. VintageBench joins the two concerns using real published vintages: the correct answer depends on the as-of date, the same observation legitimately has two values, and the grader checks point-in-time correctness and whether the model updates exactly the conclusions the revision changes.
<!-- /answer -->
(Word count: 139/150)

## 5. Methodology and use of resources

<!-- answer:5 -->
**Expert data.** I will recruit economists and statistical-agency analysts to write new task templates, check that each question is natural and unambiguous, validate gold answers against the published vintages, and flag tasks that test only arithmetic.

**Snorkel engineering support.** I would ask for help to scale the task pipeline, validate the grader independently against expert labels, and red-team the benchmark for shortcuts, leakage paths and memorization.

**Compute and hosting.** In the pilot, an episode cost $0.008 on the frontier model and $0.0004 on the small model, with reasoning off. A 500-task, 3-trial run is 1,500 episodes, about $12 per frontier model. Ten models in two configurations come to about $250; I request $1,000 of API credit to allow for reasoning tokens and reruns. Open-weight models would run through a hosted inference API. Hosting needs are a public repository and a static leaderboard.

**Milestones.**
- Nov–Dec 2026: reasoning-first schema, open-weight model, label-contradiction diagnostic.
- Jan–Feb 2027: expert-written templates; about 300 validated tasks.
- Mar–Apr 2027: grader validation, red-teaming, second-domain prototype.
- May–Jun 2027: full runs, public release, paper.
<!-- /answer -->
(Word count: 177/200)

## 6. Team members

<!-- answer:6 -->
- **Divya Jyoti** (lead), MIMS (AI & Data Science), UC Berkeley. I worked for about three years as a software engineer in quantitative finance at UBS. During an industry internship I built an evaluation framework for a text-to-SQL data-analysis agent.
- I would welcome a Snorkel co-advisor, especially for grader validation and expert-data workflows.
<!-- /answer -->
(Word count: 54)

## 7. Estimated project duration

<!-- answer:7 -->
Eight months, November 2026 to June 2027, following the milestones above.
<!-- /answer -->
(Word count: 11)

---

## Appendix: Citation verification notes

This appendix is not part of any answer. arxiv.org and huggingface.co could not be fetched from this session (blocked by network policy), so no paper was read in full.

- **ExAnte, arXiv:2505.19533 (2025).** The title, ID, authors (Yachuan Liu et al., U. Michigan) and May 2025 submission come from WebSearch result summaries of the arXiv listing. Its scope (temporal leakage and cutoffs for stock, Wikipedia, publication and QA tasks; no mention of revisions or vintages) was confirmed on the authors' code repository, github.com/yachuan/ExAnte, which does not state the arXiv ID. The EACL 2026 venue comes from a search summary only and is not claimed above.
- **Look-Ahead-Bench, arXiv:2601.13770 (2026).** The title, arXiv ID and scope (look-ahead bias in point-in-time LLMs, measured through alpha decay in simulated trading) were confirmed on the author's repository, github.com/benstaf/lookaheadbench, which does not mention data revisions. The author and January 2026 date come from search summaries.
- **LongDS-Bench, arXiv:2605.30434 (2026).** The title, arXiv ID and EMNLP 2026 acceptance were confirmed on the authors' repository, github.com/zjunlp/DataMind. The data source (Kaggle notebooks, 68 tasks) and the author list come from search summaries only, so the answer says only "static" data. The repository page does not mention data revisions.
- **TrustDABench, arXiv:2608.24145 (2026).** Verified only through WebSearch summaries of the arXiv PDF (perturbation operators over existing data-analysis QA sets, testing insufficient evidence and representation changes). No primary source was read. The first-author name (Shi) and August 2026 date come from earlier search notes. The answer keeps the claim general.
- **"Neither involves revised values"** is based on the abstracts as summarized and on the repository pages. It is not a claim from a full reading of the papers.
