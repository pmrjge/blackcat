# DS pool: design ranking items (API, schema, architecture), graded by blinded pairwise preference

**Interpretation of "ranking items and claims from graded runs":** DS and OE items are *ranking* items. No answer key;
two arms' answers to the same item are judged by a fresh `verifier` session per pair and per order (A/B swapped), and a
win needs both orders to agree (COMPARE_eq §2, §9). RS carries the "claims from graded runs" (see `../RS/README.md`).

**Built** by `gen/gen_ds.py` from `gen/scenarios.py` (63 scenarios + 1 dev scenario, authored 2026-10-04; 6 adapted
from graded prompts of the agents-baseline campaign, whose rubrics became hidden criteria: P12 ledger, P41 cron to
queue, P51 chat, P70 sessions, P55 document search, P93 eval harness). Each scenario gives three items: `api`,
`schema`, `arch`. Item order: content seed `20261004 ^ int(sha256("eq|items|DS|gen")[:8],16)` = 4129061320; segment
order `default_rng(3725927731)`, one permutation per item in manifest order.
- `prompt`: the task stem (system context, deliverables for the kind, 900-word limit); `segments`: the 5 requirements
  as text segments (the harness renders them as a bulleted list after the prompt, in the member's view order).
  `fixture`, `public_check`, `decisive_segment`: null; `allowed_tools`: [] (pure writing; equal for every arm).
- `oracle/criteria.jsonl`: hidden judging criteria per item (requirement coverage, three kind criteria, 2-3
  scenario-specific pitfalls, correctness, word limit). Never shown to arms.
- Counts: **189 non-dev** (63 api, 63 schema, 63 arch) + 3 dev (shared to-do app, one per kind).

**Pair protocol** (`oracle.py`, byte-identical in DS and OE): `--answer pair.json` with `{"first": <arm output>,
"second": <arm output>}` (first = first-named arm of the contrast; the harness keeps that mapping). `--grader-input`
writes two records (order 1: X = first, Y = second; order 2 swapped), each with a content-hash `rid`, the task as S*
saw it, the criteria, the word limit and the two answers (redacted of arm, member, head-line and id tokens, then
blind-checked; exit 2 if any token remains). `--grade` takes `[{rid, verdict: X|Y|equal}]` for both rids: score 1 (first
wins both orders), 0 (split or equal), -1 (second wins both). Invalid or missing sides lose mechanically, both invalid
tie. Detail reports word counts and the length ratio for the verbosity sensitivity analysis (COMPARE_eq §9).

**Self-test** `selftest.sh`: 32 checks (reference vs seeded wrong answer under a deterministic stub that prefers the
reference: 1, swapped: -1; position-biased stub: 0; equal: 0; empty or missing sides; two swapped records; blinding;
malformed input; missing grades; determinism; pool audit including blinding of every item's grader input).

**Known weaknesses.** (1) Three items per scenario are correlated (same domain and requirements). (2) The stub tests
the scoring mechanics, not grader quality; grader quality is measured only by M9 order consistency and the optional
human check. (3) Same-family judge and Goodhart channel via E's plan-reviewer selector (COMPARE_eq §9). (4) Scenarios
are authored by one agent; their difficulty is unmeasured until the pilot. (5) The 900-word limit is enforced by the
grader brief, not mechanically.
