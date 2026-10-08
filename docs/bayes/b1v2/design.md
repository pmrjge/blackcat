# B1 design: Bayesian inference of every learned value

Status: design + prototype v2 (data-scientist, 2026-10-03; v1 kept as design_v1.md). Binding spec: RESUME.md lines 66-80 (B1). Integration is a later python-engineer task; nothing here edits tracked files.
v2 changes (NEXT_STEPS 6.3): risk targets settled at soft 10 % / turns 2 % / hard 1 % (5.1); turns, ctx and tool_calls reparameterized (all type deviations non-centered, boundary-avoiding Gamma(2, .) priors on the group scales, 3.3); ctx(n) reparameterized as (k_t, q_t) at a reference length (3.1, S4); 4 chains x 3000 draws after 2000 tuning; scope 2 units are runs (install x prompt x variant) with an install effect (8). The fit reads stack_limits, the seed and the agents from the worktree W (B1_REPO), as v1 did.
Prototype: `fit_prototype.py` (PyMC 6.3.2, nutpie 0.16.11, ArviZ 1.3.0; `fit_prototype.py.lock`), stdlib tier `bayes_grid.py` (runs on /usr/bin/python3 3.9.6). Results: `fit_report.md` (v2; v1 in `fit_report_v1.md`), outputs `out_v2/` (v1: `out_v1/`, identical to `out/`). Data copy: `data/` with `data/SHA256SUMS` and `data/state/SHA256SUMS`. Evidence id of the fit: `f4de7ad6b29fc885ac5c480db39a54377ef62b4da8a3e179b86a73baaea7bff5` (stack_limits.evidence_id over the rows read_rows keeps).

## 0. Spec bullets and where each one is met

| RESUME B1 bullet | section |
|---|---|
| scope 1: turns.<type>, soft/hard caps agent/prompt/session, token/latency/turn estimates in stack_limits, stack_sched, stack_sched_refresh / derive_sched_model | 4 (rows L1-L8, S1-S12) |
| scope 2: routing and quality from graded runs; accuracy per agent type x task class | 4 (rows Q1-Q2), 8 |
| hierarchical partial pooling across agent types toward class/tier/model | 3.3 |
| log-normal or gamma for tokens and duration; NB for turns and tool calls; binomial/ordinal for grades | 3.1, 8 |
| cap hits, turn-limited, compacted, truncated segments censored | 3.2 |
| limit = posterior-predictive quantile with an explicit cap-hit risk target per variable; §1 floors/ceilings as prior bounds | 5.1, 5.2 |
| updates as rows append, swap only at session start via apply_and_snapshot (U4) | 5.4, 9.2 |
| fixed seeds, pinned versions, evidence_id; R-hat/ESS/divergence gates; fallback to the §4 empirical estimator | 6 |
| conjugate/closed-form stdlib in hooks; samplers only in the detached proposer, stack venv, Python 3.13 | 9.1 |
| provenance and intervals with each value (live.json, snapshot, proposals) | 7 |
| user-pinned hard floors: soft.prompt.orchestrator 80M, fan-out 32 not learnable, env overrides | 5.3 |

## 1. What the data can support today (the numbers behind the design choices)

Frozen copy at 12:11: runs3.csv 393 lines (schema 3, 2 sessions), runs.csv 2,733 lines (schema 1, 3 sessions); read_rows keeps 320 rows after last-row-wins: 281 agent rows (259 complete) over 4 sessions and 37 of 55 types, 39 main rows, 0 session rows. Gaps in the collector output that bound what any estimator can learn (all verified on the copy):
- `hit_*` columns are empty in every schema-3 row (unmeasured, U1), so a limit stop cannot be told from a normal finish except through `status_code`, `turn_limited` and `compacted` (3.2).
- `window_ctx` is set on 1 of 39 main rows and there is no `session` row: soft.prompt, hard.prompt, soft.prompt.<type>, soft.session and hard.session have (almost) no evidence; they stay on their current values (5.3, 6).
- usage/refresh.json: the last scheduler refresh was "skipped: uv cache lacks pandas/numpy", so the candidate sched_model.json is not being refreshed either.
- One session (98abbcdf, the B0 baseline) holds 186 of 281 agent rows; the §4 per-type session cap (≤ 50 % from one session) drops every single-session type outright (scout, 12 rows, has no §4 sample). The Bayesian path models the clustering instead (3.3) and does not apply that cap (3.4).

## 2. Generative story

A run (one agent segment) of type t in session s draws a demand D (API calls, context tokens, seconds per call) from a type distribution whose location is the type's own deviation from its class prior (pool, model family, frontmatter maxTurns), shifted by the session's job mix. What the collector records is min(D, the point where a limit or truncation stopped it), with flags that sometimes say it was stopped. A limit L for type t is good when P(D_new > L) for a run in the next session equals the variable's risk target r; that probability integrates over the posterior of the type's parameters and over an unknown new-session effect.

## 3. Models

### 3.1 Likelihoods

