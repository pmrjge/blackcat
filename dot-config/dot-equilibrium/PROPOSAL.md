# PROPOSAL: agent equilibrium (E)

**Drafted 2026-10-04 by data-scientist from the planner's design and the user's final decisions (budget = equal USD per
item; pilot only first; blinded pairwise grading for design and open-ended).** Status: design only. Nothing is built,
installed or dispatched. The measurement that decides whether any of it ships is pre-registered in `COMPARE_eq.md`
(same folder); where the two differ, `COMPARE_eq.md` wins.

Paths: `M=.`, `W=$M/claude_next_steps/work_carried`, `EQ=$W/equilibrium` (the frozen
package, written by the user's freeze step), `STAGE=equilibrium`
(this draft), `R=$M/.claude-work/equilibrium/runs` (run data and transcripts, git-ignored, mode 0700).

## 1. Hypothesis

**H (user):** N independent agents that see different views of one task, combined by a deterministic reducer (with
optional evidence-gated reconcile rounds), sometimes beat the best single expert, and sometimes beat a planned graph,
at equal cost, including on task types that are not equilibrium-shaped (design, open-ended).

Operational form (`COMPARE_eq.md` §2): "sometimes beats" = H1_k (E vs S*) or H2_k (E vs G) confirmed for at least one
primary class k at equal USD cap per item.

## 2. Mechanism

Member i of an E-node gets view v_i = T_i(x) of item x. T_i is seeded per (item, member) and logged with its seed.

| view | definition | use |
|---|---|---|
| perm | payload segments in a cyclic shift: member i (i = 0..N−1) sees the order rotated by s_i = ⌊i·S/N⌋ (A1; replaces i·⌈S/N⌉, which repeats shifts at N = 5 for S ∈ {6, 8, 12, 16}). For S ≥ N the N shifts are distinct, since consecutive shifts differ by ⌊S/N⌋ or more, and their gaps differ by at most 1. Each position therefore holds N distinct segments across members: a Latin rectangle, and a Latin square only when S = N. For S < N, only S distinct orders exist, so members repeat an order and differ by lens. Spreads position bias evenly across members | any item with ≥ 2 segments (files, documents, data blocks, findings lists) |
| k-cover | segments split into 4 blocks; partial member j sees blocks {j, j+1 mod 4}, so every segment is seen by exactly k = 2 partial members, plus f = 1 full-view member (N = 5) | code review, research over a corpus |
| lens | a pre-registered framing sentence prepended to the task (`lenses.json`, hashed; 5 per class, table below) | every class; the only view for proofs |
| model / effort mix | members of one type at different `--model` / `--effort` | opt-in only; not in the pilot |

Lenses (text frozen in `lenses.json`):

| class | lens 1 | lens 2 | lens 3 | lens 4 | lens 5 |
|---|---|---|---|---|---|
| proofs | direct | induction / structural | contradiction / contrapositive | counterexample search first | generalise, then specialise |
| code | spec first (read the tests) | failure first (run, read errors) | minimal diff | invariants and edge cases | adversarial reviewer |
| research | primary source first | sceptic (seek disconfirming evidence) | timeline | quantitative | definitional |
| estimation | top-down | bottom-up | reference class | data first | bounds, then geometric mean |
| design | consumer / user | operator / failure modes | minimalism | extensibility | cost |
| open-ended | domain expert | novice reader | critic | synthesiser | contrarian |

Members:

- Same agent type as S* for the class (stratum), fresh context, round 0 blind (no member sees another's output).
- Each member runs in its own copy of the item fixture (no shared writable state). Tool sets and flags are identical
  across members and arms (equal power); "read-only" in the planner's design is implemented as isolation, so that S*
  is not the only arm able to run tests.
- Members never message each other (user directive). Every exchange goes through the reducer's anonymised summary.
- Output = one JSON object validated by `--json-schema`: `answer` (canonical per class), `evidence[]` (items of kind
  `command` | `file_line` | `quote` | `counterexample` | `test`, each with `ref` and `detail`), `confidence` in [0, 1]
  (logged, never used by a reducer until calibrated).

## 3. Reducers (deterministic code in the harness, not an agent)

| answer kind | reducer | no-answer case |
|---|---|---|
| discrete (short answer, label, choice) | plurality over normalised answers; ties broken by seed `eq\|ties`. Log-odds weights from confidence only after a calibration study, never in the pilot | all abstain → partial (scored as failure) |
| checkable candidates (proof, patch) | verify-then-select: run the checker (Lean 4 for proofs; the public tests shipped in the fixture for patches) on every candidate; select the first passer in seeded order | no passer → one repair round (§4); still none → partial |
| finding sets (review findings) | cluster by (file, line ± 3, claim class); accept clusters with support c ≥ t (t = 2 at N = 5, t = 2 at N = 3); single-support clusters go to a verifier call (at most 5, seeded order; unverified singles are dropped) | empty set is a valid answer |
| numeric estimates | median of ln(estimate); one Delphi round if κ < τ | all abstain → partial |
| long-form (design, open-ended) | a fresh judge (`plan-reviewer`, never a member's type, never the grader's type) ranks all candidates twice, in a seeded order and its reverse; Borda sum; ties by seed. Selects, never fuses | — |

The reducer for "checkable" uses only checks available to every arm (public tests, Lean). The scoring oracle (hidden
tests, answer key) is never visible to any arm or reducer.

**Mediator (added 2026-10-04, pre-freeze; `MEDIATOR.md`).** The reducer is the hub, made explicit as deterministic
code. It keeps a ledger that separates opinions (answers) from facts (`evidence[]` items with a checkable reference).
Each distinct fact is checked once by re-run or lookup and marked verified, refuted or unverifiable; no model checks
facts. It attributes influence (leave-one-out, exact Shapley over stored outputs, decisive facts, round-0 vs final
shift). It returns the answer plus a provenance table and a dissent record; graders see the answer only. The reconcile
summary is built from the ledger. The only new model call is RS answer-equivalence clustering (`verifier`, ≤ 0.05B).
Influence-weighted reducers (R1 veto, R2 calibrated, R3 facts-only, ENS) are offline counterfactuals over the same
outputs; the live run uses the plain reducer R0.

## 4. Consensus and reconcile

- κ (agreement, **not** P(correct) until its AUROC is measured): discrete = top-cluster share; numeric = share of members
  within a factor 2 of the median (|ln(est/median)| ≤ ln 2; the planner's "IQR ratio" was undefined, this replaces it);
  finding sets = share of round-0 clusters with support ≥ t; checkable and long-form: not used for stopping.
- Stop rule (discrete, numeric): stop when κ ≥ τ, τ = 0.6 (N = 5: ≥ 3 agree). Otherwise one reconcile round.
- Adaptive width (confirmation only, if the pilot amendment adopts it): k0 = 3 members; stop if **unanimous**; else add 2
  members (N = 5) and apply the κ ≥ τ rule. Correction to the planner: with τ = 0.6 at k0 = 3, "κ0 ≥ τ" already holds at
  2 of 3, so growth would trigger only on a 1-1-1 split. The pilot runs N = 5 always and evaluates adaptive width by
  simulation from members 1-3 (`COMPARE_eq.md` §6, M1).
- Reconcile round: every member resumes its own session (`--resume`) with an anonymised, randomised summary: the cluster
  histogram and, per cluster, the first evidence item the harness verified (seeded order). A changed answer counts only if
  it cites NEW evidence the harness can verify: a command it re-runs in the member's copy with the stated outcome, a
  file:line that exists and contains the quoted text, a counterexample the checker accepts, a quote found at the cited
  corpus location. Otherwise the reducer keeps the round-0 answer and logs the change as conformity.
- Stop at a fixed point, κ ≥ τ, R_max (default 1, ceiling 2) or the budget, whichever comes first.
- Repair round (checkable, no passer): members with a candidate get the anonymised failing checker output of all
  candidates; same evidence rule; R_max = 1.

## 5. Arms (equal USD cap B per item)

| arm | pilot label | confirmation label | definition |
|---|---|---|---|
| S* | p1 | q1 | best single expert: one `claude -p --agent <S* type>` call, cap B. Type fixed per class (stratum) from the pilot |
| G | p2 | q2 | planned graph: one `planner` call (cap 0.15B) writes a plan JSON (≤ 8 nodes: id, owner type, brief, deps, kind ∈ {planning, checkable, finding-set, numeric, long-form, other}, budget weight); the harness runs nodes in topological order as `claude -p --agent <owner>`, passing dependency outputs by path (on CP items each node starts from a copy of its dependency's working directory: with several dependencies, the one latest in topological order, ties by node id, while the others' diffs are logged and not merged; each node's `answer_workdir` is logged, A1); nodes share 0.85B by the plan's weights (floor 0.05B). Answer = the final node's answer |
| E | p3 | q3 | N members of S*'s type with views (§2), reducer (§3), reconcile (§4). Pilot N = 5 non-adaptive |
| EG | p4 | q4 | G's plan with E-nodes by a fixed rule: the planning node (G's plan plus 2 lens planners, 0.075B each; reducer = the medoid plan by Jaccard similarity over (owner, kind) node multisets and dependency edges, ties to G's plan) and every checkable or finding-set node (k = 3 members, same reducer fractions as E). At least one E-node always exists (the planning node) |

Budget split inside E (fractions of B; caps passed as `--max-budget-usd`; unused allocations are not reallocated):

| reducer family | round 0 members | reserve | slack |
|---|---|---|---|
| discrete, numeric (research, estimation) | 5 × 0.14 | reconcile 0.25 (0.05 per member) | 0.05 |
| checkable (proofs, code patch) | 5 × 0.16 | repair 0.20 (0.04 per member) | 0 |
| finding set (code review) | 5 × 0.14 | single-support verifier 0.25 (≤ 5 × 0.05) | 0.05 |
| long-form (design, open-ended) | 5 × 0.15 | selection judge 2 × 0.10 | 0.05 |

Every arm call: `claude -p --agent <type> --max-budget-usd <cap> --output-format json --json-schema <class schema>
--permission-mode acceptEdits --disallowedTools Agent WebSearch WebFetch --strict-mcp-config` plus a frozen per-class
`--allowedTools` list (`flags.json`), in a fresh fixture copy (CP nodes of G and EG: a copy of the dependency's workdir, as above). Spawning is off in every arm so that "single expert" is
single, every graph is the harness's graph, and the USD cap covers the whole arm (whether the cap counts subagent cost
is unverified, which is a second reason to forbid spawns). The cap is Claude Code's own cost computation
(`total_cost_usd`), not an invoice; on a subscription plan it is notional (unverified for this account).

S* candidates (a priori first choice in bold). The planner's "best of ≤ 3 candidates" does not fit a 4-arm pilot; see
`COMPARE_eq.md` §1 and the open question in §9 below.

| class (stratum) | S* candidates |
|---|---|
| proofs | **mathematician**, proof-checker |
| code / patch | **python-engineer**, main-coder, coder |
| code / review | **code-reviewer**, security-auditor |
| research (closed-book over a frozen local corpus) | **researcher**, oracle |
| estimation | **data-scientist**, mathematician |
| design (API, schema, architecture) | **planner**, main-coder |
| open-ended (explanation, analysis, writing) | **writer**, oracle |

## 6. Predictions (recorded, not tested as such)

E > S* on proofs (select by checker), code review (recall at a precision guard), checkable code, and estimation (small
effect); neutral or worse on research and design; EG > G where the plan is wrong (proxy: the EG medoid plan differs from
G's plan).

## 7. If ever built (only after H is confirmed, and after graph runtime increments 1-4, `$M/claude_next_steps/NEXT_STEPS.md:370`)

- Knobs: `STACK_EQ=0|1` (default 0), `STACK_EQ_MAX_N=9`, `STACK_EQ_MAX_ROUNDS=2`; per-node settings (view, N, reducer,
  τ, R_max) in the plan.
- Rule exception needed: the stack rule "never … two agents on one question" (`dot-claude/rules/claude-agent-stack.md:28`)
  would need an explicit exception for a planned equilibrium node. In the experiment the harness, not an agent, spawns
  the members, so the rule is not touched.
- A graph-runtime E-node is in scope only for classes where `COMPARE_eq.md` §7 says ship.

## 8. PLAN (checklist; nothing below is started)

- [ ] **1. Item sets with oracles** (per class: pool or seeded generator of ≥ 180 items, 3 dev items, metadata incl. the
      decisive segment index and canonical segment order shuffled by seed `eq|items`; pool hashed before the pilot).
      Owners: **test-engineer** (code: patch fixtures with public and hidden tests; review fixtures with seeded bugs and a
      bug manifest), **mathematician** (proofs: Lean 4 statements, `sorry`-free check script; lens texts for proofs),
      **data-scientist** (estimation with sourced true values; research corpora with answer keys and rubrics; design and
      open-ended prompts; `lenses.json`; grader briefs). Done when every class has its pool manifest, oracle script and
      a dev-item oracle run that passes on a reference answer and fails on a seeded wrong one.
- [ ] **2. Harness** by **python-engineer**: one uv PEP 723 script `eq_harness.py` (views, schedules, caps, runner,
      reducers, κ, reconcile, ledger) and the additive pure-function module `eq_mediator.py` (`MEDIATOR.md` §7; its
      `verify()` runs model-written commands, so **security-auditor** reviews it), plus `eq_check.sh` (pre-item checks, `COMPARE_eq.md` §5), `eq_freeze.sh` (sidecar
      and collection; the c0 `freeze.sh` rejects labels other than `c<n>`), the frozen `schedule.tsv` and `flags.json`.
      Analysis route 1 `eq_analyse.py` by **data-scientist**; route 2 `eq_route2.sql` (DuckDB over the ledger and the
      transcripts) by **data-engineer**, written without reading route 1. Done when pytest covers: perm shifts ⌊i·S/N⌋ distinct for every S ≥ N (S = 2..40, N = 3, 5) and Latin-rectangle balance; CP workdir chaining,
      exact k-cover counts, reducer determinism under input permutation, seed reproducibility, cap arithmetic (Σ caps ≤ B),
      grader-input blinding (no arm token in any grader file).
- [ ] **3. Dry run** by **verifier**: the harness end to end on the 18 dev items with a stub `claude` on `PATH` that
      returns schema-valid JSON with fake costs (zero spend); both analysis routes on the stub data agree; `eq_check.sh`
      fails on each injected fault (install drift, open c-arm, concurrent session, c0 not collected).
- [ ] **4. Freeze** by the **USER** (agents cannot write into `M`): `bash eq_freeze.sh` installs the package into `$EQ` and
      writes `COMPARE_eq.sha256`, after c0 is collected and before any paid call.
- [ ] **5. Pilot** by the **USER** (spends money; consent is asked at that time, not now): 5a paid smoke on 1 dev item × 4
      arms at B = $0.50 (data discarded; checks flags, cap accounting, transcript paths, `runs3.csv` logging); 5b the
      pilot, 6 classes × 10 items × 4 arms; then the data-scientist writes the §12 amendment of `COMPARE_eq.md` and the
      user decides on confirmation.

## 9. Open decisions for the user (none blocks steps 1-3)

1. **B per item for the pilot.** Default proposal B = $2.00 for every class: arm spend ≤ 60 × 4 × B = $480 (less, since
   G and EG share the planner call), plus grader calls (≈ 200 × $0.50 cap = $100), plus the smoke (≈ $2). Ceiling ≈ $582.
2. **S* screening.** Accept the a-priori S* type per class for the pilot (default), or fund an extra screening cell p5
   (each alternative candidate × 10 pilot items of its class; ≈ 10·B per alternative, ≤ 11 alternatives listed in §5,
   so ≤ 110·B ≈ $220 at B = $2).
3. **Ship multiplier m** (`COMPARE_eq.md` §7): default m = 2.
