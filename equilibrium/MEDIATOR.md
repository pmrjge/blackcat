# MEDIATOR: the hub of an E-node, made explicit (design + pre-registration addendum)

**Drafted 2026-10-04 by data-scientist, before any freeze or dispatch.** Answers two user questions: "shouldn't the
equilibrium have a mediator for all the opinions, facts, results of each agent shift on the main end result?" and
"maybe having reducers each applying an influence-weighted aggregation". Pre-registered through `COMPARE_eq.md` §12,
amendment A0 (pre-freeze); this file is part of the frozen package. Numbers: `mediator_numbers.py` →
`mediator_numbers.out` (two routes: `math.comb` and `scipy`).

## 0. Verdict

Yes to a mediator, as **deterministic code**, not as an agent. The reducer was already the only hub (members never
talk to each other), so the mediator is the reducer plus three things the design lacked:

1. a ledger that separates opinions from facts and checks every distinct fact once;
2. attribution: how much each member, and each verified fact, moved the end result;
3. an output that carries provenance and dissent, not only the answer.

An LLM mediator is rejected for four reasons:
- It is one more opinion from the same model family, so it is correlated with the members.
- It could fuse answers, which the design forbids.
- It reads every member's text, which makes it the main prompt-injection target.
- Its choices cannot be replayed, so leave-one-out and Shapley would need new paid calls.

Multiple influence-weighted reducers (§5) are adopted only as **offline counterfactuals** over the same stored outputs.
The live run keeps the plain reducer until the confirmation shows otherwise ("measure before tuning").

## 1. Mediator ledger (one JSONL per item-arm, `$R/<stage>/<item>/<label>/mediator.jsonl`)

| record | fields |
|---|---|
| `claim` | member (anonymised m1..mN), round, answer_raw, answer_norm, cluster_id, confidence (logged only) |
| `fact` | fact_key, kind, ref, detail_norm, status ∈ {verified, refuted, unverifiable}, method, output_sha256, cited_by [(member, round, cluster_id)] |
| `change` | member, round, from_cluster, to_cluster, new_fact_keys, gate ∈ {evidence, conformity} |
| `result` | end answer, R0..R3 and ENS outputs (§5), κ (labelled "agreement, not probability"), provenance, dissent |
| `attribution` | leave-one-out (LOO) results, Shapley values (agreement game; accuracy game added after grading), decisive facts |

**Opinion vs fact.**
- *Opinion:* `answer` (the recommendation or answer).
- *Fact:* an `evidence[]` item that has a checkable reference.
- A free-text assertion with no reference is not a fact. It stays part of the opinion, and nobody, model or code, judges
  whether it is true.

**Fact checking.** Each distinct `fact_key` is checked once per item-arm, however many members or rounds cite it.

| kind | key (dedupe) | verified | refuted | unverifiable |
|---|---|---|---|---|
| `file_line` | (fixture-relative realpath, **l\*** = the first line in l−1..l+1 that contains the quote, sha256 of whitespace-normalised quote) (A2: canonical, so citations at l−1, l and l+1 collapse to one key; unresolved citations keep the cited l) | the quote is a substring of lines l−1..l+1 | the path is missing or outside the fixture, the line does not exist, or the quote is absent | — |
| `command` | (normalised argv, fixture id). **A2: in PF and CP (the answer is a workdir or answer file), `command` and `test` facts are always unverifiable, reason `answer_dependent`, and so is a `file_line` whose path is created or modified by the member's answer** | the argv matches the class allow-list (`flags.json`); the command is run twice in a fresh fixture copy (60 s timeout); the claimed exit code and output substring match both runs | both runs contradict the claim | the two runs differ, the command is not allow-listed, or it times out |
| `quote` (RS corpus) | (doc id, sha256 of normalised quote) | the quote is a substring of the frozen document | the document is missing, or the quote is absent | — |
| `counterexample`, `test` | sha256 of the normalised artefact | the checker (Lean or the test runner) accepts it | the checker rejects it | the checker errors |
| URL / external citation | normalised URL | — | — | always (network is off) |

**Answer-dependent facts (A2).** In PF and CP, a member's commands ran in its own copy, which contains its answer;
`verify()` runs in the pristine fixture, where the answer is absent or the planted bug is still present. Re-running there
would mark true claims as refuted. Such facts are therefore unverifiable (`answer_dependent`). The authoritative check is
the harness's `run_check` on `check_copy` (the pristine fixture with the member's answer overlaid, run in a fresh copy).
It is logged as a `check` record, not as a fact, and it is what verify-then-select uses. In a PF/CP repair round, the
evidence gate is this check: a revised candidate counts if `run_check` passes. `counterexample` facts stay checkable,
because the checker does not depend on the answer.

