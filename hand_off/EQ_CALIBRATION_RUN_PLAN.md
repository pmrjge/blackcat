# EQ calibration run plan (Phase 4): for the USER's approval

Drafted 2026-10-06 (branch `eqr-calib`), from `docs-design/RUNTIME_EQUILIBRIUM.md` §7 and §11 and `equilibrium/COMPARE_eq.md`
§12 A6. **No agent runs any step of this plan.** Every paid step is the USER's, from a logged-in terminal, after the
consent asked at that time. Agents build and test the code at $0 and analyse the frozen data afterwards.

**USD figures.** The per-call cap is `claude -p --max-budget-usd`, Claude Code's own cost computation. On a
subscription plan that figure may be notional (`PROPOSAL.md:117-118`): **[unverified] for this account.** Every total
below is a sum of caps (the worst case), not a forecast. A call can overshoot its cap before it stops; M10 measures by
how much, and the smoke checks it first.

User decisions applied: D1 nested N sweep (option B), D2 calibrate PF CP CR ES RS (no view ablation), D3 frontmatter
models (Opus members), D4 the confirmation's E arm is the runtime itself (E_rt), D10 B = $2 per item-arm and ship
multiplier m = 2, D11 keep the EG arm.

## 0. Before any spend ($0; agents and the USER)

| # | what | who | done when |
|---|---|---|---|
| 0.1 | Harness changes of A6: E2 forks (`--resume <round-0> --fork-session`, `parent_session_id`, per-branch CP workdirs), `model_ids` per call, per-agent models (D3), the p6 and p7 cells, the `cell`/`branch` fields, mediator `attribution` per round | harness part | stub run and harness tests green |
| 0.2 | Member-level grading: `grading_results/members/<CLS>.jsonl` (PF and CP hidden tests per member copy, RS rubric per distinct answer) and `members/CR_findings.jsonl` (per finding: matched bug or null, verdict, `n_seeded`); the format is read by `eq_calibrate.py` (its docstring) | harness part | a stub stage produces both files |
| 0.3 | A6 accepted by the USER and in the package (it is in `equilibrium/COMPARE_eq.md` §12) | USER | text read and accepted |
| 0.4 | c0 collected (`COMPARE_eq.md` §0): `eq_freeze.sh` refuses otherwise | USER | `FROZEN_AT.txt` of c0 exists |
| 0.5 | Freeze: `bash equilibrium/harness/eq_freeze.sh` | USER | `$EQ/COMPARE_eq.sha256` written |
| 0.6 | For q only (later): Phase 2 runtime built, reviewed and installed (`./install.sh`, the USER), because E_rt is the runtime | main-coder, reviewers, USER | `stack-eq` and the guard's eq rules live |

Shell set-up for every step (one terminal, no other Claude Code session running, `COMPARE_eq.md` §5):

```sh
cd "<the stack checkout on main>"
export EQ="$PWD/claude_next_steps/work_carried/equilibrium"     # the frozen package (eq_freeze.sh's default)
H="$EQ/eq_harness.py"                                            # the frozen harness
```

## 1. Paid steps, in order

Caps per call come from the frozen `flags.json` (the harness passes `--max-budget-usd` on every call; Σ caps of an
item-arm ≤ B by construction, `eq_harness.py` `caps_enode`). The stage ceiling is CONFIG.txt's `spend_ceiling_usd`,
checked before every item by E11 (ledger Σ `total_cost_usd` + 4B ≤ ceiling).