| quantity | rows | likelihood | link / parameters |
|---|---|---|---|
| api_calls (turns) | agent segments, api_calls ≥ 1 | shifted NB2: y - 1 ~ NegBin(mu, alpha_t) | log mu = lin |
| tool_calls | agent segments (schema 3 only) | shifted NB2 on tool_calls + 1 | as turns |
| ctx (tokens per run) | agent segments | log-normal: log y ~ N(lin, sigma_t) | lin = log median |
| sec_per_call = wall_s / api_calls | complete segments, wall_s > 0 | log-normal | as ctx |
| static_cc (first call's cache_creation) | healthy first segments | log-normal, no session or resume term | |
| ctx(n) = a n + b n^2 | complete, not compacted first segments | log y ~ N(log n + k_t + log1p(s_t (n / n_ref - 1)), sigma), s_t = sigmoid(q_t) | k_t = log(a_t + b_t n_ref), q_t = logit(b_t n_ref / (a_t + b_t n_ref)) hierarchical (v2; v1: log a_t, log b_t) |
| window_ctx (prompt), session ctx | main rows, session rows | log-normal, single level, seed-anchored prior (3.5) | |
| grade | graded baseline ids | ordinal logit, fail < partial < pass (8) | |

Log-normal vs gamma was decided by PSIS-LOO on the raw scale (log-normal includes the -log y Jacobian, censored rows enter as log P(Y ≥ y)); see fit_report "Likelihood family". Gamma stays implemented (`kind="gamma"`) for the proposer to re-check when data grows. The NB is shifted because every recorded run has at least one API call (a plain NB puts mass on 0, which matters for oracle/writer-type runs of 1-2 calls).

### 3.2 Censoring rule (per row, per quantity family)

A censored row contributes log P(Y ≥ y_obs) (NB: 1 - F(y - 2) for the shifted count; log-normal: log Phi((lin - log y)/sigma)). Columns read (parse_row names):

| condition | turns | ctx | spc, static_cc, ctx(n) |
|---|---|---|---|
| `status` != complete (open segment, truncated at collection) | censored | censored | row excluded |
| `compacted` = 1 | censored | censored | excluded from static_cc and ctx(n) |
| `turn_limited` = 1 or `hit_turn` = 1 | censored | censored | observed (a rate is not truncated by a stop) |
| any measured `hit_*` = 1 (soft or hard, any scope: a soft warning tells the run to wrap up, a hard deny stops it) | censored | censored | observed |
| `status_code` = 1 (partial) and every `hit_*` cell empty (unmeasured) | censored when api_calls ≥ 0.5 x the turn limit in force | censored when ctx ≥ 0.5 x soft.agent in force | observed |
| `status_code` = 1 with `hit_*` measured and all 0 | observed | observed | observed |
| `status_code` = 2 (blocked: consent, sandbox, permission) | observed | observed | observed |
| `status_code` empty on a schema-3 complete row (ended on a tool_use) | censored | censored | observed |

Why the status_code-1 proxy: with `hit_*` unmeasured, "partial" mixes limit stops (the guard's deny text asks for STATUS: partial) with environment stops (Miri, Gradle, Hackage blocked in B0). A limit stop happens near a limit by construction, so only a partial near the per-agent limit in force is read as censored. The limit in force is the session snapshot's value (the prototype uses the seed for the sessions that predate live.json v2). Sensitivity "all"/"none" is in fit_report; when the collector fills `hit_*`, the proxy switches itself off (row 6 of the table). Prompt-scope stops (the 33M soft.prompt warning reaching a builder below its own soft limit) are invisible until `hit_soft` is measured: a known under-censoring (open item for the collector, section 10).

### 3.3 Hierarchy (type -> pool / model family / frontmatter -> global; session and job-mix effects)

For quantity q, row i of type t in session s, resume flag r_i:

```
lin_i      = eta_t + tau_s z_s[s] + tau_ts z_ts[t,s] + rho r_i
eta_t      = a0 + b_fam[fam(t)] + g zmt_t + u_pool[pool(t)] + tau_t z_t
z_t        ~ N(0, 1)                  v2: every type non-centered in turns, ctx, tool_calls (v1: centered for types with >= 20 rows)
u_pool     ~ ZeroSumNormal(0.7)       over pools with >= 2 member types; one-type pools (coordinator, verifier) have none
b_fam      ~ ZeroSumNormal(0.5)       opus / sonnet (frontmatter model family, stack_limits.model_family)
g          ~ N(0.5, 0.5)              on zmt_t = log maxTurns_t - mean (frontmatter: the designer's prior on run length)
a0         ~ N(log c_q, 1.5)          c_q = 10 calls, 1M tokens, 15 s/call, 30k tokens (static_cc)
z_s ~ ZeroSumNormal(1); type x session deviation ~ N(0, tau_ts) (centered for pairs with >= 20 rows in turns, non-centered otherwise)
group scales, v1 prior HalfNormal(sd) with mean m = sd sqrt(2/pi):   tau_t sd 0.7, tau_s sd 0.3, tau_ts sd 0.5
  v2 boundary-avoiding Gamma(2, 2/m) (same mean m, density 0 at 0):  turns, ctx: tau_t, tau_s, tau_ts;  tool_calls: tau_s, tau_ts
  spc, static_cc, ctx(n), resume_ctx: HalfNormal as v1 (they passed every gate)
rho ~ N(0, 0.5)
scale:  log sigma_t (log-normal) or log alpha_t (NB) = pool level N(0, 0.5) or N(0.7, 0.75) + tau_l z_t, tau_l ~ HalfNormal(0.3)
```

- Partial pooling: a sparse type's eta_t shrinks toward its class prior (pool, model, maxTurns); an unobserved type gets exactly the class prior's predictive, which replaces stack_sched's UNVERIFIED_W heuristic and derive_sched_model's "pool:<tier>" copy.
- New-session predictive: a run in the next session has an unknown effect w ~ N(0, sqrt(tau_s^2 + tau_ts^2)); every limit and scheduler interval integrates over it (Gauss-Hermite, 7 nodes, for the NB; analytic for the log-normal). The type x session term was added after the first backtest showed the main session effect alone under-covered a new session's job mix (fit_report states this model revision).
- Resume: rho shifts resumed segments; the predictive mixes fresh/resume with the observed resume share (0.35 on the copy).
- Parameterization choices were driven by diagnostics (fit_report "Diagnostics"): sum-to-zero pool and session effects, fixed-scale pool effects (a scale estimated from 4 pools mixed badly), target_accept 0.98, 4 chains x 3000 draws after 2000 tuning (v1: 2000 / 1500; more draws shrink the Monte Carlo noise of R-hat at the 1.01 gate).
- v2 reparameterization (fit_report_v1 had turns 1, tool_calls 34, ctx(n) 21 divergences). Every divergence sat where a group scale went to 0:
  - The centered deviations of the 3 types with >= 20 rows make a funnel neck at tau_t -> 0 (turns, tool_calls). Fix: all types non-centered.
  - With 1-4 sessions (tool_calls: 2), the data cannot keep tau_s and tau_ts off 0, and the sampler wandered into the neck there too. Fix: a Gamma(2, 2/m) prior on those scales.
  - Justification for the Gamma prior (Chung et al. 2013, boundary-avoiding priors for group-level scales): it keeps v1's prior mean, and the scales are not of interest at 0. Sessions do differ in job mix (v1's backtest under-covered without tau_ts), and 37 observed types differ in median by more than 10x, so tau_t = 0 is implausible. The Gamma(2) prior removes only the neighbourhood of 0. P(tau < m/10) is 1.7 % instead of 6.4 % under the HalfNormal.
  - tool_calls keeps HalfNormal on tau_t: in probes, the Gamma prior there gave a divergence on its run seed.
  - Attempts and probes per model are listed in fit_report section 2.
- Known limit: a backtest fold trained on a single session (fold 1) cannot separate dev_t from the type x session deviation (only their sum is identified). Its fits keep a few divergences whatever the parameterization. Those fits are diagnostic only; no gate reads them.

### 3.4 Evidence filter

Same reader as §4 (stack_limits.read_rows: hostile-CSV filter, last-row-wins, model-mismatch exclusion, stale session rows) and the same 20-session window (_window). Not applied: the per-type `_cap_sessions` thinning (it deletes single-session types and real data; the session and type x session effects absorb the clustering). The hostile-CSV bound T17 still holds because the bounded step (5.4) is unchanged: one evidence id moves a value at most 25 % x d.

### 3.5 Prompt and session scopes (no hierarchy)

One variable each, no grouping to pool over. Prior on the location is seed-anchored: mu0 = log(seed) - z_(1-r) sqrt(sigma^2 + sd0^2) with sigma = 1, sd0 = 1 (bayes_grid.anchor_mu), so that with no data the prior-predictive (1 - r) quantile equals the current seed; data then moves it. soft.prompt.<type> uses the windows in which such an agent ran (stack_limits' existing sample). These are exact grid posteriors in the stdlib tier (no sampler needed).

## 4. Variable table (every learned value)

Risk r = target P(new run's demand > limit). "Gate" = section 6. "§4" = the stack_limits empirical estimator (fallback). f/g = §1 floor/ceiling.

| # | variable (consumer) | quantity, rows | likelihood | censored by | hierarchy | priors and bounds | output | r | gate | fallback |
|---|---|---|---|---|---|---|---|---|---|---|
| L1 | turns.<type> x55 (guard turn gate; MCP cap) | api_calls, agent rows | shifted NB2 | 3.2 col. turns | 3.3 | f = max(5, ceil(seed/4)), g = frontmatter maxTurns; decision clamped to [f, g] | ceil(q_(1-r)) of the new-run predictive | 0.02 | model + T(R-hat, ESS) | §4 decide (hard rule) |
| L2 | soft.agent.<type> x55 (soft_check warning) | ctx, agent rows | log-normal | 3.2 col. ctx | 3.3 | f = 100k, g = 100M | ceil2(q_(1-r)) | 0.10 | same | §4 decide (soft rule) |
| L3 | hard.agent.<type> x55 (budget_gate deny) | ctx, agent rows | log-normal (same posterior as L2) | as L2 | 3.3 | f = 2M, g = 200M; >= 2 x soft T (HARD_OVER_SOFT kept); soft <= 0.8 hard invariant | ceil2(max(q_(1-r), 2 T_soft)) | 0.01 | same; moves only when supported | §4 decide (hard rule) |
| L4 | soft.prompt (soft_check) | window_ctx, main rows | log-normal single level | hit_soft (any measured hit) | none | seed-anchored prior (3.5); f = 5M, g = 100M; soft <= 0.67 hard.prompt | ceil2(q_(1-r)) | 0.10 | support: >= 30 windows from >= 3 sessions; grid edge mass < 1e-3 | hold (today: 1 window) |
| L5 | soft.prompt.<type> (orchestrator; prompt_soft_limit) | window_ctx of windows where the type ran | as L4 | as L4 | none | user-pinned: floor = seed = 80M (hard floor), g = 100M | max(80M, q_(1-r)) | 0.10 | as L4 | hold at 80M |
| L6 | hard.prompt (budget_gate) | as L4 | as L4 | hit_hard_prompt, hit_soft | none | anchored on soft.prompt; f = 50M, g = 250M | ceil2(q_(1-r)) | 0.01 | as L4 | hold (100M) |
| L7 | soft.session (soft_check, unset) | session row ctx | log-normal single level | hit_soft, hit_hard_session | none | anchored on hard.session; f = 100M, g = 1.5B; <= 0.8 hard.session | ceil2(q_(1-r)) | 0.10 | >= 5 sessions | stays unset |
| L8 | hard.session (budget_gate) | session row ctx | as L7 | as L7 | none | seed-anchored (666M); f = 300M, g = 1.5B | ceil2(q_(1-r)) | 0.01 | >= 5 sessions | hold (666M) |
| S1 | sched_model types.<t>.turns {S, M, L} (stack_sched _est_for) | api_calls | as L1 (same posterior) | as L1 | 3.3 | - | predictive q_.25, q_.50, q_.90 | - | model gate | derive_sched_model.fit (refresh combine) |
| S2 | types.<t>.band.turns {lo, med, hi} | - | posterior of the type median | - | - | - | 5/50/95 % of the per-draw predictive median | - | same | fit() bootstrap band |
| S3 | types.<t>.sec_per_call {p50, p90}, band.sec_per_call | wall_s / api_calls, complete rows | log-normal | none (a rate) | 3.3 | a0 ~ N(log 15 s, 1.5) | predictive q_.50, q_.90; band = 5/95 % of the median | - | same | fit() |
| S4 | types.<t>.ctx {a, b}, band.ctx | ctx vs n, first segments | log-normal regression | rows excluded (compacted, open) | v2: k_t = log(a_t + b_t n_ref) and q_t = logit(b_t n_ref / (a_t + b_t n_ref)), n_ref = geometric mean of n: global + pool (ZeroSum, fixed 0.7) + type (tau ~ HalfNormal(0.7), non-centered); a = e^k (1 - s), b = e^k s / n_ref. k_t is pinned by any data near n_ref and q_t only by a type's spread in n, so a narrow-n type's q_t shrinks to its pool instead of sliding along v1's (log a, log b) ridge (21 divergences at tau -> 0) | K0 ~ N(log(5e4 + 2e3 n_ref), 1.5), Q0 ~ N(log(2e3 n_ref / 5e4), 1.5) (v1's centres a = 5e4, b = 2e3 mapped to (k, q); v1: A0 ~ N(log 5e4, 1.5), B0 ~ N(log 2e3, 2)) | posterior medians of a, b; band = 90 % factor of exp(predictive) at n_ref = M | - | same | fit() Huber IRLS |
| S5 | types.<t>.static_cc | first_cc, healthy first segments | log-normal, no session term | rows excluded | 3.3 without session/resume | a0 ~ N(log 3e4, 1.5) | predictive q_.10 | - | same | fit() p10 |
| S6 | run_interval.groups (stack_sched _run_factor) | turns, ctx, wall per run | from S1-S4 posteriors | - | - | - | predictive q_.95 / q_.50 factors per tier:fresh/resume (and per type, new key run_pi) | - | same | fit_run_interval (conformal) |
| S7 | pools.<tier> (all of S1-S5) | - | class-level predictive (dev_t ~ N(0, tau_t)) | - | - | - | as S1-S5 for a new type of that pool | - | same | fit() pools |
| S8 | resume_ctx {alpha, gamma} | resumed healthy segments | Student-t (nu = 4) regression of ctx/n - prev_peak on n, conjugate-free; small: run in the sampler | - | none (global) | alpha ~ N(0, 1e5), gamma ~ N(0, 1e4), both truncated at 0 | posterior medians + 90 % ETI | - | R-hat/ESS | fit_resume_ctx (Huber) |
| S9 | fixer {reread, lo, hi} | ctx_at_first_write - first_ctx, builder first segments | log-normal, Normal-Inverse-Gamma conjugate (stdlib closed form) | - | none (global) | NIG(mu0 = log 2e5, k0 = 1, a0 = 2, b0 = 2) | posterior median + 95 % ETI | - | n >= 5 from >= 3 agents | median_ci |
| S10 | cold.frac | first-call cache_creation / bound on cold resumes | Beta(1, 1)-binomial-like Beta likelihood on the fraction (conjugate approx: Beta moment fit) | - | none | Beta(1, 1) | posterior median | - | n >= 5 | median of frac |
| S11 | tool_calls (B2 input; no consumer today) | tool_calls (schema 3: 93 rows, 2 sessions) | shifted NB2 | as L1 | 3.3, v2: every type non-centered, Gamma(2, .) on tau_s, tau_ts (HalfNormal tau_t) | as L1 | predictive q_.50, q_.90 | - | model gate | none (not used yet) |
| S12 | stack_sched built-ins (_TURNS, _CTX, _SPC, _STATIC, UNVERIFIED_W) | - | - | - | - | - | replaced by S7 pool predictives in the model file; built-ins stay the no-file fallback | - | - | unchanged |
| Q1 | accuracy per agent type x task class (B2 routing input) | grades of graded baseline ids | ordinal logit (fail < partial < pass) | ungraded ids excluded (never imputed) | agent -> pool; family; size class; routing match | 8 | P(pass), P(>= partial) per cell, 90 % ETI | - | R-hat/ESS/div | Beta(1, 1)-binomial per agent (no pooling) |
| Q2 | routing choice (which agent/profile) | Q1 + E[tokens] from L2 posterior | decision on posterior draws | - | - | - | P(agent a is best for class c), expected utility; consumed by B2 | - | Q1 gate | no routing change |

Not learnable (never a variable; the Bayes writer must refuse them, test B1-T3): every FIXED_GUARDS / FIXED_PREFIXES name (fan-out STACK_MAX_FANOUT* incl. the orchestrator's 32, depth, BlackCat, god-coder, TTLs, MCP cap, images, policy, read gate, STACK_SOFT_LIMIT_SCALE, STACK_SCHED_POLICY), the floors and ceilings themselves, frontmatter maxTurns, and the kappa cache-price ratios (documented constants, not data).

## 5. Decision rule (what apply_and_snapshot does with a posterior)

### 5.1 The limit

T_v = the posterior-predictive (1 - r_v) quantile of a new run's demand (new session effect integrated), rounded as today (turns: ceil; tokens: ceil2), hard.agent at least HARD_OVER_SOFT x the soft T. The 90 % interval of T_v is the 5/95 % of the per-draw conditional quantile. The predicted cap-hit probability at any value c, p_hit(c) = P(D_new > c), is stored as a quantile table (7.1) so apply can evaluate it at the current value without the posterior.

Risk targets (constants RISK in stack_limits.py; policy, not data; settled, 10.1):

| family | r | reading |
|---|---|---|
| soft.agent, soft.prompt[.type], soft.session | 0.10 | a warning on 1 run in 10 |
| turns | 0.02 | the turn gate cuts 1 run in 50 |
| hard.agent, hard.prompt, hard.session | 0.01 | a deny on 1 run (prompt, session) in 100 |

Settled by the user on 2026-10-03 (v1 proposed 5 % / 1 % / 0.5 %).

### 5.2 §1 floors and ceilings as prior bounds

The floor and ceiling bound the decision, not the demand: demand above a ceiling is real but is observed only as a censored value. The limit's posterior is truncated to [f, g], so the decision is clamp(T, f, g) and the stored interval is [max(lo, f), min(hi, g)] with `at_bound` set when clamped. For the single-level scopes the seed-anchored prior (3.5) is additionally centred inside [f, g]. Ceilings that are frontmatter maxTurns stay the backstop (turns never rise above them).

### 5.3 Pins

- soft.prompt.<type> (orchestrator 80M): seed = floor in stack_limits_seed.json, so the clamp makes 80M a hard floor; enforce_invariants never lowers it (existing code path).
- Fan-out 32 and every fixed guard: not variables (section 4, last paragraph).
- Env overrides: snapshot_values keeps env > frozen > live, so an env value is exactly what the session uses and the learner never lowers it. The learner keeps updating live.json underneath (history shows it); `show` prints both. (Floor semantics, max(env, learned), would raise a user's deliberately low budget cap: rejected; open question 10.2 only if the user meant floor semantics.)
- frozen / hold / rollback: unchanged.

### 5.4 Movement (replaces §4 target() and dead band; keeps the step, damping and invariants)

Per variable at SessionStart, with c = current live value, status from section 6:
1. Gate failed or no Bayes entry for this evidence id: run the existing §4 decide() unchanged (method = empirical).
2. status prior (no own rows): hold. hard.* and turns: move only when supported (own n >= 5 from >= 3 agents, today's rule).
3. c unset: set to clamp(T) when supported (soft.agent: also pooled), as today.
4. Risk dead band: no change while r/2 <= p_hit(c) <= 2r, or |T - c| <= 10 % c. This replaces delta = max(0.10, w/2) and the FT(c) > 10 % / tight >= 1 / c/hmax > 1.5 / missed >= 1 direction tests, which were frequentist proxies for the same question.
5. Tightening a deny-type variable (hard.*, turns): T <- max(T, min(c, hmax_healthy)) (kept from §4).
6. Step x = clamp(T, c(1 - 0.25 d), c(1 + 0.25 d)), damping d as §4 (reversal halves, three same-sign/dead doubles), rounding toward c, clamp [f, g], pins, then enforce_invariants (unchanged).
Values change only here, once per session id (U4); propose/fit runs write inputs only.

## 6. Gates and the fallback chain

Model gate (per fitted model): max R-hat <= 1.01 over every free parameter, bulk and tail ESS >= 400, 0 divergences after tuning, E-BFMI > 0.3. Quantity gate (per variable): R-hat <= 1.01 and bulk/tail ESS >= 400 of the per-draw T draws. Support: own n >= 1 for any Bayes move; deny-type moves need supported. Grid tier gate: posterior mass in the two edge cells < 1e-3 and the hyperparameters' source fit passed its own gate.

Chain, per variable, evaluated in apply_and_snapshot:
1. bayes.json (sampler) with evidence_id == proposals.evidence_id, its model gate and the variable's quantity gate passing -> method `bayes-nuts`.
2. else the proposals entry's stdlib grid block (`bayes_grid` computed in propose(), conditional on the last gated sampler's hyperparameters, or on stdlib moment hyperparameters when none) with its grid gate passing -> method `bayes-grid` (open question 10.3: allow this tier or go straight to §4).
3. else §4 decide() on the same proposals entry -> method `empirical`.
4. Single-level scopes below support: hold (the current value), method `empirical(hold)`.

## 7. Provenance and intervals

### 7.1 Per-variable block `bayes` (same shape in bayes.json vars, proposals.json vars.<v>.bayes, live.json vars.<v>.bayes)
```
{"method": "bayes-nuts" | "bayes-grid" | "empirical", "model": "turns-nb2s-h3" | "ctx-ln-h3" | "scope-ln-anchored-1",
 "risk": 0.05, "T": 4400000, "pi90": [3100000, 6300000], "at_bound": false,
 "qtab": {"p": [0.5, 0.8, 0.9, 0.95, 0.975, 0.99, 0.995, 0.999], "x": [...]},      # predictive quantiles: p_hit(c) by log-linear interpolation
 "status": "supported" | "pooled" | "prior", "n": 31, "n_cens": 1, "agents": 26, "sessions": 2, "shrink": 0.83,
 "diag": {"rhat": 1.002, "ess_bulk": 1810, "ess_tail": 1490, "model_gate": true, "edge_mass": null},
 "fit": "<fit_id>"}
```
`shrink` = 1 - posterior sd(eta_t) / prior sd(eta_t | class) (how much the type's own data moved it). `fit_id` = first 16 hex of sha256(evidence_id, model ids, seed, versions).

### 7.2 bayes.json (new, state dir limits/, written by the sampler, read by apply)
```
{"schema_version": 1, "generated": iso, "evidence_id": <64 hex = proposals.evidence_id>, "seed_sha": <seed sha>,
 "fit_id": <16 hex>, "code": "stack_bayes/1", "versions": {python, pymc, pytensor, nutpie, arviz, numpy, scipy, pandas},
 "seed": 20261003, "chains": 4, "draws": 2000, "tune": 1500, "risk": {...}, "data": {"files": {name: sha256}, "rows": n},
 "models": {"turns": {"diag": {...}, "gate": true}, "ctx": {...}, "spc": {...}, "static_cc": {...}, "ctx_ab": {...}},
 "hyper": {"turns": {"tau_t", "tau_new", "rho", "p_resume", "types": {t: {"mu", "scale"}}}, "ctx": {...}},
 "vars": {"<var>": <7.1 block>},
 "sched": {"types": {t: {turns S/M/L, band, sec_per_call, ctx a/b, static_cc, run_pi}}, "pools": {...}}}
```
Validation on read (mirrors validate_proposals): schema, 64-hex ids, every name in the seed and none a fixed guard (else the file is ignored whole), finite numbers inside [0, CTX_MAX] / [0, TURNS_MAX], qtab monotone, risk equal to the code's RISK (else ignored: a stale policy).

### 7.3 live.json
Schema 2: each variable gains `bayes` (7.1 block or null) and `method`. Migration `_migrate_1` adds both as null and keeps the schema-1 copy as live.v1.json (existing mechanism). validate_live must carry the block through (today it rebuilds each state from known keys and would drop it). history.jsonl records gain method, T, pi90, risk, p_hit_c, fit_id.

### 7.4 Snapshot
Stays schema 1 (the guard's lean reader checks schema_version == 1 and hashes every other key). Additive key `prov`: {var: {method, T, pi90, risk, p_hit, fit_id}}, covered by the hash. `values` and `origin` unchanged, so the guard, stack_sched and session-env need no change.

### 7.5 proposals.json
Unchanged entries (x, ci, n, ...) plus `bayes` per variable (the grid tier) and top-level `bayes_hyper_source`: "fit:<fit_id>" or "stdlib-moments". _valid_entry keeps a validated `bayes` block.

## 8. Scope 2 model (provisional; final fit after B0 grading)

Graded unit i: v2, one graded run (install x prompt x variant) from stats_before v1.1's runs_before.csv. v1 used the first root run of each prompt id, which mis-pairs once a prompt has been run on two installs. For each unit: agent a (the agent that ran, including fallbacks), task family f (prompts.csv family), size class k (S/M/L), match m = 1 when the agent is the prompt's target, install n_i = 1 for the new install. Grades outside fail/partial/pass (tool-absent) are excluded, never imputed. Every unit's grade is cross-checked against the grade files: baseline_grades + grades_T8b for the old install, grades_b0v2 keyed by (id, variant) for the new one.
```
y_i in {fail, partial, pass} ~ OrderedLogistic(eta_i, cutpoints c1 < c2)
eta_i = u_a + v_f + beta m_i + gamma_k + delta n_i          delta ~ N(0, 0.5) (v2: the new install is another stack version)
u_a = tau_pool z_pool[pool(a)] + tau_agent z_agent[a]; v_f = tau_fam z_fam[f]
tau_* ~ HalfNormal(0.5); beta ~ N(0, 0.5); gamma ~ ZeroSumNormal(0.5); c ~ N([-3, -1], 1), ordered
```
Outputs: P(pass) and P(>= partial) per (agent, family) cell and per agent marginal, 90 % ETI; P(agent a best in family c) from the draws; the conjugate cross-check is a Beta(1, 1)-binomial pass rate per agent. With 22 graded ids and no fail grade, the lower cutpoint is prior-driven and every cell interval is wide; Q2 routing rules must not be applied from this fit (gate: n >= 5 graded per compared cell). The routing decision rule for B2: choose a for class c maximising E[U] = P(pass | a, c) - lambda E[tokens | a] over posterior draws, lambda per profile (cheap/fast/accurate), and change routing only when P(a beats the current choice) >= 0.9.

## 9. Integration contract

### 9.1 Where each part runs
| part | runtime | file |
|---|---|---|
| censoring flags, grid posteriors (NB, log-normal), predictive quantiles, qtab, p_hit, moment hyperparameters, seed-anchored scopes, NIG fixer | stdlib, Python 3.9, inside `stack_limits.propose()` (detached, /usr/bin/python3) | new `dot-config/dot-claude/hooks/stack_bayes_grid.py` (from b1/bayes_grid.py) imported by stack_limits |
| hierarchical NUTS fits (turns, ctx, spc, static_cc, ctx_ab, tool_calls, resume_ctx, scope 2), gates, bayes.json, sched block | stack venv Python 3.13 with pymc/nutpie/arviz, detached, at collector exit after propose | new `dot-config/dot-claude/hooks/stack_bayes.py` (from b1/fit_prototype.py, minus report/backtest) |
| decision (5.4), provenance into live/snapshot | stdlib, inside apply_and_snapshot under limits.lock, <= 300 ms (reads two JSON files) | stack_limits.py |
| scheduler model refresh from the posterior | uv script (pandas), as today | stack_sched_refresh.py |

### 9.2 Data flow (U4 unchanged)
collector exit: final scan -> `propose()` (stdlib: proposals.json incl. grid blocks, evidence E) -> `bayes_fit()` (venv: bayes.json for E) -> `refresh()` (uv: candidate sched_model.json, from bayes.json sched block when its evidence is E and gated, else today's combine). Next SessionStart: apply_and_snapshot reads proposals.json + bayes.json (same E) -> live.json v+1 -> snapshot (values, origin, prov) -> session-env / guard / stack_sched read the snapshot only.

### 9.3 Functions to add or change
stack_limits.py:
- `RISK`, `BAYES_GATE`, `NEAR = 0.5` constants; `SCHEMA = 2` for live.json only (snapshot and proposals stay 1) with `_migrate_1`.
- `censor_flags(row, family, limits_in_force)` (3.2) used by `_entry` (replaces `base()`'s exclusion: censored rows are kept and flagged, capped at MAX_X as today).
- `_entry`: add `cens` (list parallel to x), `resume`, `session` index per value so the grid can use them; keep x/ci/prob for §4.
- `bayes_grid_block(entry, hyper, family, spec)` -> 7.1 block (calls stack_bayes_grid).
- `load_hyper()` -> hyperparameters from the last gated bayes.json (same seed_sha) else `hyper_moments(rows)`.
- `build_proposals`: attach `bayes` blocks; top-level `bayes_hyper_source`.
- `_valid_entry` / `validate_proposals`: keep and validate `bayes`.
- `load_bayes(seed, evidence_id)` -> validated bayes.json vars or None (7.2 rules).
- `decide()`: new branch `decide_bayes(name, spec, st, block, ent, pool, soft_ref, now)` implementing 5.4 steps 1-6 (prototype: fit_prototype.decide_bayes, without damping state) and falling back to the current body.
- `apply_proposals(seed, live, props, bayes=None, ...)`: pass the block per variable; record method, T, pi90, p_hit in history.
- `_var_state`, `validate_live`: carry `bayes`, `method`.
- `_write_snapshot`: add `prov`.
- `show` / `status_line` / `stability_lines`: print method, T [pi90], p_hit(c).
- `maybe_spawn_propose`: unchanged (stdlib only).
stack_usage.py: `bayes_fit(trigger, session)` between propose_limits() and refresh(), run as `<venv>/bin/python stack_bayes.py --usage DIR --out limits/bayes.json` with `PYTENSOR_FLAGS=base_compiledir=<state>/pytensor,cxx=,mode=NUMBA` and `NUMBA_CACHE_DIR=<state>/numba` (the C linker fails on this macOS: clang rejects `-ld64`, verified in the prototype; the home directory is not writable from the sandbox), timeout 900 s, a lock, record in usage/bayes.json.rec like refresh.json; skipped (status recorded) when the venv lacks pymc.
stack_sched_refresh.py: `load_bayes_sched(path, evidence_id)`; `refresh()`: if present and gated, target = bayes sched block (types and pools), else today's `combine()`; `bounded()` and `rounded()` unchanged; `refresh` record gains `method` ("bayes" | "combined") and `fit_id`.
stack_sched.py: no change needed (status "prior" already maps to provisional; band/run_interval schemas kept). Optional: `limit_checks` reads the snapshot's turns.<type> instead of frontmatter maxTurns.
derive_sched_model.py: unchanged (empirical fallback and parity fixture).
install.sh / requirements: add `pymc==6.3.2 nutpie==0.16.11 arviz==1.3.0` (and their pins: pytensor 3.3.3, numba, llvmlite, xarray) to requirements/sci.in, re-lock sci.txt with hashes; doctor line "bayes: venv ok | missing". (User step.)

### 9.4 Tests the integrator must add (tests/test_stack_bayes.py unless noted)
- B1-T1 grid vs reference: stdlib NB and log-normal grid quantiles equal scipy's (sharp prior) and match the NUTS fit's T within 15 % on the frozen fixture for supported types.
- B1-T2 stdlib only: AST scan of stack_bayes_grid.py and stack_limits.py for third-party imports; import under /usr/bin/python3 3.9.
- B1-T3 hostile bayes.json: NaN/inf/negative, non-monotone qtab, wrong evidence_id, other risk table, a fixed-guard or unknown name (whole file ignored) -> §4 path, no exception.
- B1-T4 gate fallback: an entry with rhat 1.02 or ess 300 or a model with 1 divergence -> method empirical, value = §4 decide's.
- B1-T5 prior holds: a type with no own rows never moves; hard.* and turns never move unless supported.
- B1-T6 censoring rule: one row per table line of 3.2 -> expected flags (turns and ctx separately), incl. the status_code-1 proxy switching off when hit_* are measured.
- B1-T7 pins: soft.prompt.orchestrator never below 80M under 10k random blocks; env override origin "env" and value exact; no FIXED_GUARDS name in bayes.json/live/proposals.
- B1-T8 step bound: T2, T3, T17 re-run with random Bayes blocks: |x - c| <= 0.25 d c before the clamp, values in [f, g], invariants hold.
- B1-T9 U4 (extends T21): rewriting bayes.json mid-session changes nothing a running session reads; a new sid applies it once.
- B1-T10 provenance: snapshot `prov` is hashed, the guard's read_limits_snapshot accepts it (schema 1); live.json migration 1 -> 2 keeps live.v1.json.
- B1-T11 determinism: same CSV copy + seed -> identical bayes.json except `generated` (sampler side, tolerance 0 on T with the pinned stack). Caveat from the v2 prototype: with the same seed, code and data, the turns and ctx fits gave different draws in different processes (v1 run vs v2 attempt 1 on ctx: R-hat 1.0075 / 0 divergences vs 1.0113 / 1). spc, static_cc, tool_calls and ctx(n) reproduced exactly across runs. Cause unverified (candidate: NUMBA-mode kernels compiled differently with the compile cache's state). T11 must first establish whether tolerance 0 is attainable, and the gate must not rely on bit reproducibility.
- B1-T12 latency: apply_and_snapshot p95 <= 300 ms with 170 Bayes blocks (T20 extended).
- B1-T13 refresh: stack_sched_refresh with a bayes sched block writes a model stack_sched.load_model accepts; without it, output equals today's.
- B1-T14 (verifier) rolling-origin calibration: per family, realised cap-hit rate's 90 % Jeffreys interval contains r, PIT KS p > 0.05, 90 % interval coverage in [0.8, 0.97]; reported against §4 on the same folds (fit_prototype.backtest is the reference implementation).

## 10. Open design questions (the spec leaves these undecided)
1. Risk targets r per family (5.1): settled by the user (2026-10-03): 10 % soft, 2 % turns, 1 % hard.
2. Env override: settled by the user: exact (as today).
3. Fallback chain: settled by the user: the stdlib grid tier only for soft limits (soft.agent, soft.prompt[.type], soft.session); hard.* and turns go NUTS -> §4.
4. Collector: fill `hit_*` (limit-hits.jsonl folding), `window_ctx` and the session row; until then the prompt/session scopes cannot learn and the status_code-1 proxy (3.2) stands in for limit stops.
