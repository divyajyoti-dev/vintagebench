# VintageBench pilot results

v1 results (RTDSM data) will appear here after the v1 run.

## v0 (retired prototype on ALFRED; aggregate metrics only)

v0 used ALFRED/FRED vintages, which were removed from the repository (SPEC §8), so its
run files no longer exist and these numbers cannot be rechecked here. On 60 yes/no
tasks whose questions spelled out the formula, with reasoning off and 3 trials, the
frontier model `gpt-6-sol` scored asof_correct 180/180 (100%) and update_correct on
flips 89/90 (99%). The small model `gpt-6-luna` scored 141/180 (78%) and 65/90 (72%).
Leakage was 0/360 episodes. Most of `gpt-6-luna`'s errors were answer labels that
contradicted its own calculation: 30 of 39 wrong turn-1 answers. v0 spend was $1.53.
