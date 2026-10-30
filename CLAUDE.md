# VintageBench

A benchmark testing whether AI analysts reason correctly about provisional data that is
later revised. Uses US economic data vintages from ALFRED (St. Louis Fed).

## Read first
- docs/SPEC.md is the source of truth for interfaces, tasks and metrics. If you must
  change an interface, update SPEC.md in the same PR.

## Git and attribution
- Never add Claude or Anthropic as an author or co-author. No "Co-Authored-By"
  trailers and no "Generated with Claude Code" lines in commits, PR titles or
  descriptions, code comments, or docs.
- Never change git user config.
- Conventional commit messages (feat:, fix:, test:, docs:, chore:).
- Work on a branch; one PR per session; never push to main.

## Secrets and cost
- Read FRED_API_KEY, OPENAI_API_KEY, TOGETHER_API_KEY from env. Never print, log or
  commit them.
- Tests never call the network; use fixtures and mocks.
- Paid model calls only via `python -m vintagebench.run`, which enforces the budget cap
  in config/run.yaml. Always run a 1-task smoke test before a full run.

## Code
- Python 3.11, src layout, type hints, small functions, pytest, ruff.
- Cache downloaded data (data/vintages/, committed) and model responses (runs/cache/);
  reruns must be free.
- Every function that computes a gold answer has a unit test.
- Subagents edit only the files they own (SPEC §6) plus their own tests.

## Done means
- pytest and ruff pass; PR opened with: what changed, how it was tested, open issues.
