# OE pool: open-ended ranking items (explain, compare, critique), graded by blinded pairwise preference

**Interpretation of "ranking items and claims from graded runs":** DS and OE items are *ranking* items (blinded pairwise
preference, both orders, COMPARE_eq §2/§9); RS carries the claims with keys from graded runs (`../RS/README.md`).

**Built** by `gen/gen_oe.py` from `gen/topics.py` (64 topics + 1 dev topic, authored 2026-10-04 across statistics,
ML, systems, security, mathematics, typography and colour; 20 adapted from graded prompts of the agents-baseline
campaign, e.g. P04 L1 sparsity, P05 Noether, P10 the false induction proof, P07 ReDoS, P16 benchmarking, P27
repetition code, P49 TWFE, P84 KV cache). Each topic gives three items: `explain` (400 words), `compare` (500 words,
two named options in a stated context, ends with a recommendation), `critique` (450 words; a flawed passage of three
sentences, each with one error, written for the item). Item order: content seed
`20261004 ^ int(sha256("eq|items|OE|gen")[:8],16)` = 430922291; segment order `default_rng(3725927731)`, one
permutation per item in manifest order.
- `prompt`: the task stem; `segments`: 4 requirement sentences per kind as text segments (rendered as a bulleted list
  after the prompt in the member's view order). `fixture`, `public_check`, `decisive_segment`: null; `allowed_tools`: [].
- `oracle/criteria.jsonl`: hidden criteria. Each topic has three correct facts (for critiques: the passage's three
  errors); explain items turn them into "a strong answer gets this right", compare items into relevant background,
  critique items into "identifies and correctly explains this error". Never shown to arms.
- Counts: **192 non-dev** (64 explain, 64 compare, 64 critique) + 3 dev (recursion, one per kind).

**Pair protocol and oracle:** identical to DS (`oracle.py` is byte-identical; see `../DS/README.md`): pair file
`{"first", "second"}`, two blinded records with X/Y swapped, verdicts X|Y|equal, score 1 / 0 / -1, invalid side loses,
word counts and length ratio reported for the verbosity sensitivity analysis. Grader brief:
`../graders/grader_brief_OE.md`.

**Self-test** `selftest.sh` (identical to DS): 32 checks, the same as DS on OE-DEV1..3.

**Known weaknesses.** (1) Topic facts were written by one agent from expertise, without a second source; a wrong fact
in the criteria would mislead the grader for that item (every number in the facts was re-derived once: 1 - 0.99^100 =
0.634, 1 - 0.95^20 = 0.642, mod 10 -> mod 12 moves 5/6 of keys, 10^9 IDs at 64 bits -> about 2.7%). (2) Three items per
topic are correlated. (3) Critique passages put one error per sentence, which a model may learn to expect. (4) Same
judge caveats as DS (same model family, verbosity, Goodhart channel). (5) Word limits are enforced by the grader brief,
not mechanically.
