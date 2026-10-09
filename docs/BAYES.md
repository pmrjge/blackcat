# Bayesian tuning of the stack's learned values

Status: design v3 and integration contract, 2026-10-08 (WP0b, WP1a of the Bayesian-tuning program). Nothing here is
wired yet. §A.8, §A.9 and §2 are the contract WP3a (stdlib limits), WP3b (detached fitter), WP4 (scheduler) and WP7
(fan-out advice) implement; a change to a schema or a test id below is a change to this file first.

Reference material, all tracked:
- `docs/bayes/b1v2/`: the B1 v2 design, fit report, prototype (`fit_prototype.py` with its uv lock), the stdlib grid
  tier `bayes_grid.py`, and the v2 output tables. Sanitized copies; every edit is listed in `docs/bayes/b1v2/README.md`.
  "v2 §x" below means `docs/bayes/b1v2/design.md` section x.
- `tests/fixtures/bayes/b1v2/`: the frozen data of the v2 fit (agent, main and session rows; scope-2 grades; the
  limits state of that day), ids hashed, free text dropped, with `SHA256SUMS` and `EVIDENCE.json`.

Paths: hooks are in `dot-config/dot-claude/hooks/`, the state directory is `$XDG_STATE_HOME/claude-agent-stack`
(default `~/.local/state/claude-agent-stack`), called `<state>` below. Line numbers are at main `d6046693`.

Every model section states **priors, likelihood, gate, decision, fallback** in that order.

---

## 0. Decision record

- **Reversal.** On 2026-10-07 the user asked for Bayesian tuning "for everything that needs it or justifies it like
  the number of spawned subagents, parallel swarms of homogeneous agents" (`.claude-work/bayes/plan.md`, Decision
  record). This reverses the 2026-10-04 backlog line on swarms: "Learned/bayesian tuning is retired"
  (`.claude-work/lost-features/rescue/W_claude-work/backlog.md:45`).
- **Kept from 2026-10-04:** "MEASURE BEFORE TUNING: instrument first [...] no tuning of widths/thresholds/schedulers
  until data exists. Swarm width function stays but is not tuned before measurement." (same `backlog.md:9`). It
  becomes the support gates, shadow mode and the designed pilots below: no value acts until data that was not shaped
  by the value itself supports it.
- **Kept from 2026-10-03:** the decision order "Bayesian inference for ALL learned values (scope 1 limits/scheduler,
  scope 2 routing/quality), then Pareto optimization, then README last." (`git show 44c9fd5:RESUME.md`, line 36).
- **Kept, the user's 2026-10-03 answers** (v2 §10): risk targets soft 10 % / turns 2 % / hard 1 %; env overrides exact
  (an env value is what the session uses; the learner never lowers it); the stdlib grid tier for soft limits only;
  the collector fix that measures `hit_*`, `window_ctx` and the session row (commit `697a685`).
- **The user's decisions of 2026-10-07** (`.claude-work/bayes/plan.md`, "USER DECISIONS 2026-10-07"):
  - Q1: "Empirical keeps deny-type values (turns, hard.agent/prompt/session); Bayes shadow-only until ~300 scorable
    rows per family." → §3.2, §A.7.
  - Q2: "Advice only for fan-out and swarm width (logged shadow term plus plan/prompt text; static caps unchanged)."
    → §C.
  - Q3: consent to pilot P1 (cap ≤ $40) and P2 (cap ≤ $200); "the user runs them, not agents; agents must still stop
    and ask before any actual spend if the cap or design changes." → §C.6, §E.6.
  - Q4: "amend equilibrium now, before p data, so p's selection uses the Bayesian expected-utility rule; q's Holm
    tests unchanged." → §D.6 (draft amendment text; applying it is WP8).
  - Q5: stack_sched, stack_sched_refresh and stack_fanout stay. → §B, §C.
- **The T4a plan-review of v2** (`.claude-work/lost-features/rescue/T4a_review.md`, VERDICT fail, 2 BLOCKING design-text
  fixes) is applied in full in §A; its numbers are re-derived on the tracked fixture in §A.10.
- **Since the plan** (CONFIG.md §9, 2026-10-08): `soft.prompt.orchestrator` is user-set at 140M (seed = floor =
  ceiling) and `hard.prompt` at 300M (seed = floor = ceiling). The clamp to [floor, ceiling] makes both immovable by any
  learner, so L5 and L6 below are computed and reported, never moved. The plan's "80M pin" reads "140M pin" here.

---

## 1. Common model

### 1.1 Families, risk targets, support