| step | command (USER) | per-call cap | worst case (USD) | go / no-go after it |
|---|---|---|---|---|
| 1. A4 probe | the one command in `hand_off/A4_FOLD.md` §1 | 0.25 | 0.25 | the tool list matches A4 (fold it, `A4_FOLD.md` §2) |
| 2. Smoke 5a: 1 dev item × 4 arms at B = $0.50 | §2 below | ≤ 0.50 (E members 0.07) | 2.00 | flags, caps and overshoot (M10), transcript paths, `runs3.csv`, `claude -p` authenticates; Opus ids in `model_ids` |
| 3. p6/p7 smoke: 1 RS dev item at B = $0.50 | §2 below | 0.07 member, 0.0125 branch call, 0.025 equivalence | 1.155 | forks of one session run in parallel without interference; every `parent_session_id` points to the right session; `eq_calibrate.py --stage p --dry-run` reads the smoke stage |
| 4. Pilot p1-p4 (60 items × 4 arms) | `uv run --script "$H" run --stage p --spend-ok` | S* 2.00; E member 0.28 (0.32 PF/CP), reconcile 0.10; G/EG planner 0.30, nodes by weight | 480.00 (4B rule; exact cap sum 457.50) | no stage stop (E1-E11); environment failures declared as p9 |
| 5. p6 nested sweep, PF CP CR ES RS, 40 items | the p6 cell of stage p (`run --stage p --spend-ok`; the cell selector is the harness part's, e.g. `--cell p6` **[confirm with `run --help`]**) | 0.28 member (0.32 PF/CP); 0.10 equivalence; 0.10 verifier | 112.20 | every p6 item has 9 members, checks and verdicts |
| 6. p7 branches, RS ES, 20 items | the p7 cell of stage p (e.g. `--cell p7` **[confirm]**) | 0.05 per member-round | 40.00 | four branches × 2 rounds per item |
| 7. Pilot grading (RS rubric, CR claim match, DS/OE pairwise) | §3 below | 0.50 per grader call | 82.00 (164 calls); ceiling kept at 100 | grader κ ≥ 0.6, else the flag |
| 8. Calibration grading (member-level RS answers, CR findings) | §3 below | 0.50 | ≤ 5.00 (≤ 10 calls) | every key and finding the rules need is graded (`report.v<k>.json` `skipped` is empty) |
| **pilot + calibration** | | | **740.61** (exact cap sum 700.11) | **G1: `eq_calibrate.py --stage p` (§4), then the USER's go for q** |
| 9. E_rt smoke: 1 dev item, headless leader | `claude -p --agent equilibrium --max-budget-usd 0.50 …` through the harness's E_rt arm (§5) | 0.50 | 0.50 | hooks fire in headless `--agent` mode; background resumes complete; the consent file is honoured; whether `--max-budget-usd` counts subagents |
| 10. Confirmation q, per primary class (153 items × 4 arms) | `uv run --script "$H" run --stage q --spend-ok` | B_k(q) = (N\*/5) × $2 per item-arm | 1,224.00 per class at N\* = 5 (4B rule; exact 1,178.10); see §6 for N\* and rule 3 | stop rules of §10; no interim look |
| 11. H5 `none` branch, per reconcile class (RS, ES) | the q `none` branch cell **[the harness part; see §8 for E_rt]** | 0.25 B_k(q) per item | 76.50 per class at N\* = 5 | — |
| 12. q grading | §3 below on stage q | 0.50 | ≈ 7.50 per RS or CR class (≈ 15 calls); PF CP ES $0 | κ ≥ 0.6 |
| **confirmation, 2 classes** | | | **2,448.00** at N\* = 5, B = $2 (+ 153.00 H5, + ≈ 15 grading) | **G2: `eq_calibrate.py --stage q`, then Phase 5** |

## 2. Commands: configuration, smokes, pilot

```sh
# stage p configuration, once, before the first pilot item (COMPARE_eq §5 step 2). Ceiling: steps 4-6 = $632.20 of
# caps; $700 leaves ~10 % for overshoot (the USER's choice). Then the COMPARE_c0 §5 step 2 fields by hand, plus one
# line per agent file (agent_file_sha256 of the params; eq_calibrate refuses to validate a class without it):
uv run --script "$H" config --stage p --ceiling 700
for a in mathematician python-engineer code-reviewer researcher data-scientist planner writer verifier plan-reviewer; do
  printf 'agent_sha256_%s: %s\n' "$a" "$(shasum -a 256 "$HOME/.claude/agents/$a.md" | cut -d' ' -f1)"
done >> "$EQ/runs/p/CONFIG.txt"

# smokes (steps 2-3): a scratch copy, B = $0.50, dev items only, data discarded (never analysed)
S=$(mktemp -d)/eq-smoke && cp -pR "$EQ" "$S" && rm -rf "$S/runs"
jq '.B_usd |= map_values("0.50")' "$EQ/flags.json" > "$S/flags.smoke.json"
uv run --script "$H" schedule --items "$EQ/items" --stage d --out "$S/schedule.smoke.tsv"
uv run --script "$S/eq_harness.py" run --stage p --eq-root "$S" --raw-root "$S/raw" --flags "$S/flags.smoke.json" \
  --schedule "$S/schedule.smoke.tsv" --only <one dev item, e.g. RS-DEV1> --no-check --spend-ok
#   [confirm against the harness part: that `run --stage p` takes a dev item from this schedule, and the p6/p7 cell
#    selector for step 3]

# the pilot with its cells (steps 4-6)
uv run --script "$H" run --stage p --spend-ok
```

## 3. Commands: collect and grade (after each stage)

```sh
bash "$EQ/eq_freeze.sh" --collect p                       # transcripts, raw JSON, mediator ledgers; then frozen
uv run --script "$H" score --stage p --cls PF             # mechanical, $0 (also CP and ES)
uv run --script "$H" grader-input --stage p --cls RS      # blinded batch (also DS and OE pairs)
uv run --script "$H" cr-grader-input --stage p --with-members
# each batch goes to a fresh verifier session with its frozen brief ($EQ/items/graders/), cap $0.50 per call:
claude -p --agent verifier --max-budget-usd 0.50 --output-format json < <brief + batch file>   > <verdicts file>
uv run --script "$H" cr-grade --stage p --verdicts <verdicts file>
# member-level grades for the calibration (grading_results/members/): the harness part's commands [pending, 0.2]
```

The 20 % regrade (seed `eq|regrade`) is one more fresh verifier call per batch. Route 1 and route 2 then run as
pre-registered (`eq_analyse.py`, `eq_route2.py`); totals must agree within 1 %.

## 4. Calibrate p (zero spend; G1)

```sh
uv run --script equilibrium/harness/eq_calibrate.py --stage p --eq-root "$EQ" \
  --amendment A7 --reason "pilot calibration: p6 N sweep, p7 rounds and LOO views"
```

It refuses (exit 2, nothing written) an unfrozen or altered stage: the sidecar and every `pool.sha256` must verify,
`FROZEN_AT.txt` must name this sidecar, `MANIFEST.sha256` and `TRANSCRIPTS.sha256` must verify, the live ledger must
equal its frozen copy, and route 2 (transcripts) must agree within 1 % on every member call used. It writes
`equilibrium/calibration/params.v1.json`, `params.json`, the sidecar, a history line and `report.v1.json`. Every class
stays `not_run` (p tests nothing); the version holds N\*, rounds\*, the LOO variant, the certainty signal, caps, model
ids and the USD conversion. The data-scientist then writes the pilot amendment (A7: S\*, N\*, B per class, primary
classes by §7.3 rule 4, B_k(q), the ceiling) and **the USER decides whether q runs** (go/no-go G1): a class with
N\* = 1 is not eligible; at most 2 primary classes.

## 5. Confirmation q (after G1 and Phase 2)

```sh
uv run --script "$H" config --stage q --ceiling <q ceiling from §6>   # then the same agent_sha256_* lines
uv run --script "$H" run --stage q --spend-ok                           # S*, G, E_rt, EG; the H5 none branch
bash "$EQ/eq_freeze.sh" --collect q                                      # then §3 on stage q
uv run --script equilibrium/harness/eq_calibrate.py --stage q --primary <K1[,K2]> --eq-root "$EQ" \
  --amendment A8 --reason "confirmation"
```

The E_rt arm (D4) runs `claude -p --agent equilibrium --max-budget-usd <B_k(q)>` with the bundle of `params.json`,
after the harness writes the consent file (`stack-eq start --headless --consent-file`, `RUNTIME_EQUILIBRIUM.md` §2.5).
The q schedule (`schedule --stage q`) and the E_rt arm are the harness part's work **[pending: today `schedule` takes
`p` and `d` only]**.

