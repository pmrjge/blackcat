# COMPARE_eq: pre-registration of the agent-equilibrium experiment (pilot p1-p4, confirmation q1-q4)

**Drafted 2026-10-04 by data-scientist from the planner's design and the user's final decisions.** The design is
`PROPOSAL.md` (same folder); this file fixes how it is measured and read, and wins where the two differ.
**Frozen when the user runs `eq_freeze.sh`** (PLAN step 4, built in step 2). That script installs this file,
`PROPOSAL.md`, `eq_check.sh`, `eq_harness.py`, itself, `flags.json`, `lenses.json`, `schedule.tsv`, the class JSON schemas,
the grader briefs and the item-pool manifests into `$EQ`, and writes their sha256 and the freeze time to
`COMPARE_eq.sha256` beside them. `claude_next_steps/` is git-ignored by the stack repo (`.gitignore:45`, per
`COMPARE_c0.md` header), so the sidecar replaces a commit, exactly as for c0. Proof of order: the sidecar's
`frozen_at_utc` is earlier than the first `PASS` line in `$EQ/runs/p/DISPATCH_LOG.tsv` and than the first `started_utc`
in the harness ledger; `shasum -a 256 -c COMPARE_eq.sha256` prints OK at every analysis. Any change after the freeze is
an amendment: append it to §12 with date and reason, never edit §0-§11, and add a dated `# amended` line to the sidecar.

Paths: `M=/Users/pmrj/ZDone/claude-agent-stack`, `W=$M/claude_next_steps/work_carried`, `EQ=$W/equilibrium`,
`R=$M/.claude-work/equilibrium/runs` (fixture copies, raw JSON, transcript copies; git-ignored, mode 0700/0600).

## 0. What this builds on, and what it keeps

- **Kept by reference, unchanged:** `$W/stats_before/COMPARE.md` (P1-P4 definitions, §4 denominator logic, §6 reading;
  sha256 `a894da025a6640b74d7013aa29ef596bc231e40d9905b447336cca8a2f122dca`, byte-identical to
  `$M/claude-local-work/campaign/agents-baseline/stats_before_v1.1/COMPARE.md`) and `$W/context-diet/COMPARE_c0.md`
  (frozen: sha256 `57b6411aec7f83265d7e85123fa9f40f648cb53595936c71f239998b15e3792c`, sidecar frozen 2026-10-04T15:02:20Z;
  its §5 check idea, its seed formula of §8, its grading protocol of §6). Neither gets an amendment from this file.
- **Ordering constraint:** no eq call (paid or not) runs before c0 is collected (`COMPARE_c0.md` §5 step 7 has written
  `$W/context-diet/arms/c0/inputs/FROZEN_AT.txt`), and none runs while any other measurement arm is open (§5, E5-E6).
  At drafting, c0 has not started (`$W/context-diet/arms/` does not exist).
- **Not a contrast against c0.** eq compares arms with each other on its own items. The installed stack is the
  environment, pinned once for the whole pilot (§5 step 2).
- **Labels:** `c0 c1 c2 c3 c9 a1 s1 v2 r2` are taken elsewhere (`COMPARE_c0.md` §3, `context-diet/plan.md`,
  `dynamic-fanout/plan.md:267`, `stats_before/COMPARE.md` §2). eq uses `p1-p4` (pilot), `q1-q4` (confirmation),
  `p9`/`q9` (declared re-run after an environment failure, §10), `p5` (only if the user funds S* screening, §1).

## 1. Arms and stages

| arm | pilot | confirmation | definition (`PROPOSAL.md` §5) |
|---|---|---|---|
| S* | p1 | q1 | one call of the class's S* type, cap B |
| G | p2 | q2 | `planner` plan (cap 0.15B, shared with EG) + harness-executed nodes (0.85B by plan weights) |
| E | p3 | q3 | N members of S*'s type, views, reducer, reconcile; pilot N = 5 non-adaptive |
| EG | p4 | q4 | G's plan with E-nodes by the fixed rule (planning node + every checkable or finding-set node) |

- **Budget currency (user decision):** equal USD cap B per item per arm, enforced per call with
  `claude -p --max-budget-usd`; Σ caps of an arm ≤ B by construction. Actual spend (`total_cost_usd` per call) and
  tokens are both recorded; tokens are P1. The shared planner call is charged to both G and EG.