The wall-time cap for fact checking is 10 min per item-arm; facts left over are marked unverifiable. Facts are checked
for **every** arm: live for E and the E-nodes of EG (reconcile needs them), and offline after the freeze for S*, G and
EG. That gives a fair per-arm "refuted-fact rate" (metric M12).

**Security.** `verify()` executes commands that a model wrote. It accepts only allow-listed argv, runs in a fresh
fixture copy under the same sandbox as the members, with a timeout and no network. This trips the review trigger
"untrusted input → execution": security-auditor reviews it in PLAN step 2.

## 2. Influence on the end result (pure functions over stored outputs; no new model calls)

- **Leave-one-out.** For each member i, re-run the class reducer on the stored outputs without i, on both the round-0
  and the final outputs.
  - Long-form: Borda over the judge's *stored* rankings, with i removed.
  - Caveat: Borda violates independence of irrelevant alternatives. In the example (rankings x>y>z and y>z>x), removing
    the non-winner z turns the winner y into a tie between x and y. So for long-form, an LOO change is not proof that
    member i was influential.
- **Shapley, agreement game** (runtime, no oracle): v(S) = 1[R0(S) = final answer]. Exact over the 2⁵ = 32 coalitions
  at N = 5, with v(∅) = 0 and R0's seeded tie rule.
  - Example: votes A,A,A,B,C give φ = (1/3, 1/3, 1/3, 0, 0) and HHI = 1/3.
  - Finding sets: v(S) = |R(S) ∩ F_final| / |F_final|. The support count per accepted finding is logged as the cheap
    proxy.