Status per primary class (A6.5): `validated` iff H1 or H2 is confirmed by Holm in E's favour and 2^(median P1 log2
ratio) ≤ 2; `refuted` per §7.1; else `not_established`; every other class `not_run`. A validated class must have
every field (agent file sha256, one model id, caps, …), else nothing is written.

## 6. Arithmetic (re-derived from the harness's caps)

Per-call caps at B = $2 (`flags.json` families, N = 5): E members 0.70B/5 = 0.14B = **$0.28** (discrete, numeric,
finding set), 0.80B/5 = 0.16B = **$0.32** (checkable), 0.75B/5 = $0.30 (long form); reconcile reserve 0.25B over
N × R_max calls; RS equivalence 0.05B = **$0.10**; CR verifier 0.25B/5 = **$0.10**; G planner 0.15B = $0.30 shared with
EG; EG lens planners 2 × 0.075B.

- **Pilot arms:** the 4B rule gives 60 × 4 × $2 = **$480.00**. The exact cap sum is lower: per item S\* 1B + E 0.95B
  (1.00B checkable; the 5 % slack is never allocated) + G and EG 1.85B (one shared planner call): PF 10 × 3.85B, CP 5 ×
  3.85B, CR, RS, ES, DS, OE 45 × 3.80B → 228.75B = **$457.50**.