- **Every call** uses the flags of `PROPOSAL.md` §5 (`--disallowedTools Agent WebSearch WebFetch`, `--strict-mcp-config`,
  `--json-schema`, `--permission-mode acceptEdits`, the class's frozen `--allowedTools`), in a fresh fixture copy, with
  the prompt's first line `<ITEM> <label> <role>` (roles: `s`, `plan`, `n<j>`, `m<i>/<N>`, `r<k>`, `sel`, `ver`) so
  every call of one item-arm carries the item head.
- **Stages.** Pilot (user decision: spend on the pilot only): 6 classes × 10 items × 4 arms. Nothing is tested on the
  pilot; it fixes the parameters listed in §7.3 by the rules written there, and its items never enter the confirmation.
  The confirmation runs only after a §12 amendment and a new user decision.
- **S\*.** The planner's "best of ≤ 3 candidates, fixed from the pilot" cannot be done inside 4 arms. Pre-registered
  instead: S* = the a-priori type of `PROPOSAL.md` §5 (bold) for the pilot. If the user funds it, cell `p5` runs each
  other listed candidate on the same 10 pilot items; the confirmation S* is then the candidate with the highest pilot
  score (ties → the a-priori type). Without `p5`, the confirmation S* is the a-priori type, and every H1 claim reads
  "E vs the a-priori expert", not "E vs the best expert".

## 2. Hypotheses, classes, scores

Classes k: **proofs** (PF), **code** (strata CP patch, CR review; 5 + 5 pilot items), **research** (RS, closed-book over
a frozen local corpus), **estimation** (ES), **design** (DS), **open-ended** (OE).

| class | per-item score | oracle (never visible to any arm) | win / tie / loss of arm A over B |
|---|---|---|---|
| PF | 1 if the Lean 4 proof compiles with no `sorry` and no non-standard axiom, else 0 | `check_lean.sh` from PLAN step 1 | A=1, B=0 / equal / A=0, B=1 |
| CP | 1 if all hidden tests pass on the patched fixture, else 0 | hidden test suite | as PF |
| CR | recall of seeded bugs − 0.5 × (findings the grader marks false) / #seeded; a finding matches a seeded bug if same file, line within ± 3 and the blinded grader confirms the claim | bug manifest + grader | A > B / equal / A < B |
| RS | 1 if the answer meets the rubric and the key, else 0 | blinded `verifier`, answer only (§9) | as PF |
| ES | e = \|ln(estimate / true)\|; non-positive or missing estimate → e = ∞ | sourced true value | e_A < e_B − ln 1.1 / within ln 1.1 / e_A > e_B + ln 1.1 |
| DS, OE | pairwise preference | blinded `verifier`, both orders (§9) | A preferred in both orders / orders disagree or "equal" / B preferred in both |

Missing or schema-invalid output, a budget-cap stop without an answer, or a reducer "partial" score 0 (e = ∞; in a
pair, the other side wins if it has an answer, else tie). Ties are dropped from sign tests and counted.

Hypotheses per class k (π = share of discordant items won by the first-named arm):

- **H1_k:** E vs S*, π ≠ 0.5 (two-sided; a confirmation counts only in E's favour).
- **H2_k:** E vs G, π ≠ 0.5.
- **H3_k:** EG vs G, π ≠ 0.5 (secondary family, §7.1).
- **H (user):** confirmed iff at least one of {H1_k, H2_k : k primary} is confirmed in E's favour (§7.1).

## 3. Items and sampling

- Per class a pool (or a seeded generator with a frozen code hash) of ≥ 180 items, plus 3 dev items per class kept
  apart. Pools, oracles, rubrics, `lenses.json` and the decisive-segment annotation are frozen (manifest sha256 in the
  sidecar) before the pilot. A class whose pool is smaller than the confirmation n it would need cannot be primary.
- Draw order per class: `numpy.random.default_rng(3725927731).permutation(pool ids)` (seed `eq|items`, §8.4); pilot =
  the first 10 drawn (code: first 5 CP and first 5 CR); confirmation = the next ones in the same order. Items are never
  hand-picked or replaced after a result is seen.
- Canonical segment order of every multi-segment item is shuffled once at build time (seed `eq|items`) so the decisive
  segment's position in what S* and G see is random, not chosen by the item author.
- `schedule.tsv` (frozen): item order interleaved across classes (seed `eq|order`, 3167602700), and per item a
  permutation of (S*, G, E, EG) from the same generator, in that sequence. The shared planner call runs just before the
  first of G and EG. E members run in parallel; G nodes run in parallel when dependencies allow.
- View seeds: per (item, member) `2742449181 ^ int(sha256("<item>|<member>")[:8], 16)` (`eq|views`); logged per call.
- Dev items run only in the dry run (stub, zero spend) and the paid smoke (PLAN 5a); their data are never analysed.

## 4. Denominators and exclusions (identical for every arm)

- **Unit = item.** Item-arm = all calls carrying `<ITEM> <label>` (planner, nodes, members, reconcile, reducer calls).
  Grading calls are not part of any item-arm.
- **Comparison set per contrast** = items with a scored result in both arms (state its size). An item missing in one
  arm is listed, never imputed.
- **Excluded from every statistic, listed with reason:** (a) items whose oracle is found defective by the blind item
  audit (run on the oracle and the item alone, before scores are joined to arms; dropped in all arms); (b) item-arms
  with a FAIL of E1, E2, E3, E8 or E9 between their `PASS` line and their first call; (c) item-arms whose environment
  failed and whose declared `p9`/`q9` re-run also failed or was not run.
- **Data, never excluded:** wrong answers, refusals, schema-invalid output, budget-cap stops, hook denials, tool absence,
  timeouts of the model, judge disagreements (ties).
- **Discordance share** δ̂ = discordant / comparison set, per contrast, always reported with the tie count.
- **Censoring:** item-arms in which any call stopped on its budget cap stay in; their tokens are lower bounds. P1 and P5
  are repeated without them (sensitivity).
- **Over-cap:** an item-arm whose summed `total_cost_usd` exceeds B by more than 10 % stays in and is listed (cap
  overshoot is part of the mechanism; M10 measures it).

## 5. Procedure (the user runs it; agents cannot write into `M`)

1. **Preconditions** (all checked by `eq_check.sh`, stop if one fails): the sidecar exists and verifies; c0 is collected;
   no other measurement arm is open; no Claude Code session is running anything else.
2. **Record the configuration** once, before the first pilot item, in `$EQ/runs/p/CONFIG.txt`: every field of
   `COMPARE_c0.md` §5 step 2 (Claude Code version, manifest commit and files digest, `main` head, `stack.env` sha256 and
   the four knob lines, settings, agent model/effort/maxTurns), plus B per class, the consented spend ceiling, the
   sha256 of `eq_harness.py`, `flags.json`, `schedule.tsv`, and the numpy version. **This pins the install for the
   whole pilot.** The confirmation records its own `$EQ/runs/q/CONFIG.txt`; a different pin between stages is recorded
   in §12 and is allowed, because the pilot only sets parameters.
3. **Run:** `uv run --script $EQ/eq_harness.py run --stage p` walks `schedule.tsv`. Before every item it runs
   `bash $EQ/eq_check.sh <ITEM>` as a subprocess and stops on any FAIL. Checks (each appends to
   `$EQ/runs/<stage>/DISPATCH_LOG.tsv`):
   - **E1** installed manifest commit = `CONFIG.txt`; **E2** manifest files digest = `CONFIG.txt`; **E3** installed files
     match the manifest (as c0 C1-C3, with the pin read from `CONFIG.txt` instead of hard-coded).
   - **E4** `COMPARE_eq.sha256` verifies (this file, `PROPOSAL.md`, the scripts and every frozen input).
   - **E5** c0 collected: `$W/context-diet/arms/c0/inputs/FROZEN_AT.txt` and `MANIFEST.sha256` exist.
   - **E6** no open arm: every `DISPATCH_LOG.tsv` under `$W/*/arms/*/` that has a `PASS` line has a sibling
     `inputs/FROZEN_AT.txt`.
   - **E7** the item is the next one in `schedule.tsv`, or a re-check of the last PASS whose calls have not started.
   - **E8** Claude Code version = `CONFIG.txt`; **E9** `stack.env` sha256 = `CONFIG.txt`.
   - **E10** no other session active in the last 900 s in `~/.local/state/claude-agent-stack/usage/runs3.csv` (c0 C9 rule),
     except session ids the ledger assigns to this stage. Also no other `claude` process (`pgrep -x claude` count
     equals the harness's own children).
   - **E11** spend: ledger Σ `total_cost_usd` + 4B ≤ the consented ceiling in `CONFIG.txt`.
4. **During the stage:** no install, no `stack.env` edit, no `/model` or effort change, no other Claude Code use. An
   `ASK USER` in any arm call cannot be answered headless: it is data.
5. **Collect, then freeze** (before any install): `bash $EQ/eq_freeze.sh --collect p` copies, by the session ids in the
   ledger, each call's transcript (`~/.claude/projects/<slug of its cwd>/<sid>.jsonl` and its folder), the raw JSON
   outputs, `runs3.csv`, `reports.jsonl`, `CONFIG.txt`, `DISPATCH_LOG.tsv` and `NOTES.txt` into `$EQ/runs/p/inputs/`
   (transcripts into `$R/p/transcripts/`), then writes `FROZEN_AT.txt` and `MANIFEST.sha256`. Never edited afterwards.
6. **Grade** in one blinded batch after the freeze (§9). **Analyse** with both routes (§6). Then the §12 amendment.

## 6. Metrics

Pairing unit = item. log2 ratios are first-named arm / second-named arm. Contrasts: E-S*, E-G, EG-G (and descriptive
EG-S*). Route 1 = `eq_analyse.py` over the harness ledger and raw JSON outputs; route 2 = `eq_route2.sql` (DuckDB) over
the frozen transcripts' usage records and the grader CSVs, written without reading route 1. Scores, counts and test
results must agree exactly; per-item-arm token totals within 1 %, otherwise the discrepancy is resolved and documented
before any number is reported.

**Primary**

| # | metric | estimator | interval / test |
|---|---|---|---|
| H1, H2 | win/tie/loss per contrast and class (§2) | wins, losses, ties, δ̂, π̂ = wins / discordant | exact two-sided sign test on discordant items; Holm (§7.1); two-sided 95 % Clopper-Pearson for π |
| P1 | tokens per item-arm = input + cache_creation + cache_read + output over all its calls | median over items of paired log2 ratio | percentile bootstrap over items, B = 10000, seed = `20261004 ^ int(sha256("eq\|<contrast>\|P1")[:8], 16)`: E-S* 943313030, E-G 391859146, EG-G 594628461 |

**Secondary**

| # | metric | estimator | interval |
|---|---|---|---|
| H3 | EG vs G (§2) | as H1 | sign test, Holm over primary classes |
| P2 | score rate per arm and class (binary classes); mean score (CR); median e (ES) | k/n per arm | Wilson; paired exact McNemar = the sign test above |
| P3 | cap-hit rate: item-arms with ≥ 1 call stopped by its budget cap | k/n | Wilson |
| P4 | wall time per item-arm (first call start to answer, harness clock) | median paired log2 ratio | bootstrap as P1, tag `eq\|<contrast>\|P4` (1803240717, 1866285162, 1599796053) |
| P5 | USD per item-arm (Σ `total_cost_usd`) | median paired log2 ratio | bootstrap as P1, tag `eq\|<contrast>\|P5` (646548904, 1744006119, 4118203276) |

**Mechanistic (E and the E-nodes of EG; descriptive, n shown)**

| # | metric | route 1 | route 2 |
|---|---|---|---|
| M1 | accuracy vs N: for m = 1..5, mean over all C(5, m) member subsets of the class reducer's score on round-0 answers (plurality, median, verify-then-select, cluster threshold t = max(2, ⌈0.4m⌉)); long-form: not enumerable; plus the adaptive-width simulation (members 1-3, grow unless unanimous) | exact enumeration | Monte-Carlo over 10^4 random subsets, seed `eq\|ties` (366605965) |
| M2 | ρ̂ = intra-item correlation of member correctness (binary classes); N_eff = N / (1 + (N−1)ρ̂) | moments: ρ̂ = [mean_i (Y_i − N p̂)² / (N p̂ (1−p̂)) − 1] / (N − 1) | beta-binomial MLE, ρ = 1 / (α + β + 1) |
| M3 | oracle@N (≥ 1 member correct) vs reducer accuracy; selection loss = difference | ledger | transcripts |
| M4 | round-0 vs post-reconcile score; flips right→wrong and wrong→right; conformity rate = changes without verified new evidence / all changes | ledger | transcripts |
| M5 | AUROC of 1 − κ0 for predicting an E error (binary classes) | rank formula | bootstrap CI, seed `eq\|auroc` (3066176665) |
| M6 | member accuracy vs relative position of the decisive segment in its view (quintiles), and vs whether a k-cover member saw it | binned rates, n per bin | logistic GEE clustered by item |
| M7 | member accuracy per lens | k/n | — |
| M8 | accuracy by κ0 bin (0.2, 0.4, 0.6, 0.8, 1.0) | k/n | — |
| M9 | judge order-consistency: share of pairs where both orders agree (grading and E selection) | k/n | Wilson |
| M10 | cap overshoot per call = `total_cost_usd` / cap | median, max | — |

## 7. Reading the result

### 7.1 Confirmation (q stage only)

- **Primary family:** {H1_k, H2_k : k ∈ primary classes}, at most 2 classes → at most 4 tests, Holm at FWER 0.05 (first
  step α = 0.0125). If the amendment names one primary class, the family has 2 tests (first step 0.025).
- **H1_k (or H2_k) confirmed** iff its test is rejected by Holm and E has more wins than losses.
- **H confirmed** ("E sometimes beats") iff at least one primary test is confirmed.
- **H refuted** (planner's rule, kept) iff for every primary test either the reverse direction is rejected by Holm or
  the 95 % Clopper-Pearson upper bound of π is < 0.6. This is rarely reachable (§8.3); report it if it holds.
- **Powered effect excluded** (added) iff for every primary test the 95 % upper bound of π is < 0.75.
- Otherwise: **"not established at this n"**, with every count stated.
- **H3:** separate family, Holm at FWER 0.05 over the primary classes; reported with the subgroup "plan switched" (EG's
  medoid plan ≠ G's plan) descriptively.
- Non-primary classes: same tables, unadjusted p labelled descriptive; no claim.
- P1, P4, P5: a difference counts as measured only when the 95 % interval excludes 0 (`COMPARE.md` §6), n stated.

### 7.2 Ship rule

E ships for class k only if H1_k or H2_k is confirmed **and** 2^(median P1 log2 ratio of E over the beaten arm) ≤ m,
m = 2 (default; the user may change m only by amendment before the confirmation is unblinded). The P5 ratio and its
interval are reported next to it. The build itself follows `PROPOSAL.md` §7.

### 7.3 Pilot → confirmation rules (applied mechanically; the result goes in the §12 amendment)

1. **S\*** per class: §1.
2. **N and width:** N = 3 if the M1 enumerated score at m = 3 is within 0.02 of m = 5 (pooled over binary classes),
   else 5. Adaptive width (k0 = 3, grow unless unanimous) is adopted iff its simulated score is within 0.02 of N = 5
   and its simulated mean member count is ≤ 4.
3. **B per class:** unchanged unless P3 (cap-hit) of S* exceeds 0.3 in that class; then B is doubled for all arms of
   that class.
4. **Primary classes:** for each class k and contrast c ∈ {H1, H2}: δ̃ = (d + 1)/(n + 2), π̂ = (w + 1)/(d + 2),
   shrunk π̃ = 0.5 + 0.5 (π̂ − 0.5); n_kc = the exact minimum number of items for power 0.8 at α = 0.0125 with (δ̃, π̃)
   (`derive_numbers.py` `min_items`), infinite if π̃ ≤ 0.5. n_k = min_c n_kc. Eligible: n_k ≤ the pool remainder and ≤
   the user's affordable maximum. Primary = the 2 eligible classes with the smallest n_k (ties → larger π̂). None
   eligible → no confirmation; H is reported as "not supported by the pilot".
5. **Confirmation n per primary class** = n_k. Both H1_k and H2_k are tested on the same items.
6. Any further change to §0-§11 for the confirmation (reducer fractions, τ, R_max, flags) is listed in the amendment
   with its reason, before the first q item.

### 7.4 Pilot reading

Descriptive only: every table of §6 with n, intervals where defined, and the sentence "pilot, no test". The pilot
cannot confirm or refute anything (§8.2).

## 8. Statistics (re-derived; `derive_numbers.py`, output `derive_numbers.out`, two routes: `math.comb` and `scipy`)

### 8.1 Critical counts (exact two-sided sign test, p = 0.5)

| α | first reachable | minimal wins at n discordant |
|---|---|---|
| 0.05 | 6/6 (p = 0.031) | 9/10, 10/12, 12/15, 15/20, 18/25, 21/30, 27/40 |
| 0.025 (Holm, 1st of 2) | 7/7 (0.016) | 9/10, 11/12, 13/15, 16/20, 19/25, 22/30, 28/40 |
| 0.0125 (Holm, 1st of 4: **this design**) | 8/8 (0.0078) | 10/10, 11/12, 13/15, 16/20, 20/25, 23/30, 29/40 |
| 0.0083 (Holm, 1st of 6) | 8/8 (0.0078) | 10/10, 11/12, 13/15, 17/20, 20/25, 23/30, 29/40 |

All of the planner's counts check out: 6/6, 9/10, 15/20, 21/30 at 0.05; 7/7 at 0.025; 8/8, 10/10, 11/12, 17/20 at
0.0083.

### 8.2 Power (π = 0.75, power 0.8)

| α | normal-approx. n_d | exact power at that n_d | exact n_d (power ≥ 0.8 from there on) | items, n_d/δ at δ = 0.3 | items, exact unconditional (D ~ Bin(n, δ)), δ = 0.2 / 0.3 / 0.4 |
|---|---|---|---|---|---|
| 0.05 | 28.9 → 29 | 0.71 | 35 | 97 | 168 / 112 / 84 |
| 0.025 | 35.3 → **36** | 0.725 | 42 | 120 | 196 / 131 / 98 |
| 0.0125 | 41.6 → 42 | 0.77 | 46 | 140 | 229 / **153** / 114 |
| 0.0083 | 45.3 → 46 | 0.76 | 50 | 154 | 246 / 164 / 123 |

Monte-Carlo check (20 000 replicates, seed `eq|derive|mc`) at the δ = 0.3 exact minima: 0.806, 0.803, 0.800, 0.803.
**Pilot reach:** 10 items, δ = 0.3, π = 0.75: power 0.008 at α = 0.05; P(≥ 6 discordant) = 0.047.

### 8.3 Refutation operating characteristics (per test, at the exact n_d)

| n_d | "refuted" (upper < 0.6) needs wins ≤ | P(refuted \| π = 0.5) | "powered effect excluded" (upper < 0.75) needs wins ≤ | P(excluded \| π = 0.5) | P(excluded \| π = 0.75) |
|---|---|---|---|---|---|
| 35 | 14 | 0.155 | 20 | 0.845 | 0.016 |
| 46 | 20 | 0.231 | 28 | 0.948 | 0.024 |
| 50 | 22 | 0.240 | 30 | 0.941 | 0.014 |

H refuted needs every primary test refuted: under π = 0.5 everywhere and independent tests, about 0.23⁴ ≈ 0.003 at
n_d = 46. Hence the added "powered effect excluded" reading.

### 8.4 Seeds (`20261004 ^ int(sha256(tag)[:8], 16)`, checked by Python and by `shasum` + shell arithmetic)

`eq|order` 3167602700 · `eq|items` 3725927731 · `eq|views` 2742449181 · `eq|ties` 366605965 · `eq|grader` 3808915453 ·
`eq|regrade` 779827486 · `eq|auroc` 3066176665 · `eq|reconcile` 3724266183 · P1/P4/P5 seeds in §6.

### 8.5 Corrections to the planner's numbers

1. n_d at α = 0.025 is 36 (35.29 rounds up), not 35.
2. The normal approximation overstates the power of the exact test (0.71-0.77 at the formula's n_d). Exact n_d:
   35 / 42 / 46 / 50.
3. items = n_d/δ ignores that the discordant count is random. Exact items at δ = 0.3: 112 / 131 / 153 / 164 for
   α = 0.05 / 0.025 / 0.0125 / 0.0083 (planner: ~100 / 117 / — / 155).
4. The primary family is H1 and H2 over 2 classes = 4 tests, so Holm's first step is 0.0125 (8/8 minimum; 153 items
   per primary class at δ = 0.3), not 0.025 as for 2 tests.
5. The refutation rule is nearly unreachable (§8.3).
6. τ = 0.6 at k0 = 3 is met by 2 of 3, so "stop if κ0 ≥ τ" would grow only on a 1-1-1 split; adaptive growth is
   "unless unanimous" (`PROPOSAL.md` §4).

## 9. Grading

- **Mechanical** (PF, CP, ES, and the matching step of CR): oracle scripts run by the harness after the freeze, on
  answers stripped of arm labels. No LLM.
- **Rubric** (RS) and **claim match** (CR): a fresh `verifier` session per batch file, brief saved word for word as
  `$EQ/runs/<stage>/grader_brief_<class>.md`; input = answer text only (evidence, κ, member count and formatting
  metadata stripped; whitespace normalised), item-arms relabelled with random tokens and shuffled (seed `eq|grader`),
  all four arms of a stage in one batch. Vocabulary pass|fail (RS) and true|false|unclear (CR, unclear = not false).
  A random 20 % (seed `eq|regrade`) is re-graded by a second fresh `verifier`; Cohen's κ with n is reported; κ < 0.6 →
  RS and CR results carry a "grader unreliable" flag.
- **Pairwise** (DS, OE; user decision): a fresh `verifier` session per pair and order; each pair (E-S*, E-G, EG-G, and
  descriptive EG-S*) is judged twice, A/B swapped, in separate sessions; a win needs both orders to agree, else tie.
  The grader is never a member, node or selector of any arm (fresh session; `verifier` is not an S* type; E's selection
  judge is `plan-reviewer`, so grader and selector differ in type and prompt).
- **Judge-bias caveats (recorded, partly controlled):** position bias (controlled by both orders; M9 reports the
  disagreement rate); verbosity bias (answer length per arm reported; sensitivity: wins restricted to pairs with length
  ratio in [0.67, 1.5]); self-preference and shared taste (members, selector and grader are all Claude models: an E win
  on DS/OE may partly reflect that E's selector optimises what a Claude judge prefers, a Goodhart channel the design
  cannot close); no human ground truth (optional: the user grades 10 random pilot pairs blinded; agreement reported).
- Grader calls cost money outside B: per-call cap $0.50, total included in the consented ceiling.

## 10. Stop rules

- **Per item:** any `eq_check.sh` FAIL → the harness does not start the item. E7, E10: fix and re-check.
- **Stage stop** (remaining items not run, reported missing): E1, E2 or E3 fails (install changed: irrecoverable for the
  stage); E8 (Claude Code version changed: continue only after a §12 amendment splitting the stage by version); E9
  (`stack.env` changed: restore to the recorded hash, §12 note); E11 (ceiling reached: stop; more spend needs new
  consent); cumulative spend > 1.1 × the projected stage spend from the first 10 items (stop, amend).
- **Environment failure** (API outage, harness bug, process killed from outside): note in `NOTES.txt`; one declared
  re-run of that item-arm labelled `p9`/`q9`, declared in §12 before it runs; it replaces the failed run in analysis.
  Model errors, refusals, wrong or missing answers, cap stops and hook denials are data.
- **No interim analysis and no early stop for results**, in either stage. Grading starts after the stage is frozen.

## 11. Confounds (recorded, not controlled)

- Same model family for members, selector and grader (§9). Contamination: items from public sources may be in training
  data (pools record their source; contamination is a pool property shared by all arms).
- Parallel members share prompt-cache prefixes and rate limits: E's token and wall-time costs reflect this harness's
  parallelism, not a law of E. Cache share per arm is reported.
- `--max-budget-usd` is Claude Code's own cost computation; whether it binds for this account's auth type, whether it
  counts subagent cost and how far a call overshoots are unverified until the paid smoke (PLAN 5a) and M10.
- Whether the stack's hooks run and write `runs3.csv` rows for headless `--agent` sessions is unverified; E10 and route 2
  do not depend on those rows (route 2 uses transcripts).
- Headless calls cannot answer `ASK USER`; arms that would ask lose that path equally.
- Pilot-chosen parameters (S*, N, B, primary classes) carry the pilot's noise; the pilot's items never enter the
  confirmation, which protects the test but not the choice.
- Time drift and web drift: arms are interleaved per item (§3) and network tools are off for every call.
- Without `p5`, S* is an a-priori expert, not the best one (§1).

## 12. Amendments (dated; append only)

- **A0 — 2026-10-04, PRE-FREEZE (written before `eq_freeze.sh` and before any eq call; part of the frozen text).
  Mediator and multi-reducer option.** Reason: two user questions (an explicit mediator; reducers that each apply
  influence-weighted aggregation). Design and reach are in `MEDIATOR.md`, which joins the frozen package and the sidecar
  (E4). Changes to §0-§11, effective from the first pilot item:
  1. The E reducer becomes the mediator module of `MEDIATOR.md` §1-§4: a per-item-arm ledger; each distinct fact
     checked once (verified / refuted / unverifiable; no model checks facts); the reconcile summary built from the
     ledger (up to 2 verified facts per cluster, plus refuted facts marked); a provenance and dissent record in the
     output. §9 is unchanged: graders get the answer only, with provenance and dissent stripped.
  2. New model call: RS answer-equivalence clustering (`verifier`, cap 0.05B, inside E's reconcile reserve), only when
     deterministic normalisation leaves more than 1 cluster.
  3. Facts are also checked for S*, G and EG, offline after the freeze. This feeds M12 only and changes no arm's answer.
  4. The live run uses the plain reducer R0 (and its κ) for every decision. R1 (veto), R2 (calibrated, cross-fitted in
     the pilot), R3 (facts-only) and ENS are offline counterfactuals over the same stored outputs. Their weights never
     come from agreement, LOO, Shapley or reconcile stability (`MEDIATOR.md` §5).
  5. §6 gains M11-M18 (`MEDIATOR.md` §6), each with route 1 and route 2. Deterministic quantities must match exactly.
  6. Secondary family H4 = {R1, R3, ENS} vs R0 on E's stored outputs; classes RS, ES and CR; win rule from §2; Holm
     over 3 at FWER 0.05 (first step 0.0167, first reachable 7/7). Confirmation only; descriptive in the pilot (power
     about 0.02 on its 25 applicable items). Items needed for power 0.8 at the first step: 430 / 287 at π = 0.75 and
     217 / 145 at π = 0.85, for δ = 0.10 / 0.15. R2 is descriptive in both stages. Numbers: `mediator_numbers.out`.
  7. No change to arms, labels, caps (apart from item 2), schedules, the primary family, §7.1-§7.3 or the stop rules.
- **A1 — 2026-10-04, PRE-FREEZE (user decisions relayed by the coordinator; written before `eq_freeze.sh` and before
  any eq call; A0 stands).**
  1. **Perm shift.** Member i (i = 0..N−1) sees segments rotated by s_i = ⌊i·S/N⌋, replacing i·⌈S/N⌉ mod S.
     Re-derived (`shift_check.py` → `shift_check.out`; two routes, shift arithmetic and explicit rotation tables):
     - Old rule at N = 5: only 3 distinct shifts at S = 6, and 4 at S = 8, 12, 16. At N = 3 it collides at S = 4.
     - New rule: S distinct shifts when S < N; N distinct shifts for every S in 2..40 at N = 3 and N = 5. Proof: for
       S ≥ N, s_(i+1) − s_i ≥ ⌊S/N⌋ ≥ 1, and the gaps differ by at most 1.
     - So for S ≥ N, each position holds N distinct segments across members (a Latin rectangle; a Latin square only
       when S = N), and the decisive segment takes N distinct positions.
     - Where `PROPOSAL.md` said "Latin square when N ≤ S", read "Latin rectangle".
     - Not affected: the k-cover construction (4 blocks), the coverage counts k = 2 and f = 1, the view seeds, and
       metric M6. M6 still bins the decisive segment's relative position; under A1 every multi-segment item feeds N
       distinct positions when S ≥ N.
  2. **CP chaining.** In G and EG, a node on a CP item starts from a copy of its dependency's working directory. With
     several dependencies it takes the one latest in topological order (ties by node id); the other dependencies' diffs
     are logged, not merged. An EG E-node's members each start from that copy; the selected passer's copy becomes the
     node's output.
     - The ledger logs `answer_workdir` per node.
     - The §2 CP score = hidden tests run on the final node's `answer_workdir`. S* and E are unchanged: one fresh
       fixture copy per call.
  3. **Quorum unchanged:** τ = 0.6, t = 2 (`PROPOSAL.md` §3-§4).
  4. Nothing else in §0-§11 changes. No statistic in §8 depends on the shift rule.
- **A2 — 2026-10-04, PRE-FREEZE (security review of the harness; the coordinator's items A1.3 and A1.4; written
  before `eq_freeze.sh` and before any eq call; A0 and A1 stand).**
  1. **R3 counts members, not keys** (A1.3).
     - Cause: `file_line` keys carried the cited line, while `verify()` accepts the quote anywhere in l−1..l+1. One
       member could therefore turn one quote into 3 verified keys and outscore two members sharing one fact.
     - Fix: the key uses the line where the quote was found (one key per fact). R3's cluster score = the number of
       members with ≥ 1 verified, kind-matching round-0 fact, counting each member at most once per cluster. Ties go
       to the tied cluster with more R0 votes, then seed `eq|ties`; with no verified member, R3 = R0. Finding sets:
       accept a finding if ≥ 1 member supports it with such a fact.
     - Checked in `r3_check.py` / `r3_check.out`: padding case old 3 vs 1 (padder wins), new 1 vs 2 (pair wins); tie
       and fallback cases as specified. Details: `MEDIATOR.md` §1 and §5.
     - H4 is unchanged as a test (paired sign test, Holm over 3, first reachable 7/7). Its reach in `MEDIATOR.md` §6
       depends only on the assumed δ and π, so it is unchanged. R3 vs R0 now reads "do members with checked evidence
       outvote the plain majority?"; expect a smaller δ than under key counting.
     - M12 rates are over canonical keys.
  2. **Answer-dependent facts are unverifiable, not refuted** (A1.4).
     - Scope: in PF and CP, `command` and `test` facts, and `file_line` facts on paths the member's answer creates or
       modifies.
     - The authoritative per-member check is `run_check` on `check_copy`, logged as a `check` record, not a fact.
     - Effects:
       - R1 and R3 are not applied to checkable classes, and H4 covers RS, ES and CR only, so H4 is unaffected.
       - The live repair-round summary no longer shows true PF/CP claims as "refuted".
       - M12 reports unverifiable facts split by reason (`answer_dependent`, `not_allowlisted`, `nondeterministic`,
         `timeout`, `external`). Cross-class comparisons use answer-independent facts only.
       - M16 in PF/CP uses answer-independent facts only, which removes the inversion.
     - Cost: no model calls, no USD; fewer re-runs (less wall time). `run_check` already runs once per candidate.
- **A3 — 2026-10-05, PRE-FREEZE (the USER's explicit decision, relayed by the coordinator; written before
  `eq_freeze.sh` and before any eq call: no `COMPARE_eq.sha256` sidecar and no `runs/` exist; A0-A2 stand).
  This CHANGES THE PRE-REGISTERED SCORING of §2/§9 for PF and CP.**
  1. **A missing or score-less authenticated verdict scores 0.** Before: when the PF/CP oracle's output held no single
     authenticated `EQV1 <nonce>` line, `score` recorded score null and the item-arm was unscored (dropped by both
     routes). Answer code shares the oracle's uid and output stream (N24#5), so a failing answer could suppress its own
     verdict (`kill -9 -1` at compile time, flooding the stream) or kill the checker so that the oracle's one
     authenticated line carries score null (`checker error`; R2c F1), and turn a 0 into "unscored": selection on outcome.
  2. Now `flags.json` `no_verdict_policy` = `"zero"` (also `DEFAULT_FLAGS`): on either case `score` re-checks isolation
     (an unhealthy backend stops `score`, exit 2, nothing written for that item-arm), re-runs the oracle once, and if
     there is still no score records score 0 (`exit` kept, still counted as an oracle failure; `detail`
     `no authenticated verdict (scored 0)` or `authenticated verdict without a score (scored 0)`). A score from the
     re-run is recorded as usual. A host-side oracle error (no answer code involved) stays unscored.
  3. `"unscored"` (the originally pre-registered rule) remains selectable for a sensitivity re-score only; it is not
     the primary analysis. Schema: `harness/LEDGER_SCHEMA.md` `grading_results/<PF|CP|ES>.jsonl`.
  4. Nothing else changes: ES, CR (graded by `cr-grade`), arms, caps, families, tests and stop rules are as before.
- **A4 — 2026-10-05, PRE-FREEZE, pre-registration amendment (the coordinator's brief T1b; written before
  `eq_freeze.sh` and before any eq call: no `COMPARE_eq.sha256` sidecar and no `runs/` exist; A0-A3 stand).
  This CHANGES THE TOOLS every call can use (PROPOSAL §5 flags).**
  1. **Why.** The harness passed each class's tool list with `--allowedTools` only. That flag auto-approves the listed
     tools; it does not restrict the others, so the pool lists were not the tool sets the models had. And no class had
     the `Skill` tool on its list.
  2. **What changed.**
     - Every class gets `Skill`: `flags.json` `common_tools` = `["Skill"]` (also `DEFAULT_FLAGS`) is appended to the
       class's pool-owned `allowed_tools` in `member_tools`. The pools and their `pool.sha256` are unchanged.
       A flags file without `common_tools` stops the run (fails closed).
     - The list is a function of (flags, class) only, so every arm (S*, E, G, EG) and every role of a class (planner,
       selector, members, verifier, nodes) gets the identical list. `tests/test_skill_tools_argv.py` asserts this over
       every launched call of the stub run.
     - `build_argv` now passes the list twice:
       - `--tools <one comma-separated value>` restricts the built-in tool set. It carries the built-in names only:
         MCP tools (`mcp__*`, e.g. the eqbox sandbox tool) are outside the built-in set and stay on `--allowedTools`.
         `StructuredOutput` is always appended, so the `--json-schema` answer tool is never withheld.
       - `--allowedTools <tools...>` keeps auto-approving the same list in `-p` mode.
     - The launched argv, and so the `--tools` value, is in every ledger `call` record.
     - Resulting `--tools` values: PF `Read,Write,Edit,Bash,Skill`; CP `Read,Edit,Write,Bash,Glob,Grep,Skill`;
       CR `Read,Glob,Grep,Bash,Skill`; RS `Read,Grep,Glob,Skill`; ES `Read,Skill`; DS and OE `Skill`; each followed
       by `,StructuredOutput`. Under `member_exec` `"sandbox"`, `Bash` drops out of `--tools` (as before, it is
       replaced by the sandbox tool).
  3. **Evidence (no paid call; Claude Code 2.1.287, read from `claude --help` and the installed binary).**
     - `--tools <tools...>` restricts the built-in set; it takes a comma-separated value (help example
       `"Bash,Edit,Read"`); `""` disables all tools.
     - The binary implements `--tools` as deny rules (source `toolsNarrowing`): every name returned by
       `getAllBaseTools()` that the list does not name is denied. A listed name that is not built-in is ignored
       without a warning.
     - The Skill tool (`name: "Skill"`, enabled unless `--disable-slash-commands`) is in `getAllBaseTools()`, so
       `Skill` is a valid `--tools` name.
     - `--tools` adds no allow rule: allow rules come only from `--allowedTools` (rule source `cliArg`). So
       `--allowedTools` stays.
  4. **Still unverified** (settled only by a live `claude -p` call, which costs money and has not been run):
     - that the `--json-schema` answer still arrives under `--tools`, and whether `StructuredOutput` needs naming;
     - that the `--agent` frontmatter `tools:` and `--tools` combine as an intersection on the main thread under
       `-p`. Every agent named in `flags.json` lists `Skill` in its installed frontmatter (`~/.claude/agents`, read
       2026-10-05); their other tools still differ.
     - that `--settings` (if ever passed) cannot widen the list back;
     - that `Skill` actually loads a skill in a `-p` call with `--strict-mcp-config` and the members' environment
       (`CLAUDE_CONFIG_DIR` passthrough).
  5. **Effect on the design.** Members can now load skills (more capability, more tokens per call, inside the same
     caps). Tools outside the list, which were previously only unapproved, are now withheld. Arms, caps, families,
     statistics and stop rules are unchanged. Any pilot run made before A4 is not comparable with one made after it.