| family | variables | risk r (P(new run's demand > limit)) | kind | may act (Q1) |
|---|---|---|---|---|
| soft.agent | `soft.agent.<type>` | 0.10 | soft | yes, after promotion |
| soft.prompt | `soft.prompt`, `soft.prompt.<type>` | 0.10 | soft | yes (`.orchestrator` is pinned: no-op) |
| soft.session | `soft.session` | 0.10 | soft | yes, after promotion |
| turns | `turns.<type>` | 0.02 | deny (hard) | **shadow only** |
| hard.agent | `hard.agent.<type>` | 0.01 | deny | **shadow only** |
| hard.prompt | `hard.prompt` | 0.01 | deny | **shadow only** (pinned 300M: no-op anyway) |
| hard.session | `hard.session` | 0.01 | deny | **shadow only** |

`RISK` in code holds exactly these seven keys (`soft.prompt.<type>` uses `soft.prompt`'s r).

**Support** of a type variable is today's predicate, evaluated by apply on the validated proposals entry, never read
from a fitted file: `classify(fam, ent, pool)[0] == "supported"` (`stack_limits.py:1091`; own n ≥ 5 from ≥ 3 agents,
or n ≥ 3 from ≥ 2 agents with CI width / p90 ≤ 0.35, current regime). Prompt scope: ≥ 30 windows from ≥ 3 sessions;
session scope: ≥ 5 sessions (`support`, `:495`). **Strata** for calibration: *supported* (support holds) and *sparse*
(it does not); the frozen-fixture backtest uses n_train ≥ 5 vs < 5, which is what T4a scored.

### 1.2 Hierarchy (v2 §3.3 plus a regime effect)

For a quantity q, row i of type t in session s, resume flag r_i, regime g_i (the 16-hex `regime` column):

```
lin_i = eta_t + tau_s z_s[s] + tau_ts z_ts[t,s] + rho r_i + tau_g z_g[g_i]
eta_t = a0 + b_fam[model family of t] + g zmt_t + u_pool[pool(t)] + tau_t z_t      (every type non-centred)
```

Priors (v2's priors, never v2's posterior: the live window contains the frozen rows, so a posterior-as-prior would
count them twice):
- a0 ~ N(log c_q, 1.5), c_q = 10 calls (turns), 1M tokens (ctx), 15 s per call (spc), 30k tokens (static_cc);
- b_fam ~ ZeroSumNormal(0.5) over {opus, sonnet, ...}; g ~ N(0.5, 0.5) on zmt_t = log maxTurns_t − mean;
- u_pool ~ ZeroSumNormal(0.7) over pools with ≥ 2 member types (one-type pools have none);
- z_s ~ ZeroSumNormal(1) over sessions; z_g ~ ZeroSumNormal(1) over the window's regimes (identically 0 with one
  regime: constant by construction); z_t, z_ts ~ N(0, 1); rho ~ N(0, 0.5);
- group scales: Gamma(2, 2/m) (boundary-avoiding, mean m) on tau_t, tau_s, tau_ts for turns and ctx, on tau_s, tau_ts
  for tool_calls (HalfNormal on its tau_t, v2 attempt 2); HalfNormal(sd) with m = sd·sqrt(2/pi) elsewhere, sd = 0.7
  (tau_t), 0.3 (tau_s), 0.5 (tau_ts);
- **new:** tau_g ~ Gamma(2, 2/0.3). With one regime in the window z_g is constant by construction (§A.4) and the term
  drops out. Prediction is for the current regime: its z_g when it has rows, else a new draw tau_g·N(0, 1), integrated like the new-session effect.
- scale: log sigma_t (log-normal) or log alpha_t (NB) = pool level N(0, 0.5) or N(0.7, 0.75) + tau_l z_t, tau_l ~
  HalfNormal(0.3).

New-session predictive: a run in the next session gets w ~ N(0, sqrt(tau_s² + tau_ts²)) integrated (Gauss-Hermite, 7
nodes, for the NB; analytic for the log-normal), and the resume mix at the window's observed resume share.

### 1.3 Models

| model id (bayes.json) | quantity, rows | likelihood | outputs |
|---|---|---|---|
| `turns-nb2s-h4` (M1) | api_calls, agent rows | shifted NB2: y − 1 ~ NB(mu, alpha_t), censored rows log P(Y ≥ y) | L1, S1, S2 |
| `ctx-ln-h4` (M2) | ctx, agent rows | log-normal, censored rows log Φ((lin − log y)/σ) (LOO beat gamma: Δelpd 16.8, SE 5.3) | L2, L3 |
| `spc-ln-h4`, `static_cc-ln-h2`, `ctx_ab-kq-h2`, `resume_ctx-t-1`, `tool_calls-nb2s-h4` (not fitted by WP3b, §1.3) (M3) | as v2 §4 S3–S11 | as v2 | S3–S11 |
| `scope-ln-anchored-1` (M4) | window_ctx (main rows), session ctx (session rows) | log-normal, single level, seed-anchored grid (stdlib) | L4–L8 |
| `grades-ord-1` (M5) | graded runs | ordinal logit | Q1, Q2 (§E) |
| `width-1` (M6) | per-child wall, failures, rate limits | §C | advice |
| `eq-n-1` (M7) | eq member-subset scores | §D | N*, rounds* |
| `stop-logit-1` (M8) | early-stop windows | §F | report |

`h4` = v2's `h3` hierarchy plus the regime term. Sampler (`stack_bayes.py` `CHAINS`, `DRAWS`, `TUNE`): nutpie NUTS,
8 chains × 4000 draws after 2000 tuning, `cores=8`, target_accept 0.98, seed 20261003, all recorded in
`sampler` (T4a LOW fix: v2 §7.2's "2000 / 1500" is replaced). Why 8 × 4000: the quantity gate's MCSE(T)/T ≤ 2 %
(A.4) binds at the extreme quantiles. On the WP2 copy (2026-10-09; 975 agent rows, 20 sessions) the hard.agent
blocks above 2 % were 46/57 at 4 × 3000 (WP2), 10/57 at 8 × 3000 (median 1.86 %) and 1/57 at 8 × 4000 (median
1.65 %); soft.agent 0/57 at both 8-chain settings. Wall time 276 s vs 348 s (§H). Cost of more draws: the model
gate's `divergences == 0` is stricter on more draws (turns and ctx each had 2 divergences in 24000 draws and 3 in
32000, about the same rate).

WP3b fits `turns-nb2s-h4`, `ctx-ln-h4` and the other M3 models but not `tool_calls-nb2s-h4`: nothing reads it (no
§2.1 variable and no §2.2 key comes from it), and it took 113–116 s of WP2's NUTS time.

---

## 2. Files, schemas, validation (the contract)

All under `<state>`; the state directory is sandbox `denyWrite` for agents. Writers write atomically
(`stack_io.write_atomic`). Readers treat every file as untrusted.

| file | writer | reader | when |
|---|---|---|---|
| `limits/bayes.json` | `stack_bayes.py` (WP3b, venv, detached) | `stack_limits.load_bayes`, `load_hyper` (WP3a); `stack_sched_refresh.load_bayes_sched` (WP4) | written after `propose()` at collector exit; read at SessionStart apply |
| `usage/bayes.json.rec` | `stack_usage.bayes_fit` (WP3b) | `bayes_fit` (rate limit), `stack_usage.py status`; doctor (WP3c) | one record per fit attempt or skip past the lock (§2.8) |
| `limits/advice.json` | `stack_bayes.py --advice` (WP7c) | `stack_fanout` report and shadow term, `stack-budget plan` | after a width fit or a prior-only build |
| `limits/proposals.json` | `stack_limits.propose` | apply | gains `bayes` blocks and two top-level keys (§2.3) |
| `limits/live.json` | apply | apply, `show` | schema 2 (§2.4) |
| `limits/snapshots/<sid>.json` | apply | guard, session-env, stack_sched | schema 1 plus `prov` (§2.5) |
| `limits/history.jsonl` | apply | `show`, reports | records gain fields (§2.6) |

### 2.1 `limits/bayes.json` (schema_version 1)

```
{"schema_version": 1,
 "code": "stack_bayes/1",
 "generated": "2026-10-08T12:00:00Z",
 "evidence_id": "<64 hex>",                 # stack_limits.evidence_id over the rows the fit read
 "seed_sha": "sha256:<64 hex>",             # stack_limits.load_seed()["sha"] of the seed the fit read
 "fit_id": "<16 hex>",                      # sha256(evidence_id, sorted model ids, sampler seed, versions)[:16]
 "risk": {"soft.agent": 0.1, "soft.prompt": 0.1, "soft.session": 0.1, "turns": 0.02,
          "hard.agent": 0.01, "hard.prompt": 0.01, "hard.session": 0.01},
 "sampler": {"seed": 20261003, "chains": 8, "draws": 4000, "tune": 2000, "target_accept": 0.98},
 "versions": {"python": "3.13.x", "pymc": "...", "pytensor": "...", "nutpie": "...", "arviz": "...",
              "numpy": "...", "scipy": "...", "pandas": "..."},
 "data": {"rows": 320, "files": {"runs3.csv": "<64 hex>", ...}},
 "models": {"<model id>": {"gate": true,
                           "diag": {"rhat_max": 1.0034, "ess_bulk_min": 1841, "ess_tail_min": 1680,
                                    "divergences": 0, "ebfmi_min": 0.76,
                                    "constant": ["z_s"],          # excluded by name: zero spread in every chain
                                    "nan": []}}},                 # any other NaN R-hat/ESS: the gate fails
 "hyper": {"turns": {"tau_t": f, "tau_new": f, "rho": f, "p_resume": f,
                     "types": {"<type>": {"mu": f, "scale": f}}},
           "ctx":   {...same keys...}},
 "drift": {"<family>": {"ks_p": f, "sessions": int, "breach": false}},   # rolling PIT, last 5 sessions;
                                            # WP3b writes {} (no drift check yet, §H)
 "vars": {"<var>": <block>},
 "sched": <sched block> | null}
```

Per-variable `<block>` (also the shape of proposals' `vars.<v>.bayes` and live's `vars.<v>.bayes`):

```
{"tier": "nuts" | "grid",
 "model": "<model id>",
 "risk": 0.1,                               # == RISK[family]
 "T": 14200000,                             # rounded: turns ceil, ctx ceil2; hard.agent >= ceil2(2 x soft T)
 "T_raw": 14163401.2,
 "pi90": [9800000, 21000000],               # 5 / 95 % of the per-draw conditional quantile
 "qtab": {"p": [0.5, 0.8, 0.9, 0.95, 0.975, 0.99, 0.995, 0.999], "x": [8 numbers]},   # predictive quantiles
 "at_bound": false,
 "n": 31, "n_cens": 1, "agents": 26, "sessions": 2,
 "shrink": 0.83,                            # 1 - posterior sd(eta_t) / prior sd(eta_t | class); null for M4
 "status": "supported" | "pooled" | "prior",     # informational; apply recomputes support (§1.1)
 "diag": {"rhat": 1.002, "ess_bulk": 1810, "ess_tail": 1490, "mcse_rel": 0.006, "edge_mass": null}}
```

Validation (`load_bayes(seed, evidence_id)`, all or nothing unless stated):
1. Size ≤ 4 MiB; JSON parses (catch `ValueError`, `RecursionError`); top level is an object; `schema_version == 1`;
   `code` starts with `stack_bayes/`.
2. `evidence_id` matches `HEX64_RE` and equals the proposals' evidence id; `seed_sha` equals the loaded seed's `sha`;
   `fit_id` matches `HEX16_RE`; `risk == RISK` exactly (a stale policy drops the file).
3. Every key of `vars` is a seed variable and `is_fixed_guard()` is false for it; any name failing either drops the
   **whole file** (B1-T3). Likewise every type key under `hyper.*.types` and `sched.types` must be a seed type
   (`_types(seed)`) and every `sched.pools` key a seed pool, none a fixed-guard name.
4. Every number is finite (`math.isfinite`; Python's json accepts `NaN`/`Infinity` tokens, so check explicitly) and
   not a bool. `hyper.*.rho` and `hyper.*.types.*.mu` (log scale, signed) lie in [−50, 50]; `hyper.*.tau_t`,
   `tau_new` and `types.*.scale` in (0, 50]; `hyper.*.p_resume`, `risk.*` and `drift.*.ks_p` in [0, 1]; a block's
   `shrink` in [−10, 1] or null; `diag` values and counts ≥ 0. Every other number of a block (`T`, `T_raw`, `pi90`,
   `qtab.x`) lies in [0, CTX_MAX] for ctx variables and [0, TURNS_MAX] for turns variables. `qtab.p` equals
   `QTAB_P`; `qtab.x` has 8 entries, is non-decreasing and > 0; `pi90[0] ≤ pi90[1]`; `n_cens ≤ n`; counts are
   non-negative ints. **At the cap:** a block whose `T`, `T_raw`, `pi90[1]` or any `qtab.x` reaches the range's
   upper end (CTX_MAX, TURNS_MAX) must carry `at_bound: true`, else the whole file is dropped (`_norm_block`).
   The writer clamps there instead of failing: the ctx predictives of sparse types pass CTX_MAX = 1e10 (WP2), so
   `stack_bayes.make_block` clamps T, T_raw, pi90 and qtab.x to [0, cap] and sets `at_bound` when any value
   reached it (a soft T = ceil2(T_raw) rounds T_raw in (9.9e9, 1e10) up to exactly 1e10; the grid tier's
   `bayes_grid_block` flags the same way). A turns quantile beyond the type's sweep (max(400, 4 × its ceiling), at most KMAX 5000 < TURNS_MAX)
   is reported at the sweep's end with `at_bound: true` and `mcse_rel: null`, so it fails the quantity gate
   (rule 5): such a T would act as the ceiling (A.2 L1), never as a learned value.
5. Per-block acceptance (a failing block is dropped, the file kept): `tier == "nuts"`, `risk == RISK[family]`, the
   block's `model` names a model whose gate passes (rule 6), and the **quantity gate**: `rhat ≤ 1.01`,
   `ess_bulk ≥ 400`, `ess_tail ≥ 400`, `mcse_rel ≤ 0.02` (any of them missing or null fails).
6. **Model gate** (recomputed from `diag`, the `gate` flag alone is not trusted): `rhat_max ≤ 1.01`,
   `ess_bulk_min ≥ 400`, `ess_tail_min ≥ 400`, `divergences == 0`, `ebfmi_min > 0.3`, `nan == []`, and every name in
   `constant` is in the code's `CONSTANT_BY_CONSTRUCTION` set (`z_s`, `z_g`: zero-sum effects over a grouping
   that can have one level) (B1-T4, B1-T17).
7. Drift: blocks of a family with `drift.<family>.breach == true` are dropped (the family falls back to §4).
Returns `{var: block}` of the accepted blocks, or `None`.

`load_hyper(seed)` (used by `propose()` and by apply, stdlib): reads the same file with rules 1, 3, 4, 6 and 7 (a
breached family's grid blocks are not built) for the `turns` and `ctx` models, `fit_id` matches `HEX16_RE`, and
`seed_sha == seed["sha"]`; the evidence id may differ (the grid serves evidence newer than the last
fit). Returns `(hyper, "fit:<fit_id>")` or `(None, None)`. **There is no moment-hyperparameter path**: with
`(None, None)` `propose()` writes no grid blocks (T4a BLOCKING 2, B1-T16).

### 2.2 `sched` block of bayes.json (WP4)

```
"sched": {"model_gate": {"turns": true, "spc": true, "ctx_ab": true, "static_cc": true},
          "types": {"<type>": {"turns": {"S": q25, "M": q50, "L": q90},
                               "sec_per_call": {"p50": f, "p90": f},
                               "ctx": {"a": f, "b": f},
                               "static_cc": q10,
                               "band": {"level": 0.9, "method": "bayes", "n_ref": M,
                                        "turns": {"lo": f, "med": M, "hi": f},
                                        "sec_per_call": {"lo": f, "med": p50, "hi": f},
                                        "ctx": {"lo": f, "med": 1.0, "hi": f}},
                               "n_seg": int, "n_agents": int, "n_first": int,
                               "status": "supported" | "provisional"}},
          "pools": {"<pool>": {...same keys, no status...}},
          "resume_ctx": {"alpha": f, "gamma": f, "lo": [f, f], "hi": [f, f]},
          "fixer": {"reread": f, "lo": f, "hi": f, "level": 0.95, "n": int}}
```
Keys mirror `sched_model.json` (`types.<t>`, `pools.<p>`, `band`), so `stack_sched.load_model` takes them unchanged.
Valid only when every number is finite and positive and `lo ≤ med ≤ hi` per band quantity and `S ≤ M ≤ L`.

### 2.3 proposals.json additions (schema stays 1)

- `vars.<v>.b` (WP3a, §A.8.4): `{"y": [...], "cens": [0|1...], "resume": [0|1...], "sess": [int...]}`.
- `vars.<v>.bayes`: a §2.1 block with `tier: "grid"` (soft families only; built only when `load_hyper` returned
  hyperparameters).
- top level: `"bayes_hyper_source": "fit:<16 hex>" | null` and `"bayes_seed_sha": "sha256:<64 hex>" | null`.
`_valid_entry` keeps a `b` and a `bayes` block only when they validate (§2.1 rule 4; `b` lists of equal length
≤ MAX_X); `validate_proposals` drops every grid block unless `bayes_hyper_source` matches `^fit:[0-9a-f]{16}$` and
`bayes_seed_sha == seed["sha"]` (a `"stdlib-moments"` or absent source → no grid block → method `empirical`, B1-T16).

### 2.4 live.json schema 2

`LIVE_SCHEMA = 2` (live.json only); `SCHEMA = 1` stays for the seed, proposals and snapshots (T4a LOW; bumping
`SCHEMA` would break `read_snapshot` and the guard's `LIMITS_SCHEMA` check, `agent_guard.py:4781`). Each variable state
gains `"bayes": <block> | null` (the last block a decision used, live or shadow) and
`"method": "empirical" | "bayes-nuts" | "bayes-grid" | null`. `MIGRATIONS[1] = _migrate_1` adds both as null and sets
`schema_version` 2; `load_live_locked` already sets the old file aside as `live.v1.json` before writing. `validate_live`
and `_var_state` carry both (today `validate_live` rebuilds each state from known keys and would drop them).
`LIVE_SCHEMA` replaces `SCHEMA` at every live.json site: `live_from_seed` (:1293), `validate_live` (:1308, :1350),
`_migrate` (:1386), `read_live` (:1410, :1412), `load_live_locked` (:1455, :1456, :1459, :1484), `_bounds_notes`
(:1524). The seed (:567, :568, :590), proposals (:949, :1009, :1029) and snapshots (:1642, :1726) keep `SCHEMA`.
`validate_live` keeps a state's `bayes` block only when it passes §2.1 rule 4 (else null), and `method` only when it
is one of its four values.

### 2.5 Snapshot `prov` (schema stays 1)

```
"prov": {"bayes_mode": "off" | "shadow" | "on", "fit_id": "<16 hex>" | null,
         "vars": {"<var>": {"method": "...", "T": n, "pi90": [lo, hi], "risk": r, "p_hit": p, "would": n | null}}}
```
Only variables with an accepted block appear; `would` is the shadow decision's value when it differs from `values`.
`values` and `origin` are unchanged, so the guard, session-env and stack_sched need no change; the hash covers `prov`
(`snap_hash`; the guard hashes every key but `hash`, `agent_guard.py:4786-4792`).

### 2.6 history.jsonl records

Every record apply writes gains `"method"`; Bayes-informed records also `"T"`, `"pi90"`, `"risk"`, `"p_hit_c"`,
`"fit_id"`, `"tier"`. A shadow record is a separate line with `"method": "bayes-shadow"`, `"would"` (the value the
Bayes decision would have set), `"decision"` (its decision label) and `"applied": false`, written next to the
section-4 record of the same variable and apply.

### 2.7 `limits/advice.json` (schema_version 1, WP7c)

```
{"schema_version": 1, "code": "stack_bayes/1", "generated": iso, "fit_id": "<16 hex>" | null,
 "seed_sha": "sha256:<64 hex>",
 "source": "pilot-P1" | "prior",
 "evidence": {"ledger_sha256": "<64 hex>" | null, "waves": int, "widths": [int, ...]},
 "lambda": {"profile": "default", "time": f, "tokens": f, "failure": f},
 "advice": {"advice.width.<type>":   {"w": int, "w_pi90": [int, int], "cap": int, "p_rl_wave": f, "status": "fitted" | "prior"},
            "advice.swarm":          {"min_items": int, "w": int, "w_max": 16, "p_better": f},
            "advice.min_part.<type>": {"tokens": int, "wall_s": f}}}
```
Validation: names match `^advice\.(width|min_part)\.[a-z0-9][a-z0-9_.:-]{0,79}$` or equal `advice.swarm`; any
fixed-guard name (`is_fixed_guard`) or other name drops the whole file; every `w ≤ cap`, where `cap` must equal the
static cap the reader computes for that type (`STACK_MAX_FANOUT` / `DEFAULT_FANOUT_BY_TYPE`, `agent_guard.py:1214,
1463`) and `w_max ≤ 16`; integers ≥ 1; probabilities in [0, 1]; finite numbers. advice.json is a file, never an env
knob, so `FIXED_GUARDS` and the `FIXED_LIMIT_KNOBS` self-test are unaffected (Q2).

### 2.8 The fit run and `usage/bayes.json.rec` (WP3b)

`stack_usage.bayes_fit(trigger, force=False)` runs at a collector's exit (`session end`, `owner gone`, `idle`) after
`propose_limits()` and before the scheduler `refresh()`, and by hand as `stack_usage.py bayes [--force]`. In order:
`STACK_BAYES=off` → `skipped:off`; another fit holds `usage/bayes.lock` (non-blocking flock) → `skipped:locked`
(neither is recorded); no valid proposals evidence id → `skipped:no-proposals`; the last *attempt* (`ok` or
`failed:*`) had this evidence id → `skipped:same-evidence`, or is less than 6 h old → `skipped:rate` (`--force`
skips both); an equilibrium run is live (a `<state>/<session>/eq/<run>/` without `ended.json`, phase not
`result`/`cleaned`, written in the last 2 h; past 4096 entries: assumed live) → `skipped:eq-run`; the collector
cannot take `<state>/accel.lock` (`accel_acquire`: someone holds it, or it is not a regular file) →
`skipped:accel-lock`; no executable `<config>/venvs/tools/bin/python` → `skipped:no-pymc`; no `stack_bayes.py`
beside it → `skipped:no-fitter` (both release `accel.lock` at once). Otherwise the child is
`<venv python> -I -B stack_bayes.py fit` (`-B`: `-I` ignores `PYTHONDONTWRITEBYTECODE`, and no pyc may land in
the hooks folder), cwd `/`, its own session and process group, `nice` +10, stdin and stderr null, the
`usage/bayes.lock` and `accel.lock` fds inherited (a fit whose collector was SIGKILLed keeps both until it ends,
so neither a second fit nor another accelerator job starts beside it), the environment `refresh_env()` minus
every `PYTENSOR*`, `NUMBA_*`, `AESARA*`, `THEANO*` knob plus
`PYTENSOR_FLAGS=base_compiledir=<state>/bayes-cache/pytensor,cxx=,mode=NUMBA` and
`NUMBA_CACHE_DIR=<state>/bayes-cache/numba`; at 900 s the whole group is killed (`failed:timeout`), and so on a
SIGTERM to the collector while it runs (`failed:signal`; the collector's own handler then stops it as before).
**The fit's own cap.** `stack_bayes.py fit` arms `alarm(FIT_TIMEOUT_S)` = 930 s (`--timeout S`, 1 to 86400)
with SIGALRM at its default action, and disarms it on return. The kernel terminates the process whatever the
sampler's threads are doing (a Python handler would wait for a long C call to return). While the collector
lives, its 900 s kill comes first. A fit orphaned by a SIGKILLed collector ends itself at 930 s, and the kernel
drops both locks with its last fd. Only the fit process is terminated: a process it started itself would
survive. None is expected, since nutpie runs its chains as threads (unverified on a real fit, §H). Exit codes: 0
`ok`, 3 `skipped:no-pymc` (a Bayes dependency does not import: one line, no traceback, nothing written), 4
`skipped:no-rows` (< 10 agent rows or < 2 sessions), anything else `failed:exit <rc>`. A skip is not an attempt, so
the next exit tries again.

**`<state>/accel.lock`** is a convention (WP3b): any long job that saturates the Mac's GPU, ANE or CPU holds an
flock on it for its duration (rules: "one accelerator job per GPU or Mac"). The Bayes fit is its first holder
(work order step 9): 8 NUTS chains on 8 cores for about 6 minutes.
- **How the fit takes it.** `stack_usage.accel_acquire(holder)` opens the file read-write without following a
  link. It creates the file 0600 when absent. It opens with `O_NONBLOCK`, so a FIFO cannot block it, and takes a
  regular file only. It then takes `LOCK_EX|LOCK_NB`. Once it holds the lock, it writes one JSON line into the
  file: `{"holder": "bayes-fit", "pid": <the collector>, "since": <epoch>}`. The line is informative only; the
  flock is the lock.
- **Fail closed.** Held by anyone, or not openable as a regular file (a link, a FIFO, a directory) →
  `skipped:accel-lock`.
- **How long it holds it.** The collector holds the fd from the check to the end of the fit, so no gap lies
  between test and use. The fit inherits it. The kernel drops the lock when the last fd closes, on any exit,
  SIGKILL included, and so at the latest at the fit's own 930 s cap.
- **Testing it.** `flock_held` (open read-only without following a link, `LOCK_EX|LOCK_NB`, release; it never
  creates the file) tests the lock without taking it.
- **Other jobs.** Another job adopts the convention the same way: take the flock non-blocking and skip or wait
  while it is held.
- **Sandbox.** Agents cannot read the lock from the sandbox (`<state>/**/*.lock` is read-denied). The
  collector is started by a hook rather than an agent's shell, so it is not under that sandbox (unverified on a
  live install).

One record per run that got past the lock (JSON, sorted keys, one line, the last 400 kept; the reader reads the
last 256 KiB and drops lines that do not parse to an object):

```
{"ts": 1791504000.0,                       # epoch seconds, 3 decimals
 "trigger": "session end",                 # the collector's reason or "manual", ≤ 40 chars
 "status": "ok" | "skipped:<why>" | "failed:timeout" | "failed:signal" | "failed:exit <rc>",
 "rc": 0 | null,                           # null: timeout or not run
 "evidence_id": "<64 hex>" | null,
 "secs": 347.8 | null,                     # child wall time
 "summary": "bayes: fit <fit_id> rows … accepted … total_s …" | null,   # the child's last "bayes: " line, ≤ 288 chars
 "fit_id": "<16 hex>" | null,              # ok only: from the bayes.json just written
 "gates": {"<model id>": true, ...} | null}  # ok only: stack_limits.model_gate recomputed from diag
```

`stack_usage.py status` ends with "last bayes fit: <the last record's status>". The child's other output is
discarded.

### 2.9 Installing the fitter's packages and the doctor line (WP3c)

`./install.sh --with-bayes` is opt-in. It syncs the tools venv from `requirements/tools-bayes.txt` instead of
`tools.txt`. The rest of the install is unchanged.
- **The lock.** `tools-bayes.txt` is compiled from `tools-bayes.in` (`-r tools.in` plus pymc 6.3.2, pytensor 3.3.2,
  nutpie 0.16.11, arviz 1.3.0, scipy 1.18.1). It uses the repo's tools command plus `-c requirements/tools.txt`,
  with the 7-day cooldown (`--exclude-newer 2026-10-02T00:00:00Z`; command in `requirements/README.md`).
  - Hashes and Python: every package is hashed, Python 3.13, arm64 wheels only. Every package it shares with
    `tools.txt` has the same pin.
  - Pins: equal to the prototype's lock except pytensor. Its 3.3.3 was published 2026-10-02T14:13Z, inside the
    cooldown, so the lock pins 3.3.2 (pymc 6.3.2 accepts `>=3.2.2,<3.4`).
  - Re-lock: on or after 2026-10-10 the lock can move to 3.3.3, the version the WP2 and WP3b fits ran on.
    `fit_id` hashes the versions, so a refit on another version gets a new id.
- **Vulnerability scan.** pip-audit 2.10.1 on 2026-10-09, run through `uvx` (uv's cache only, nothing
  installed into the stack). It used the PyPI advisory feed, because the sandbox refused `api.osv.dev`.
  - Result: 76 packages; no known vulnerability, in this lock or in `tools.txt`.
  - History: the first lock (on the older `tools.txt`) carried `pyjwt` 2.14.0 (via `mcp`), with two advisories,
    PYSEC-2026-4141 / CVE-2026-101918 and PYSEC-2026-4183 / CVE-2026-102275, fixed in 2.15.0. The re-lock on the
    merged relock-tools `tools.txt` (same cutoff) moved the 6 shared pins that changed (cryptography 50.0.2,
    pyjwt 2.15.1, python-dotenv 1.2.4, sse-starlette 3.5.0, starlette 1.7.0, uvicorn 0.54.0) and cleared them.
- **Shadow only.** Nothing installs these packages by default, and installing them changes no limit:
  `STACK_BAYES` defaults to `shadow` (§3.1) and `BAYES_LIVE` is empty (§3.2). With the packages present, the
  collector's fits write `limits/bayes.json`, which feeds only `bayes-shadow` records.
  - A later run without `--with-bayes` syncs `tools.txt` (the same shared pins). It leaves the Bayes packages in
    place and says so.
  - `STACK_BAYES=off` stops the fits. `uv pip sync --python <config>/venvs/tools/bin/python --require-hashes
    --only-binary :all: requirements/tools.txt` returns the venv to the base lock exactly. Uninstalling only
    pymc, pytensor, nutpie and arviz would leave the other 24 of the lock's 28 Bayes-only distributions
    (2026-10-09), among them scipy, numba, llvmlite, xarray, zarr, pyarrow and setuptools; doctor would then
    say `venv missing` and a plain install would name none of them.
  - Under `--no-deps` the flag does nothing, and the installer prints one line saying so.
- **`doctor.sh`.** One line after the ML venv's. It reads distribution metadata only: importing pytensor
  would write a compile cache under `~`.
  - `bayes: skipped (STACK_BAYES=off …)`
  - `bayes: venv missing (…)`: no tools venv, or none of pymc, pytensor, nutpie, arviz. An `ok` line, never a
    failure.
  - `bayes: venv incomplete (…)`: some of the six fitter dependencies are absent. A WARN.
  - `bayes: venv ok (<versions>; STACK_BAYES=<mode>; last fit: <status>)`. The status is the last record of
    `usage/bayes.json.rec`. It is printed only if it matches the record's status shape, else as `unreadable`.
- **`STACK_BAYES` in the guard.** The knob is in the guard's `FIXED_LIMIT_KNOBS`. Its self-test fails when a
  `STACK_*` name in `stack_limits.FIXED_GUARDS` is missing from that list. It already failed when a listed knob
  was learnable.
- **`accel.lock`.** WP3c added no holder. The fit itself became the first holder afterwards (§2.8, work order
  step 9).

---

## 3. Modes, shadow, promotion, rollback

### 3.1 `STACK_BAYES` (env only, fixed knob)

`STACK_BAYES = off | shadow | on`, default `shadow`, any other value → `shadow` with one log line. Added to
`stack_limits.FIXED_GUARDS` (WP3a) and `agent_guard.FIXED_LIMIT_KNOBS` with its self-test (WP3c).
- `off`: `load_bayes` is not called; no shadow rows; method `empirical` everywhere; `prov.bayes_mode = "off"`.
- `shadow`: §4 decides every variable exactly as today (S1); for each variable with an accepted block,
  `decide_bayes` runs on a copy of the state and its result is logged as a `bayes-shadow` record (S2).
- `on`: a variable whose family is in `BAYES_LIVE` is decided by `decide_bayes` (method `bayes-nuts`, or
  `bayes-grid` when its family is also in `BAYES_GRID_LIVE`); every other variable as in `shadow`.

### 3.2 `BAYES_LIVE`, `BAYES_GRID_LIVE` (code constants)

`BAYES_LIVE = frozenset()` and `BAYES_GRID_LIVE = frozenset()` at WP3a. They change only by a reviewed commit with the
user's yes (WP6). `BAYES_LIVE ⊆ {"soft.agent", "soft.prompt", "soft.session"}` is asserted at import and by a test
(Q1: deny-type families are shadow-only until about 300 scorable rows per family support a 2 % / 1 % check; a new user
decision is needed to lift this). `BAYES_GRID_LIVE ⊆ BAYES_LIVE`, and a family enters it only after the rolling-origin
backtest of grid(NUTS hyperparameters) passes B1-T14 for it (T4a BLOCKING 2).

### 3.3 Promotion (per family) needs all five

1. the model gate passes on 3 consecutive refits (`usage/bayes.json.rec`);
2. B1-T14 (§A.9) passes on a rolling origin with ≥ 3 folds that train on ≥ 2 sessions, supported stratum;
3. ≥ 5 new sessions in shadow, with the would-vs-§4 report (WP6);
4. the user's approval, recorded in CONFIG.md §9;
5. the drift check (§2.1 rule 7) is implemented and written for that family (WP3b writes drift as {}).

### 3.4 Rollback (any one)

- `STACK_BAYES=off`: the next session uses §4 (method `empirical`), with no command (rollback drill, a test);
- `stack_limits.py rollback VAR|--all --to prev|seed` (existing command);
- delete `limits/bayes.json` or `limits/advice.json`: falls back to empirical, static or today's defaults;
- `live.v1.json` (kept by the migration) restores the pre-Bayes state;
- drift: the fitter sets `drift.<family>.breach = true` (§2.1) when the rolling PIT over the last 5 sessions fails
  (KS p < 0.01); `load_bayes` drops that family's blocks, so it falls back to §4 at the next session. Not
  implemented in WP3b (drift is {}): promotion item 5. The Goodhart
  guard (partial/blocked rate of the family's types in `reports.jsonl` up > 5 points after a change) is a WP6 report
  item that asks the user to roll back; it is not automatic.

---

## A. Limits v3 (L1–L8)

### A.1 What changed from v2 (every T4a finding, plan section 3)

| # | T4a finding | v3 text | code / proof |
|---|---|---|---|
| 1 | BLOCKING: a soft value tightens from one own row (sparse 10/21 hits) | A.5 step 5 (T4a's step 2b) `hold:sparse`; A.4 support line | `decide_bayes` branch; B1-T15; A.10 backtest |
| 2 | BLOCKING: grid tier on stdlib-moment hyperparameters (worst held-out, 21/65) | A.6 tier 2: only hyperparameters of a gated bayes.json with the same `seed_sha`; no moment path; tier off until B1-T14 on grid(NUTS) passes | `load_hyper`; `BAYES_GRID_LIVE`; B1-T16 |
| 3 | HIGH: fit_report blamed censoring | `docs/bayes/b1v2/fit_report.md` section 1 rewritten (marked EDITED) | A.10 re-derives the numbers |
| 4 | MEDIUM: `max()` skips NaN R-hat | A.4 NaN-strict gate | `CONSTANT_BY_CONSTRUCTION`; B1-T17 |
| 5 | MEDIUM: B1-T1 (grid within 15 % of NUTS) fails on the data | B1-T1 = grid vs scipy under a sharp prior; grid vs NUTS reported only | B1-T1 |
| 6 | MEDIUM: B1-T14 scores uncensored rows only, T only, no strata | B1-T14 replaced (A.9) | `tests/b1_backtest.py` |
| 7 | MEDIUM: censoring text stale after 697a685; prompt-scope warnings invisible on agent rows | A.3 rows 6–7 and the main-window join | `censor_flags`; B1-T19 |
| 8 | LOW: `SCHEMA` bump; hard.session seed; draws | §2.4 `LIVE_SCHEMA = 2`; L8 on the seed file's value (main 1.92B, f/g 300M / 2.5B), verifier runs set `B1_REPO` to the main checkout; 3000 / 2000 | B1-T18 |

### A.2 Variables

f/g = the seed's floor/ceiling (`stack_limits_seed.json`); the decision is always clamped to [f, g].

| # | variable | priors | likelihood | gate | decision | fallback |
|---|---|---|---|---|---|---|
| L1 | `turns.<type>` ×57 | §1.2, a0 ~ N(log 10, 1.5) | M1 shifted NB2, censored per A.3 | model + quantity gate (A.4); moves only when supported | T = ceil(q_.98); A.5; f = max(5, ceil(seed/4)), g = frontmatter maxTurns | §4 `decide()` (live, Q1); Bayes shadow-only |
| L2 | `soft.agent.<type>` ×57 | §1.2, a0 ~ N(log 1e6, 1.5) | M2 log-normal, censored per A.3 | as L1; sparse: may rise, never fall (A.5 step 5) | T = ceil2(q_.90); A.5; f 100k, g 100M | §4 |
| L3 | `hard.agent.<type>` ×57 | as L2 (same posterior) | M2 | as L1; supported only | T = ceil2(max(q_.99, 2 × T_soft)) (HARD_OVER_SOFT), clamp [2M, 200M], `at_bound`; soft ≤ 0.8 hard kept by `enforce_invariants` | §4 (live, Q1); shadow-only |
| L4 | `soft.prompt` | seed-anchored: mu0 = log(seed) − z_(1−r)·sqrt(σ² + sd0²), σ = sd0 = 1 (`bayes_grid.anchor_mu`) | M4 log-normal single level, censored on own `hit_soft`/`hit_hard_prompt` | ≥ 30 windows from ≥ 3 sessions; grid edge mass < 1e-3 | ceil2(q_.90); f 5M, g 100M; soft ≤ 0.67 hard.prompt | hold, method `empirical(hold)` |
| L5 | `soft.prompt.<type>` (orchestrator 140M pinned) | as L4 on the windows where the type ran | as L4 | as L4 | max(seed, q_.90), clamped: seed = f = g → never moves | hold at 140M |
| L6 | `hard.prompt` (pinned 300M) | anchored on soft.prompt | as L4 | as L4 | ceil2(q_.99), reported; f = g = 300M → never moves | §4 (Q1) |
| L7 | `soft.session` (unset) | anchored on hard.session | M4 on session rows, censored on `hit_soft`/`hit_hard_session` | ≥ 5 sessions | ceil2(q_.90); f 100M, g 1.5B; ≤ 0.8 hard.session | stays unset |
| L8 | `hard.session` | seed-anchored on the seed file's value (main: 1.92B) | as L7 | ≥ 5 sessions | ceil2(q_.99); f 300M, g 2.5B | §4 (Q1); shadow-only |

Bayes action: T is the posterior-predictive (1 − r) quantile of a new run's demand with the new-session effect
integrated. This is the Bayes action under pinball loss with cost ratio hit : slack = (1 − r) : r (9:1 soft, 49:1
turns, 99:1 hard), so the user's risk targets fix the loss.

### A.3 Censoring (`censor_flags(row, fam, lim_in_force, win_hits)`)

A censored row contributes log P(Y ≥ y_obs). Per row and family (turns, ctx), first match wins:

| # | condition | turns | ctx | spc, static_cc, ctx(n) |
|---|---|---|---|---|
| 1 | `status != "complete"` (open or truncated at collection) | cens | cens | excluded |
| 2 | `compacted == 1` | cens | cens | excluded from static_cc, ctx(n) |
| 3 | `turn_limited == 1` or `hit_turn == 1` | cens | cens | observed |
| 4 | any measured `hit_*` == 1 (soft or hard, any scope) | cens | cens | observed |
| 5 | agent row whose window's main row has `hit_soft == 1` or `hit_hard_prompt == 1` (**main-window join**) | cens | cens | observed |
| 6 | `status_code == 1` and every `hit_*` cell empty (pre-697a685 rows) | cens when api_calls ≥ NEAR × turns limit in force | cens when ctx ≥ NEAR × soft.agent in force | observed |
| 7 | `status_code == 1` with `hit_*` measured, all 0 | observed | observed | observed |
| 8 | `status_code == 2` (blocked: consent, sandbox, permission) | observed | observed | observed |
| 9 | schema-3 complete row with `status_code` empty (ended on a tool_use) | cens | cens | observed |

- NEAR = 0.5. "In force" = the row's session snapshot values when `limits/snapshots/<session>.json` reads `ok`,
  else the seed (the prototype's approximation, kept for the frozen fixture).
- Text replacing v2 §3.2's last two sentences (T4a fix 7): since 697a685 `hit_*` is measured per row, so the proxy
  (row 6) turns itself off row by row. Prompt- and session-scope soft warnings land on the main and session rows only
  (`stack_usage.py:700-715`: an agent row's `hit_soft` is its own `soft_agent` firing). `censor_flags` therefore also
  censors an agent row whose (session, window) main row has `hit_soft = 1` or `hit_hard_prompt = 1`.
- The join key: an agent row's `(session, int(window))` matches the main row with the same `session` and `seg ==
  window` (the key `build_proposals` already uses for `soft.prompt.<type>`, `stack_limits.py:925, 932`). `win_hits` is
  the set of such keys built once per `build_proposals` call.
- Main rows (L4–L6): censored on their own `hit_soft` or `hit_hard_prompt`; session rows (L7, L8): on `hit_soft` or
  `hit_hard_session`.

### A.4 Gates and support

- Model gate (per fitted model, NaN-strict): max R-hat ≤ 1.01 over every free parameter, bulk and tail ESS ≥ 400,
  0 divergences after tuning, E-BFMI > 0.3. Parameters constant by construction (zero spread across all chains, e.g.
  z_s with one session, z_g with one regime) are excluded by name (`CONSTANT_BY_CONSTRUCTION`); any other NaN R-hat or
  ESS fails the gate (T4a fix 4).
- Quantity gate (per variable, over the per-draw T): R-hat ≤ 1.01, bulk/tail ESS ≥ 400, MCSE(T)/T ≤ 0.02.
  **MCSE(T) by the delta method** (`stack_bayes.delta_mcse`): T solves F̄(T) = 1 − r with F̄ the mean over the
  posterior draws d of the per-draw predictive CDF F_d, so MCSE(T) = MCSE(mean_d F_d(T)) / f̄(T), f̄ the mean
  predictive density at T (log scale for the log-normal, so the ratio is already MCSE(T)/T; for the NB the pmf of
  T's step, F_d interpolated linearly within it, and the result divided by T_raw). MCSE of that mean = sd / √ESS,
  ESS the split-chain autocorrelation ESS of F_d(T) over every chain and draw (Geyer's initial monotone sequence,
  as arviz's `ess(method="mean")`, equal to it to 1e-9 in the tests). It replaces WP2's batch means over 20
  batches, whose own noise moved blocks across the 2 % gate between two runs with one seed; an iid sd/√N would
  ignore the autocorrelation (an AR(1) chain with φ = 0.8 carries (1 − φ)/(1 + φ) = 1/9 of its draws' information).
  A T with no positive density (a turns T past the sweep, §2.1 rule 4) has `mcse_rel: null`. Calibrated by
  replication: over independent autocorrelated posteriors the spread of T matches the mean
  predicted MCSE within [0.75, 1.33] for an NB 0.98 and a log-normal 0.9 quantile (`tests/test_stack_bayes_fit.py`).
- Grid tier gate: edge mass < 1e-3 in the two edge cells, and the hyperparameters come from a bayes.json whose model
  gate passed and whose `seed_sha` matches (§2.1 `load_hyper`).
- Support (appended to v2 §6, T4a fix 1): a soft-family Bayes value whose own sample fails `support()` (n ≥ 5 from
  ≥ 3 agents, or n ≥ 3 / 2 agents with a narrow CI) may rise toward T but never fall below c (decision
  `hold:sparse`). It tightens only when supported, like hard.* and turns.

### A.5 Decision (`decide_bayes`), per variable at SessionStart

Notation: c = current live value, T the block's rounded T, p_hit(c) from qtab (below), r = RISK[family], d the
damping level of the state, `supported` from §1.1.
0. Prelude, unchanged from `decide()` (`stack_limits.py:1114-1144`): no entry and no pool → nothing; frozen →
   `frozen`; hold counter → `hold`; no new rows (`n_new > 0 and upto > last` fails) → nothing.
1. No accepted block (absent, gate failed, other evidence id, `STACK_BAYES=off`) → today's `decide()` body, method
   `empirical`.
2. No own rows (no proposals entry, or the block's `n == 0`) → `hold:prior`.
3. c unset → soft.agent with ≥ 1 own row, or a deny-type variable that is supported: x = clamp(T, f, g) → `set`;
   otherwise `hold:unsupported`.
4. Deny-type family (turns, hard.*), not supported → `hold:unsupported`.
5. **Soft family, not supported, T < c → `hold:sparse`** (T4a's "step 2b").
6. Risk dead band: r/2 ≤ p_hit(c) ≤ 2r, or |T − c| ≤ 0.10 c → `dead` (counts toward `_streak`).
7. Tightening a deny-type variable: T ← max(T, min(c, hmax)); T ≥ c → `hold:hmax`. hmax is the sample's maximum
   (`x[-1]`, hit rows included, as in `decide()`): more conservative than a healthy-only maximum, which the
   proposals do not carry.
8. Step: reversal damping as `decide()` (a sign reversal among the last 3 moves halves d; three same-sign or dead
   decisions double it, `_streak`), x = clamp(_round_toward(step(c, T, d), c, unit), f, g), pins by the clamp
   (seed = floor = ceiling), then `enforce_invariants` over all variables (unchanged).

p_hit(c): with qtab (p_k, x_k), F(x_k) = p_k; for x_k ≤ c ≤ x_(k+1), log(1 − F(c)) is linear in log c between the two
points; c < x_0 → p_hit = 0.5 (clamped: "≥ 0.5", outside every dead band); c > x_7 → p_hit = 0.001 ("≤ 0.001"); equal
x's → the larger 1 − p.

### A.6 Fallback chain (per variable, in apply)

1. bayes.json with `evidence_id` == proposals' and both gates passing → tier `nuts` (acts only when its family is in
   `BAYES_LIVE` and `STACK_BAYES=on`; else shadow).
2. else the proposals entry's grid block, only when apply's own `load_hyper(seed)` returns `fit:<fit_id>` equal to the
   proposals' `bayes_hyper_source`, `drift.<family>.breach` is false and its grid gate passes; soft families only →
   tier `grid` (acts only when the family is in
   `BAYES_GRID_LIVE`; else shadow). Stdlib-moment hyperparameters never feed a decision.
3. else §4 `decide()` → `empirical`.
4. Prompt and session scopes below support → hold, `empirical(hold)`.
Accepted consequence: without the Bayes venv (WP3c, the user's install step) nothing is Bayesian; §4 runs everywhere.

### A.7 Q1, Q2 in code

- Q1: `decide_bayes` runs for turns and hard.* only in shadow, whatever `STACK_BAYES` is (`BAYES_LIVE` cannot hold
  them, §3.2). Their 2 % / 1 % targets need about 300 scorable rows per family before ±1 % is checkable; until then
  the backtest can show "no excess" only.
- Q2: no limits variable is a width; widths are advice (§C).

### A.8 WP3a specification (`dot-config/dot-claude/hooks/stack_limits.py`, new `stack_bayes_grid.py`)

1. `stack_bayes_grid.py` = `docs/bayes/b1v2/bayes_grid.py` minus `eb_hyper_lognormal` and that docstring clause
   (imports `math` only; Python 3.9); B1-T16 adds an AST check that no `eb_hyper_*` is defined in, or referenced from,
   stack_bayes_grid.py or stack_limits.py. Soft families only.
2. Constants: `RISK` (§1.1); `BAYES_GATE = {"rhat": 1.01, "ess": 400, "div": 0, "ebfmi": 0.3, "edge": 1e-3,
   "mcse_rel": 0.02}`; `NEAR = 0.5`; `LIVE_SCHEMA = 2` (`SCHEMA = 1` unchanged); `QTAB_P = (0.5, 0.8, 0.9, 0.95,
   0.975, 0.99, 0.995, 0.999)`; `CONSTANT_BY_CONSTRUCTION = frozenset({"z_s", "z_g"})`;
   `BAYES_MODES = ("off", "shadow", "on")`; `BAYES_LIVE = frozenset()`; `BAYES_GRID_LIVE = frozenset()`;
   `"STACK_BAYES"` added to `FIXED_GUARDS`.
3. `bayes_mode()`: `STACK_BAYES` lower-cased in `BAYES_MODES`, else `shadow` (logged once).
4. `censor_flags(row, fam, lim_in_force, win_hits) -> bool` per A.3; `fam` in {"turns", "ctx"} for agent rows,
   the variable family for main and session rows.
5. `_entry`: x, ci, prob, tight, top, n, agents, sessions, healthy, n_new, upto stay byte-identical (§4 unchanged;
   B1-T9 compares proposals without the new keys). Add `b = {"y", "cens", "resume", "sess"}` from the windowed rows
   with the quantity set, **censored rows included**, no `_cap_sessions`, sorted by (ts, session, id, seg), newest
   MAX_X; `resume = int(seg > 0)`; `sess` = index of the row's session in order of first appearance in `b`.
6. `load_hyper(seed)` and `load_bayes(seed, evidence_id)` per §2.1; `bayes_grid_block(entry, hyper, var, spec)` →
   a tier-`grid` block (stack_bayes_grid NB / log-normal posterior and predictive, qtab at `QTAB_P`).
   `build_proposals` attaches it when `load_hyper` returned hyperparameters and sets `bayes_hyper_source`,
   `bayes_seed_sha`. A variable whose type has no `hyper.<model>.types` entry (first seen after the fit) gets no grid
   block.
7. `decide_bayes(name, spec, st, block, ent, pool, soft_ref, now)` per A.5 → `(state, record)`; `p_hit(qtab, c)` per
   A.5.
8. `apply_proposals(seed, live, props, sid=None, now=None, *, bayes=None, mode=None)` (`stack_limits.py:1939` calls it
   positionally): per variable, choose the block by
   A.6; `mode == "on"` and family in `BAYES_LIVE` → the Bayes decision is the live one; otherwise run `decide()` for
   the live state and, when a block exists and mode != off, `decide_bayes` on `_copy_state(st)` and append its record
   as `bayes-shadow` (§2.6). The shadow call never mutates the live state (S1).
9. `_var_state`, `validate_live`, `MIGRATIONS[1] = _migrate_1`, `LIVE_SCHEMA` per §2.4.
10. `_write_snapshot` adds `prov` (§2.5). `show`, `status_line`, `stability_lines`, `history`: print method, T [pi90]
    and p_hit(c), and the shadow would-value.
11. Hard.agent T in a block = max(q_.99, 2 × soft T), clamped to [2M, 200M], `at_bound` set when clamped.
12. Latency: apply reads two JSON files only; p95 ≤ 300 ms with 176 blocks (B1-T12). No third-party import (B1-T2).
13. Scope variables (soft.prompt, soft.prompt.<type>, soft.session, hard.prompt, hard.session; M4, L4–L8) get no
    Bayes block in WP3a. `build_proposals` attaches none; `load_bayes` drops a `vars` block whose name is outside
    `soft.agent.*`, `hard.agent.*`, `turns.*` (that block only). They run §4 as today (A.6 step 4). M4's producer and
    tier are specified once WP2 has counted the window and session rows (§H).

### A.9 Tests (WP3a: `tests/test_stack_bayes.py`; B1-T11, WP3b: `tests/test_stack_bayes_fit.py`; B1-T13 and B1-T20, WP4: `tests/test_stack_sched_bayes.py`; B1-T14: `tests/b1_backtest.py`, a uv script)

| id | asserts |
|---|---|
| B1-T1 | stack_bayes_grid NB and log-normal quantiles equal scipy's under a sharp prior (sd 1e-6), relative 1e-6 (reference values computed with scipy and embedded; checked live when scipy imports); `p_hit` interpolation: inside the table it inverts qtab, below x_0 it is 0.5, above x_7 it is 0.001 (kills "qtab edge clamp off"). Grid vs NUTS agreement is reported, not gated |
| B1-T2 | AST scan: stack_bayes_grid.py and stack_limits.py import stdlib only; both compile and import under /usr/bin/python3 (3.9) |
| B1-T3 | hostile bayes.json: NaN/Infinity tokens, negative, non-monotone qtab, wrong `qtab.p`, wrong evidence_id, wrong seed_sha, another risk table, a fixed-guard name (e.g. `STACK_MAX_FANOUT`, `STACK_BAYES`), an unknown name, > 4 MiB, deep nesting → whole file ignored, method `empirical`, values equal §4's, no exception (kills "fixed-guard name accepted"). Positive control: a bayes.json whose `hyper` comes from `docs/bayes/b1v2/out_v2/hyper_ctx.json` and `hyper_turns.json` (`nuts` blocks, rho < 0) is accepted by `load_hyper` and `load_bayes` |
| B1-T4 | gate fallback: block rhat 1.02, ess_bulk 300, ess_tail 300, mcse_rel 0.03, model with 1 divergence, ebfmi 0.2, `gate: true` with failing diag → `empirical`, value = §4's |
| B1-T5 | prior holds: a type with no own rows never moves; turns and hard.* never move unless supported |
| B1-T6 | censoring: one row per A.3 line → expected flags for turns and ctx separately; the status_code-1 proxy switches off when `hit_*` is measured |
| B1-T7 | pins: `soft.prompt.orchestrator` never leaves 140M and `hard.prompt` never leaves 300M under 10k random blocks; env override origin `env` and exact; no fixed-guard name in bayes.json / live / proposals (advice.json: WP7c) |
| B1-T8 | step bound: with random valid blocks, \|x − c\| ≤ 0.25 d c before the clamp, values in [f, g], invariants hold (kills "step bound removed") |
| B1-T9 | U4: rewriting bayes.json mid-session changes nothing a running session reads; a new sid applies it once; proposals without `b`/`bayes` keys equal today's; proposals for the five scope variables (A.8 item 13) carry no `bayes` key |
| B1-T10 | provenance: snapshot `prov` is hashed and `agent_guard.read_limits_snapshot` returns ok; migration 1 → 2 keeps `live.v1.json`. A schema-1 live.json with a learned (non-seed) value, loaded twice by `load_live_locked`, keeps that value, and no `live.invalid-*` file appears |
| B1-T11 | determinism of the fitter: same data and seed → identical bayes.json except `generated` for spc, static_cc, ctx_ab; turns/ctx within a tolerance set empirically (v2: not bit-reproducible across processes); the gate never relies on bit reproducibility |
| B1-T12 | latency: apply_and_snapshot p95 ≤ 300 ms with 176 blocks |
| B1-T13 | refresh: with a valid sched block `stack_sched_refresh` writes a model `stack_sched.load_model` accepts, method `bayes`; without it, output byte-equal to today's (WP4) |
| B1-T14 | (verifier, `tests/b1_backtest.py`) rolling origin; per family × stratum (supported / sparse), score T and the deployed value; a censored row above T is a hit, below T unknown, so counts are intervals [lo, hi]; censored rows get a randomized PIT U(F(y), 1); accept when, on T in the supported stratum, the session-clustered P(K ≥ lo) ≥ 0.05 and P(K ≤ hi) ≥ 0.05, coverage90 ∈ [0.8, 0.97], and in the sparse stratum hits(deployed) ≤ hits(current) |
| B1-T15 | 10k random blocks: `decide_bayes`'s state for a sparse soft type has value ≥ c (asserted before `enforce_invariants`) (kills "no hold:sparse") |
| B1-T16 | proposals with `bayes_hyper_source: "stdlib-moments"`, absent, or another seed_sha → no grid block used, method `empirical`; `load_hyper` without a gated bayes.json returns (None, None) and `propose()` writes no grid block (kills "moment hyperparameters accepted"); bayes.json deleted after propose → grid block unused, method `empirical`; `drift.soft.agent.breach = true` → same; an AST check that no `eb_hyper_*` is defined in, or referenced from, stack_bayes_grid.py or stack_limits.py |
| B1-T17 | a fake posterior with one constant-per-chain parameter not in `CONSTANT_BY_CONSTRUCTION` (NaN R-hat) → model gate false → `empirical`; the same with `z_s` constant → gate unaffected (kills "NaN-skipping R-hat") |
| B1-T18 | seed, proposals and snapshot stay `schema_version` 1; live.json is 2; `read_limits_snapshot` accepts `prov` (kills "SCHEMA bumped instead of LIVE_SCHEMA") |
| B1-T19 | a main-window `hit_soft` (and, separately, `hit_hard_prompt`) censors the agent rows of that window only, for turns and ctx (kills "main-window join dropped") |
| B1-T20 | a hostile bayes.json `sched` block (NaN, lo > med, S > L, unknown type, fixed-guard name) → `combine()` output equals today's (WP4) |
| S1 | `STACK_BAYES=shadow` with valid blocks: live.json values, snapshot `values`/`origin` and §4 history records are byte-identical to `STACK_BAYES=off` on the same inputs (kills "shadow applies values") |
| S2 | in shadow, each variable with an accepted block gets exactly one `method: "bayes-shadow"` record with `would`, `decision`, `T`, `p_hit_c`, `fit_id`, `applied: false`; with `STACK_BAYES=off` none |

WP3a mutants, each killed by the named test: no hold:sparse → T15; moment hyperparameters accepted → T16;
NaN-skipping R-hat → T17; fixed-guard name accepted → T3; step bound removed → T8; SCHEMA bumped instead of
LIVE_SCHEMA → T18; shadow applies values → S1; qtab edge clamp off → T1; main-window join dropped → T19.
Also: a test that `BAYES_LIVE` holds no deny-type family (Q1), and the rollback drill (`STACK_BAYES=off` → method
`empirical` next session). Other live.json readers to re-check for the schema bump: `install.sh:2817` (the copy-aside
of an older schema), `dot-config/dot-claude/bin/stack-budget`, and the tests that write live.json fixtures
(`rg -l 'live\.json' tests`).

### A.10 Calibration on the frozen fixture (WP1b, $0, no refit)

Inputs: the v2 held-out rows (`docs/bayes/b1v2/out_v2/backtest_clustered/backtest_rows.csv`, and the main run's
`out_v2/backtest_rows.csv` as an independent sampler run), scored by `.claude-work/bayes/wp1b/wp1b_backtest.py` with
the prototype's lock (`uv run --no-cache --locked --script`). Rolling origin, 3 folds; c = the value in force (the
seed of that day, the prototype's approximation). soft.agent:

| stratum | T (Bayes): hits/n [Jeffreys 90 %] | deployed v3 | current c | §4 | grid (moment hyper) |
|---|---|---|---|---|---|
| sparse (n_train < 5) | 10/21 [0.31, 0.65] | 7/23 | 7/23 [0.17, 0.47] | 0/2 | 14/21 |
| sparse with a Bayes block (n_train ≥ 1) | 10/21 | **7/20** | **7/20** | | |
| supported (n_train ≥ 5) | **5/44 = 11.4 %** [0.05, 0.21] | 1/31 (dead band) to 1/42 (step) | 1/31 | 7/43 | 7/44 |

- Targets met: supported 5/44 and sparse hits(deployed) 7/20 ≤ hits(current) 7/20. The deployed count is the same
  whether or not the risk dead band holds (p_hit(c) is not in the rows): with hold:sparse every sparse row with T < c
  keeps c (25 of 26 decisions), and the one step goes up (data-scientist, T 22.9M > c 19M) on a censored row whose
  outcome is unknown either way.
- T4a's PIT figures reproduce on the sparse rows with a block: soft n 13, mean 0.655, KS p 0.0028; turns n 19, mean
  0.741. Supported: soft KS p 0.42.
- The main sampler run gives the same counts; a csv-module recount (second route) agrees.
- Not computed here (needs the posterior, i.e. a refit): the session-clustered P(K ≥ lo), P(K ≤ hi) per stratum and
  the randomized PIT of censored rows. Both are WP2/WP5 (`tests/b1_backtest.py`). v2's pooled clustered check for
  soft.agent: hits [15, 29] of 79, P(K ≥ 15) = 0.087.
- turns 0/63 and hard.agent 0/54 held out: "no excess" only (upper Jeffreys bounds 0.03 / 0.035 pooled).

---

## B. Scheduler estimates (S1–S12)

- **Priors.** §1.2 per model (a0 centres 10 calls, 15 s per call, 30k static_cc; ctx(n) K0 ~ N(log(5e4 + 2e3 n_ref),
  1.5), Q0 ~ N(log(2e3 n_ref / 5e4), 1.5)); resume_ctx alpha ~ N⁺(0, 1e5), gamma ~ N⁺(0, 1e4); fixer NIG(log 2e5, 1,
  2, 2); cold.frac Beta(1, 1).
- **Likelihood.** M1 for turns; M3 log-normal for sec_per_call (complete rows, wall_s > 0), static_cc (healthy first
  segments, no session or resume term), ctx(n) regression in (k_t, q_t) at n_ref; Student-t (ν = 4) for resume_ctx;
  log-normal NIG for the fixer reread; censoring per A.3 (rates are not truncated by a stop).
- **Gate.** The model gate of each source model (A.4); the block is used only when `evidence_id` equals the
  proposals' and `seed_sha` matches; values finite with lo ≤ med ≤ hi and S ≤ M ≤ L.
- **Decision (mapping, T4a spec item 13).** turns {S, M, L} = predictive q.25/.50/.90; `sec_per_call` {p50, p90};
  ctx {a, b} = posterior medians; static_cc = predictive q.10; band.turns = {lo: M·q05m/q50m, med: M, hi:
  M·q95m/q50m} with q·m quantiles of the per-draw median; band.ctx = {lo, med: 1.0, hi} as factors at n_ref
  (`combine_entry` semantics, `stack_sched_refresh.py:156`); pools from the class-level predictive (a new type of that
  pool), which replaces `UNVERIFIED_W` and the "pool:<tier>" copy. Then `bounded()` (≤ ×1.5 per refresh) and
  `rounded()` unchanged. Record: `method: "bayes" | "combined"`, `fit_id`.
- **Fallback.** Today's `combine()` (B1-T13: output byte-equal without a block; B1-T20 for hostile blocks).
- **WP4 contract.** `load_bayes_sched(path, evidence_id, seed_sha)` in `stack_sched_refresh.py` returns the validated
  §2.2 block or None; `stack_sched.py` is unchanged (`load_model` takes types and pools as given). Mutant: lo ≤ med ≤
  hi check removed → B1-T20. Scheduler estimates are not limits: promotion (§3.3) needs only items 1, 3, 4.

---

## C. Fan-out and swarm width (M6), advice only

- **Scope (Q2).** The static caps (`STACK_MAX_FANOUT` 3, `DEFAULT_FANOUT_BY_TYPE` orchestrator 32, main-coder 6,
  ninja-coder 5, researcher 4, planner 8, plan-reviewer 8) and every `STACK_FANOUT_*` knob stay fixed guards and
  ceilings. M6 writes `limits/advice.json` (§2.7); stack_fanout logs an `adv` term in its decision rows (shadow, never
  enforcing), and the plan text, `stack-budget plan` and the planner/orchestrator rule lines show W*, the swarm
  threshold and the minimum part size: "swarm width = advised w* (stack-budget plan), else min(items, 8), ≤ 16".

### C.1 Priors
- Per-child wall: log wall_i = mu_i + gamma·log w_wave + e_i, mu_i from the M1 × M3 predictive of the child's type
  (calls × seconds per call), gamma ~ HalfNormal(0.2) (slowdown per doubling ≤ ~15 % a priori), e_i ~ N(0, sigma_w),
  sigma_w ~ HalfNormal(0.5).
- Child failure (error, rate limit, overload): logit P = alpha0 + alpha1·log w, alpha1 ≥ 0 ~ HalfNormal(0.5), alpha0 =
  logit(0.01) − alpha1·log 8 + eps, eps ~ N(0, 1): P(fail at w = 8) ≈ 1 % a priori.
- Wave rate limit: logit P(any 429 in a wave) = beta0 + beta1·log w, beta1 ≥ 0 ~ HalfNormal(0.5), beta0 anchored as
  alpha0 at 2 % for w = 8.
- Overhead tokens per child = static_cc (S5) + brief + report, from the M3 posteriors.

### C.2 Likelihood
Log-normal wall per child (open children censored at the wave end), Bernoulli failures per child, Bernoulli rate limit
per wave, all from the wave reader (WP7a: n live, child wall, errors per spawn). Only designed data (P1) enters the
gamma, alpha1 and beta1 terms: live waves are shaped by the AIMD window and today's w is always 8 with 0 failure events
(148 decisions, 162 finishes, 0 rate-limit/overload/failure errors on 2026-10-07), so they would only return the prior.

### C.3 Gate
Model gate (A.4); ≥ 2 distinct widths with ≥ 3 waves each from P1; prior-predictive check of makespan per width
within the observed range. Without it advice.json carries `source: "prior"` and today's defaults.

### C.4 Decision
w*_t = argmin over w ∈ {1, ..., cap_t} of λ_t·E[makespan(w)] + λ_c·E[tokens(w)] + λ_f·E[failures(w)], subject to
P(any rate limit in a wave) ≤ 0.10 and w ≤ cap_t (and ≤ 16 for swarms). Swarm threshold: the smallest item count for
which P(U(w*) > U(1)) ≥ 0.9 (sequential is w = 1). Minimum part size: the smallest part with E[wall saved]·λ_t >
E[spawn overhead] (static_cc + brief + report). λ from the Pareto profiles (WP11); until then a provisional default
profile λ_t = 1 per minute, λ_c = 1 per 1M tokens, λ_f = 30 (an assumption of this design, recorded in advice.json
`lambda`, replaced by WP11).

### C.5 Fallback
advice.json absent or invalid → today's defaults (min(items, 8), max 16; static caps; AIMD W0 = 8).

### C.6 Pilot P1 (consented, Q3; the user runs it)
16 homogeneous read-only lookup items (mechanically scored) × widths {2, 4, 8, 16} × 3 replicate headless
orchestrator sessions = 12 sessions × $3 cap, plus a 1-session smoke: ≤ $40 in `claude -p --max-budget-usd` cap sums
(on a subscription the USD may be notional; runs use plan quota). It identifies makespan per width well; with 0 events
it bounds the rate-limit probability only (≈ 6 % per-arm 95 % upper bound). Harness `tests/pilot_width.py` (WP7b, $0
tests against a stub `claude`). Any change of cap or design goes back to the user before spend.

---

## D. Equilibrium N* and rounds* (M7)

### D.1 Priors
logit P(correct | m, k, item i) = a_k + b_k·log m + c_k·rounds + u_i; a_k ~ N(0, 1.5); b_k = b̄ + σ_b z_k, b̄ ~ N(0.3,
0.3), σ_b ~ HalfNormal(0.3) (partial pooling across classes); c_k ~ N(0, 0.5); u_i ~ N(0, σ_u), σ_u ~ HalfNormal(1).
For non-binary scores the same linear predictor: CR's score rescaled to [0, 1] in the fractional-logit term, ES with
an identity link and a Gaussian likelihood (§D.2).

### D.2 Likelihood
The unit is (item i, m): y_im = A6's score(m) on item i (the exact mean over the C(9, m) subsets, expectation
tie-breaks), one observation per (item, m), m ∈ {1, 3, 5, 7, 9}. PF, CP, RS: y_im ∈ [0, 1] with a fractional-logit
(quasi-binomial) term, weight 1 per (item, m). CR: the §2 score rescaled to [0, 1], same term. ES: s_im with a
Gaussian likelihood on the same linear predictor (identity link, σ_k ~ HalfNormal(0.5)). u_i carries the dependence
across m. p7: one observation per (item, branch, r) on the stop-rule score.

### D.3 Gate
Gate: the A.4 model gate (R-hat ≤ 1.01, bulk and tail ESS ≥ 400, 0 divergences, E-BFMI > 0.3, NaN-strict) and
WP8's parameter-recovery test at p's fixed design (10 items per class; 5 for CP and CR). The synthetic ledgers
simulate member-level answers, with a member effect shared by every subset that contains it. The 90 % interval of b_k
must cover the truth in [0.80, 0.97] of 200 replicates; otherwise the amendment is not dated and Q4 reverts to (b).
No item-count gate: §3 fixes p's counts.

### D.4 Decision
N*_k = argmax over m ∈ {1, 3, 5, 7, 9} of E[score(m) − λ·cost(m)], with cost(m) = m · member cap · (1 + rounds) from the
ledger's blended USD rate; keep N = 5 unless P(U(N*) > U(5)) ≥ 0.9; N* = 1 → class not eligible. rounds* by the same
rule over {0, 1, 2} given N*. Bounded by `STACK_EQ_MAX_N` 9 and `STACK_EQ_MAX_ROUNDS` 2.

### D.5 Fallback
N = 5, rounds = 1 (`docs/RUNTIME_EQUILIBRIUM.md` §7.7). eq_params.json has every class `not_run` today.

### D.6 Draft amendment (Q4; text only, applied by WP8, not here)

To be appended as the next §12 amendment of `dot-config/dot-equilibrium/COMPARE_eq.md` (A10 at main `d6046693`), dated
before any pilot (p) data exists, re-pinned with `tests/equilibrium_paths.py amend`:

> **A10. <date>, PRE-FREEZE. Bayesian expected-utility selection of N* and rounds* on p.** Written before
> `eq_freeze.sh --collect` and before any p call: no p data exists (every class `not_run` in `eq_params.json`).
> 1. Replaces, for stage p only, the one-SE rules of A6 for N* and rounds* (`docs/RUNTIME_EQUILIBRIUM.md` §7.1 rows
>    "N*" and "rounds*"). The model: logit P(correct | m, k, i) = a_k + b_k log m + c_k r + u_i, priors as in
>    `docs/BAYES.md` §D.1, fitted with PyMC (pinned stack) on p6's C(9, m) subset scores and p7's branches, seed
>    `eq|bayes` = 20261004 ^ int(sha256("eq|bayes")[:8], 16).
> 2. Selection: N*_k = argmax_m E[score(m) − λ cost(m)] over posterior draws, λ fixed before p at the default
>    profile's value (recorded here as a number when this amendment is dated); N*_k stays 5 unless
>    P(U(N*) > U(5)) ≥ 0.9; N* = 1 → class not eligible. rounds*: same rule over {0, 1, 2} given N*.
> 3. Gate: R-hat ≤ 1.01, bulk and tail ESS ≥ 400, 0 divergences, E-BFMI > 0.3, no NaN diagnostic outside effects
>    constant by construction; failing → the A6 one-SE rule applies unchanged (it is the
>    fallback, computed and recorded in every case).
> 4. Unchanged: q's hypotheses, Holm over the primary family, the ship rule, every seed of §8.4, the draw order and
>    the disjointness of p and q items. p still tests nothing; the selection rule is mechanical and fixed here.
> 5. `params.json` gains a `selection` provenance block per class: `{"rule": "bayes-eu" | "one-se", "fit_id",
>    "p_better", "N_one_se", "rounds_one_se"}`.

If p data exists before WP8 lands, this amendment is void and Bayes stays secondary (reported next to the one-SE
choice), per the risk table of the plan.

---

## E. Routing, quality, effort and model (M5)

### E.1 Priors
y ∈ {fail, partial, pass} ~ OrderedLogistic(eta, c1 < c2); eta = u_a + v_f + β·match + γ_size + δ·install +
ε_e·effort_down + μ·model_alt; u_a = τ_pool z_pool + τ_agent z_agent; v_f = τ_fam z_fam; τ_* ~ HalfNormal(0.5);
β, δ ~ N(0, 0.5); γ ~ ZeroSumNormal(0.5); c ~ N([−3, −1], 1) ordered; **new** ε_e ~ N(0, 0.5) per class pooled
(ε_e,k = ε̄ + σ_e z_k, σ_e ~ HalfNormal(0.3)), μ ~ N(0, 0.5) (only once P2 or a model switch gives variation).

### E.2 Likelihood
Ordinal logit on graded runs (graded ids only; tool-absent excluded, never imputed); tokens per run from M2 for the
cost side.

### E.3 Gate
Model gate; ≥ 5 graded runs per compared cell (v2 §8). Today: 64 graded runs (57 pass, 7 partial, 0 fail), no
(agent, family) cell with ≥ 5 → no routing or effort rule may be drawn; the lower cutpoint is prior-driven.

### E.4 Decision
Choose a for class c maximising E[U] = P(pass | a, c) − λ·E[tokens | a] over posterior draws; change routing or
effort only when P(beats the current choice) ≥ 0.9 and the cell gate holds. Changes to frontmatter effort or
`agent_effort.json` go through claude-code-engineer after the user's yes (WP9).

### E.5 Fallback
No routing or effort change; Beta(1, 1)-binomial pass rate per agent is reported as the unpooled cross-check.

### E.6 Pilot P2 (consented, Q3; the user runs it)
4 classes × {frontmatter effort, one level lower} × 10 baseline prompts = 80 runs × $2 cap plus 80 grader calls ×
$0.50: ≤ $200. Resolves the pooled effort effect on pass rate to about ±0.12 (90 %), per class about ±0.17; the token
side is well identified. WP9 refines these widths by prior-predictive simulation before the run.

---

## F. Early-stop thresholds (M8), report only

- **Priors.** logit P(recover | window features, type) = a + b·fails_in_window + c·rounds_without_progress +
  d_pool + e_type; a ~ N(0, 1.5), b, c ~ N(0, 1), pool and type effects ZeroSumNormal / N(0, τ), τ ~ HalfNormal(0.5).
- **Likelihood.** Bernoulli on replayed windows (`tests/derive_early_stop.py`): 521 runs, 34 stalls, 30 recovered,
  12 false stops on the 5 frozen stage-4 sessions (CONFIG.md "Brief budgets and early stop").
- **Gate.** Model gate; ≥ 50 stall windows from ≥ 5 sessions.
- **Decision.** Report the posterior false-stop rate per (ROUNDS, FAILS) pair; recommend a pair only if its false-stop
  rate is ≤ 5 % with P ≥ 0.9. `STACK_EARLY_STOP` stays `observe`; the switch is the user's.
- **Fallback.** ROUNDS 8, FAILS 4, observe.
- Output shrink (8000 / 20000) and `RESERVE_TOK` (8M): report only (re-read-after-cut rate; posterior q.90 of
  integration plus verifier cost), values unchanged.

---

## G. Never tuned

Security and policy guarantees (no-push, PROTECTED_PATHS, POLICY, READONLY_TYPES, read gate, scrub, SendMessage scope,
USER: relay, BlackCat delegate-only and its step caps); capacity ceilings the user set (max concurrent subagents 128,
depth 8, MCP 64, static fan-out caps, `STACK_EQ_*` caps, web-search caps); floors, ceilings, pins, frontmatter
maxTurns, HARD_OVER_SOFT, PAIR_RATIO, exact env overrides and the risk targets; liveness and lock timers; hostile-input
bounds; control-law constants (STEP_MAX 0.25, D_LEVELS, AIMD, breaker, NODE_RUNS, refresh step 1.5); supply-chain
cooldowns; platform facts; the user's dials (`STACK_SOFT_LIMIT_SCALE`, `STACK_SCHED_POLICY`, every observe / shadow /
enforce switch, `STACK_BAYES`). A learned value would turn a guarantee into a statistic.

## H. Open and unverified

- Fit time against the 900 s timeout (v2's 1069 s includes the backtest and LOO). **Measured:** WP2 (4 × 3000,
  with tool_calls): NUTS only 302.9 s cold, 267.1 s warm; 497 s in-process cold with the post-processing. WP3b's
  `stack_bayes.py` on the same copy (8 chains on 8 cores, no tool_calls, warm compile cache, 2026-10-09):
  8 × 3000 NUTS 156 s, post-processing 107 s, 276 s wall, 1069 MiB peak RSS; 8 × 4000 (shipped) NUTS 182 s,
  post-processing 148 s, 348 s wall, 1248 MiB. The proposer window caps the data at 20 sessions, so the margin
  (2.6×) shrinks only with rows per session.
- **No block accepted on today's data.** At 8 × 3000 and 8 × 4000 the turns and ctx models each had 2–3
  divergences, so both model gates fail and 0 of 171 blocks pass (WP2 at 4 × 3000: 0 for ctx, 1–2 for turns), and
  148 of 171 blocks are `at_bound`. The data is censored by a collector defect (719 of 975 turns rows and 728 of 975
  ctx rows censored; fixed on branch `fix/turn-limited`, not yet merged). The gates are not loosened; refit on
  data collected after that fix before judging the models.
- `drift` is written as `{}`: the rolling-PIT drift check (§2.1 rule 7) is not implemented; nothing is dropped
  for drift until it is.
- `<state>/accel.lock` (§2.8): the Bayes fit is its only holder. No other stack job (an MLX or GPU run) takes it
  yet. The tests prove the holder with a fake fitter, under `tmp` state (2026-10-09); a live install's
  collector holding it is unverified.
- A fit orphaned by a SIGKILLed collector ends itself at 930 s (`stack_bayes.py`'s own SIGALRM cap, §2.8). The
  tests prove it with the real `main()` around a fake fit that never ends (`--timeout 3`). A process the fit
  started itself would outlive that cap. The nutpie sampler starts none, but that is unverified on a real fit.
- The Bayes lock pins pytensor 3.3.2 rather than the 3.3.3 the WP2 and WP3b fits ran on, because of the cooldown
  (§2.9). Re-lock on or after 2026-10-10. A fit on 3.3.2 has not been run.
- Window and session row counts in today's live data: WP2.
- The clustered check per stratum and the randomized PIT of censored rows: need a refit (WP2/WP5).
- Turns and ctx fits were not bit-reproducible across processes with the same seed in v2 (§2). B1-T11 on the frozen
  fixture (2026-10-09; WP2's environment, nutpie, 4 × 1000, two processes on one machine): the two bayes.json files
  were identical apart from `generated` (171 blocks, 139 with an MCSE). The test keeps a tolerance of 5 combined
  MCSEs on T for turns and ctx, since another machine or library build may still differ; the gates never rely on
  bit reproducibility.
- The limits in force at past sessions are approximated by that day's seed in the censoring proxy (rows 6 only).