- **Shapley, accuracy game** (analysis only, after grading): v(S) = oracle score of R0(S).
- **Decisive fact.** A verified fact f is decisive if reverting every reconcile change that cited f as new evidence
  (back to that member's previous answer) changes the R0 end result. At round 0, f is decisive for R1 or R3 if setting
  f to unverifiable changes that reducer's output.
- **Shift.** End result at round 0 vs final, and per member right→wrong and wrong→right flips. Each flip is either
  evidence-gated or conformity (the existing M4, now read from `change` records).

## 3. Where a model is still needed (never a member's type; costs inside B, logged)

| step | why code cannot do it | who | cap |
|---|---|---|---|
| RS answer equivalence ("Paris" vs "Paris, France"), only when deterministic normalisation leaves > 1 cluster | semantic equivalence | `verifier`, which returns a partition of answer strings only (no choice, no fusion); if the call fails, the string clusters are used | 0.05B, taken from E's reconcile reserve |
| CR single-support findings | already in the design | `verifier` | as `PROPOSAL.md` §5 |
| DS/OE selection | already in the design | `plan-reviewer` | as `PROPOSAL.md` §5 |

- CR claim class: members self-label it from a fixed enum in the JSON schema, so no model is needed.
- Fact verification is never done by a model. A model "fact-check" would just be one more correlated opinion.
- Every model step sees member text as quoted data, and its output is schema-constrained (a partition, a ranking or a
  boolean).

## 4. What the mediator adds to the output, and what it costs

- **Output:**
  - the end answer;
  - a provenance table (fact key, kind, status, citing members m1..mN, cluster);
  - a dissent record (each cluster not adopted: its size, its best verified facts, its refuted facts);
  - κ, labelled agreement only.
- **Graders never see provenance or dissent.** They get the answer only (`COMPARE_eq.md` §9), so arms stay
  indistinguishable to the grader. Whether provenance helps a human reader is a different study, not run here.
- **Reconcile summary** is now built from the ledger: the cluster histogram, up to 2 verified facts per cluster, and
  every refuted fact of that cluster marked "refuted by re-check". This replaces "the first verified evidence item".
- **User directives:**
  - No peer-to-peer messaging: the mediator is code, and members see only the anonymised summary.
  - Least code: one module of pure functions plus a ledger writer, and no new agent.
  - Measure before tuning: every weighted reducer is offline (§5).
- **Cost:**
  - USD: 0 for everything deterministic. The only new model call is the RS equivalence call (≤ 0.05B, RS items with
    > 1 normalised cluster only).
  - Wall time: fact checking, ≤ 10 min per item-arm.
  - Compute: attribution is ≤ 32 coalitions × 4 reducers per item, which is negligible.
  - "Near zero" is measured, not assumed: reducer and attribution CPU time per item is logged (M18).

## 5. Option: several reducers, each with its own influence-weighted aggregation

Specified and pre-registered as an option to test, not as a premise. All the reducers below run over the **same stored
member outputs**, so they share budget exactly. The live run, including the κ stop and the reconcile trigger, uses R0
only.

| id | aggregation | where the weights come from (must be independent of the vote) |
|---|---|---|
| R0 | plain: plurality / median / support ≥ t (`PROPOSAL.md` §3) | none |
| R1 | **veto**: a member whose answer-supporting evidence contains a refuted round-0 fact has weight 0; every other member has weight 1 | the world (fact checks), not the other members. No parameters |
| R2 | calibrated log-odds by lens × class (and isotonic-calibrated confidence) | held-out graded data. Pilot: 5-fold cross-fitting by item (seed `eq\|reconcile`); confirmation: fitted on the pilot, frozen in the amendment |
| R3 | **verified-support plurality** (A2): the score of a cluster = the number of MEMBERS in it with ≥ 1 verified, kind-matching round-0 fact (a member counts at most 1 per cluster, however many facts or keys it cites). Kind-matching: RS `quote`; ES `quote` or `command`; CR `command` or `test` (a reproducer; `file_line` alone shows only that the code exists). Ties: the tied cluster with more plain R0 votes wins, then seed `eq\|ties`. No verified member anywhere: R0 | the world decides who counts, never the vote; votes are used only to break ties |
| ENS | majority of {R0, R2, R3}; if all three differ, R1 | — |

How each answer kind maps:
- Numeric: R1 is the median of the non-vetoed members; R2 is an inverse-variance weighted median using held-out
  log-errors per lens; R3 is the median of members with ≥ 1 verified fact; ENS is the median of R0, R2 and R3.
- Finding sets: R3 accepts a finding cluster if ≥ 1 member supports it with a verified, kind-matching fact (one per member). ENS accepts a finding if at least 2 of R0, R2 and R3 accept it.
- Not applicable to:
  - checkable classes, because the checker decides and all passers score the same;
  - long-form classes, because selection is done by a judge.

**Circularity (rich-get-richer).**
- Weights computed from agreement, LOO, Shapley or reconcile stability measure *consensus*. Feeding them back
  entrenches the majority and rewards correlated members, and the reconcile summary shows the majority, so stability
  is partly conformity.
- So these quantities are diagnostics only (M11, M13) and never weights.
- R1 and R3 use only verdicts from re-running checks against the fixture or corpus. R2 uses only accuracy measured on
  *other* items.
- R1 and R3 use round-0 facts only. Facts first cited after the summary could be copied from it.

**Why the reducers' disagreement carries signal.** R0 reads votes, R2 reads track record and R3 reads verifiable
evidence: three different information channels. When they agree there is nothing extra to learn. When they disagree,
that disagreement is pre-registered as an error predictor (M15: AUROC vs that of 1 − κ0). Feeding disagreement back
to trigger a live reconcile round needs new model calls, so it can only be adopted by an amendment for the
confirmation, never simulated.

**Failure cases and defaults.**

| case | behaviour |
|---|---|
| ties | R0 uses its seeded tie rule; a 3-way ENS split goes to R1 |
| sparse support (no verified fact) | R1 = R0, and R3 falls back to R0, so ENS degrades to R0. M15 reports the share of items where the reducers had any non-R0 information |
| injected or adversarial member output | member text never reaches the code reducers as instructions. Fake facts are re-checked and refuted, so R1 gives that member weight 0. Fact spam is limited by the cap of 3 facts per member, kind matching and dedupe. Only the RS equivalence call and the judges read member text, and both are schema-constrained |
| small N (3) | Shapley has 8 coalitions and is coarse; R2 lens weights rest on 3 lenses per item; ENS still has 3 inputs |
| correlated members | weights do not cure correlation. ρ̂ and N_eff (M2) are reported next to every reducer result |

**Cheapest tuning-free default: R1 (veto).** It has no parameters, uses only information independent of the vote, and
equals R0 whenever no fact is refuted. It still ships only if the confirmation shows it beats R0 (H4).

## 6. Pre-registered metrics and tests (added to `COMPARE_eq.md` §6 by amendment A0)

| # | metric | route 1 (`eq_mediator.py` ledger + `eq_analyse.py`) | route 2 (independent re-implementation from stored outputs, by data-engineer) |
|---|---|---|---|
| M11 | influence concentration: HHI of agreement-game φ per item (range 1/N..1); share of "dictator" items (max φ ≥ 0.5) | exact enumeration | independent enumeration; must match exactly |
| M12 | fact status rates (verified / refuted / unverifiable over distinct facts) per arm and class; facts per answer; refuted-fact rate, paired per arm (descriptive) | ledger | re-check of all `file_line`/`quote` facts, plus a 20 % sample of `command` facts (seed `eq\|regrade`) |
| M13 | LOO stability: share of items whose N LOO results all equal the full result; LOO change in oracle score | ledger | recomputed |
| M14 | decisive facts: share of items with ≥ 1; evidence-gated vs conformity flips | ledger | recomputed |
| M15 | reducer disagreement rate; AUROC of disagreement for E error vs AUROC of 1 − κ0 | ledger | recomputed; bootstrap seed `eq\|auroc` |
| M16 | P(member correct \| cited a refuted fact) vs P(correct \| not) | k/n, Wilson | recomputed |
| M17 | Spearman correlation of accuracy-game φ with self-reported confidence | ledger | recomputed |
| M18 | reducer and attribution CPU time per item; USD of the RS equivalence call | ledger | transcripts |

**H4 (secondary family):** R1 vs R0, R3 vs R0 and ENS vs R0, each a paired sign test on E's stored outputs. The win
rule is the class's from `COMPARE_eq.md` §2. Classes: RS, ES, CR. Holm over 3 at FWER 0.05.
- **Confirmation only.** The pilot is descriptive; R2 is descriptive in both stages because its pilot fit rests on
  10 items per class.

Reach (exact; `mediator_numbers.out`):
- The first reachable result at Holm's first step (0.05/3 = 0.0167) is 7/7 (p = 0.0156).
- Reducers that read the same outputs disagree rarely; assume δ = 0.10–0.15.
- Items needed for power 0.8 at the first step: 430 / 287 (π = 0.75, δ = 0.10 / 0.15); 217 / 145 (π = 0.85).
- Pilot: about 25 applicable items (RS 10, ES 10, CR 5), so power is 0.02 even at δ = 0.15, π = 0.85. The pilot can
  show disagreement rates (δ̂), fact-status rates and attribution shapes. It cannot show that any reducer is better.
- Confirmation: H4 is informative only if both primary classes are in {RS, ES, CR}. At 2 × 153 = 306 items the power is
  0.60 (δ 0.10, π 0.75) or 0.995 (δ 0.15, π 0.85). Otherwise H4 stays descriptive.

## 7. Harness impact (additive; the builder of orchestrator workstream 4 takes it as one module)

- New file `eq_mediator.py`, pure functions:
  - `normalise`, `fact_key`, `cluster`;
  - `reduce_r0..r3`, `ens`;
  - `loo`, `shapley`, `decisive_facts`, `provenance`, `dissent`.
- `verify(fact, fixture)` is the one function with side effects (allow-listed re-runs in a fresh copy).
- Hooks into the existing harness, three calls:
  1. after round 0, `verify` the E facts and write the ledger;
  2. build the reconcile summary from the ledger;
  3. write `result` and `attribution` at the end.
- Everything else, including fact checks for S*, G and EG, H4 and M11-M18, runs offline in `eq_analyse.py` after the
  freeze.
- No change to the arms, the caps (except the 0.05B RS equivalence call inside E's reserve), the schedules or the
  grader inputs.
- Tests the builder adds:
  - R0..R3, ENS and Shapley give the same output under any permutation of member order;
  - φ sums to v(full) − v(∅);
  - the A,A,A,B,C example gives φ = (1/3, 1/3, 1/3, 0, 0);
  - the Borda IIA example reproduces;
  - `verify` refuses non-allow-listed argv and times out at 60 s.
  - A2: one member citing one quote at l−1, l and l+1 yields one key, and loses under R3 to two members sharing that fact (`r3_check.py`); ties resolve by R0 votes, then the seed.
  - A2: in PF and CP, `command`/`test` facts and `file_line` facts on answer-touched paths come back `unverifiable/answer_dependent`, never `refuted`.