- **Smokes:** 4 arms × $0.50 = $2.00; p6/p7 smoke on one RS dev item at B = $0.50: 9 × 0.14 × 0.50 = 0.63, + 0.05 ×
  0.50 = 0.025 equivalence, + 4 branches × 5 members × 2 rounds × 0.025 × 0.50 = 0.50 → **$1.155** (the design's 1.13
  omits the equivalence call).
- **p6:** members 9 × (PF 10 × 0.32 + CP 5 × 0.32 + CR 5 × 0.28 + ES 10 × 0.28 + RS 10 × 0.28) = 9 × 11.80 =
  $106.20; RS equivalence 10 × 0.10 = $1.00; CR verifier ≤ 10 per item × 5 × 0.10 = $5.00 → **$112.20** (= the
  design's 56.1 B).
- **p7:** 20 items × 4 branches × 5 members × 2 rounds × 0.025B ($0.05) = **$40.00** (800 calls).
- **Grading, pilot:** DS/OE pairwise 20 items × 4 pairs × 2 orders = 160 calls; RS and CR 1 batch + 1 regrade each =
  4 → 164 × $0.50 = **$82.00**; the design's ≈ $100 (≈ 200 calls) stays as the ceiling in case a batch must be split.
  Calibration grading ≤ 10 × $0.50 = $5.00 (RS graded per distinct answer key, CR per finding).
- **Pilot + calibration:** 0.25 + 2.00 + 1.155 + 480 + 100 + 112.20 + 40 + 5 = **$740.61** (the design's ≈ $740:
  confirmed). With the exact cap sum and $82 grading: **$700.11**. Stage-p ceiling (E11): steps 4-6 = $632.20 of caps.
- **Confirmation, per primary class:** 153 items × 4 arms × B_k(q). At N\* = 5, B_k(q) = $2: **$1,224.00** (4B rule;
  exact 153 × 3.85B = $1,178.10); two classes **$2,448.00** (design: confirmed). B_k(q) = (N\*/5) × $2 for every arm:
  N\* = 3 → $734.40, N\* = 7 → $1,713.60, N\* = 9 → **$2,203.20** per class (two: $4,406.40). Rule 3 (S\* cap-hit
  > 30 %) doubles B on top: up to **$8,812.80** for two classes at N\* = 9. H5 `none` branch: 153 × 0.25 × B_k(q) =
  $76.50 per reconcile class at N\* = 5 ($137.70 at N\* = 9). q grading ≈ $7.50 per RS or CR class; a DS or OE
  primary class would add 153 × 4 pairs × 2 orders × $0.50 = $612 (none is calibrated, D2).

Corrections to the design's figures: none to the totals; the exact cap sums are lower (pilot arms $457.50 vs $480,
q $1,178.10 vs $1,224 per class at N\* = 5), the p6/p7 smoke is $1.155 (not $1.13), and pilot grading is $82 by call
count (the $100 is a buffer).

## 7. Phase 5: ship the validated params (zero spend)

```sh
cp equilibrium/calibration/params.json dot-claude/hooks/eq_params.json
~/.claude/venvs/tools/bin/python -m pytest -q tests/test_eq_params_pin.py     # byte copy, sidecar, chain, schema
git add equilibrium/calibration dot-claude/hooks/eq_params.json && git commit   # a coder or the USER; never pushed
./install.sh                                                                    # the USER
```

The installer stages `hooks/eq_params.json` and records its sha256 in `.stack-manifest.json` (key `eq_runtime`, Phase 2
installer work); the guard and `stack-eq` then route only the classes whose entry is `validated`.

## 8. Unverified, and what settles each

- The subscription-plan USD figures of `--max-budget-usd` (this account): the smoke's `total_cost_usd` vs the plan.
- Cap overshoot per call (M10): smoke 5a, then the pilot's M10.
- Parallel `--fork-session` branches of one session without interference: step 3.
- Whether `--max-budget-usd` counts subagent spend in the E_rt arm, and whether the E_rt result's `usage` includes its
  members' tokens (P1 of the ship rule): step 9; otherwise P1 for E_rt must come from its transcripts (the leader's
  and `subagents/`).
- Hooks and background resumes in a headless `claude -p --agent equilibrium` session: step 9.
- The H5 `none` branch under E_rt: the runtime has no forked-branch mode yet; until the harness part adds one, H5 is
  reported as not computable and changes nothing.
- The exact smoke and cell commands (`--cell`, a dev item under stage p, `schedule --stage q`): the harness part's CLI.
