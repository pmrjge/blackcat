# Harness ledger schema (version 1)

Written by `eq_harness.py run` to `$EQ/runs/<stage>/ledger.jsonl` (stage `p` pilot, `q` confirmation, `d` dev dry
run). **Append-only JSONL**, one object per line, written under an exclusive `flock`; lines are never rewritten. A
re-started run appends after the existing lines (item-arms already holding an `item_arm` record are skipped). Analysis
routes (`eq_analyse.py`, `eq_route2.sql`) should be written from this file alone; `COMPARE_eq.md` §4-§6 defines what
to compute.

Conventions: times are UTC ISO-8601 with microseconds (`2026-10-05T12:00:00.123456Z`); money is USD; `cap_usd` is a
decimal string with 6 places (exact, floored micro-USD); member numbers are 1-based; `label` is the arm label
(`p1` S*, `p2` G, `p3` E, `p4` EG; `q1`-`q4` in the confirmation; the dev dry run uses `p` labels; `p5` the unfunded S* screening, `p6` and `p7` the calibration cells of COMPARE_eq §12 A6.3, stage `p` only; `p9`/`q9` declared re-runs); `node` is a plan
node id (G and EG) or null (S*, E); paths are absolute.

## Common fields (every record)

| field | type | meaning |
|---|---|---|
| `schema_version` | int | 1 |
| `seq` | int | 1-based line number at write time (strictly increasing) |
| `ts_utc` | str | write time |
| `record` | str | one of `run_start`, `call`, `plan`, `reduce`, `reconcile`, `check`, `node`, `item_arm`, `e_rt`, `run_end`, `run_abort`, `wall` |
| `stage` | str | `p`, `q` or `d` |

## `run_start` / `run_end`

| field | type | meaning |
|---|---|---|
| `harness_sha256` | str | sha256 of the running `eq_harness.py` |
| `flags_sha256` | str | sha256 of `json.dumps(flags, sort_keys=True)` (the loaded flags.json) |
| `claude_bin` | str | resolved `claude` path; `stub` bool: true for the stub (zero spend) |
| `stub` | bool | see above |
| `numpy_version` | str | numpy used for every seeded draw |
| `argv` | list[str] | the harness command line |
| `cells` | list[str] | (`run_start`, A6.3) the calibration cells this invocation runs (`run --cells p6,p7`; `[]` = the stage's arm rows only: cell rows are skipped without `--cells`, and with it only the named cells' rows run) |
| `e_arm` | str | (`run_start`, A6.5) `harness` (default: the E arm is the harness's own N-member E-node) or `runtime` (`run --e-arm runtime`: the E rows run E_rt, see `e_rt` below) |
| `items_run` | int | (`run_end` only) items started in this invocation |
| `isolation` | object | (`run_start`) the run's ONE isolation backend, frozen: `backend` (`container` = Apple container, the default since 2026-10-05 / `off`; `sandbox-exec` is a stub that fails closed; ledgers written before 2026-10-05 say `docker`), and for container `images` (class → `name:tag@sha256:<digest>`), `limits` (`nproc`, `memory`, `cpus`), `tmp_size` (the `/tmp` tmpfs), `work_size` (the capped `/work` tmpfs, filled from the read-only `/eqsrc/work` bind), `user` (uid:gid), `network` (`none`), `oracle_isolated_classes`. A ledger whose earlier `run_start` names another isolation is refused |
| `wall` | object | (`run_start`) the WALL of this run (`../wall/WALL_DESIGN.md`), frozen like `isolation`: `{"enabled": false}` without one (the pre-registered default); else `enabled`, `mechanism` (`dir-v1`), `ctr_path` (`/eq/tunnel`), `policy_sha256`, `broker_sha256`, `client_sha256`, `config_sha256` (all equal to flags.json `wall`, checked before the run starts), `policy_path`, `tunnel_root`, `state_dir`, `run_id` (the WALL run id, 32 hex), `nonce_sha256` (commitment to the per-run nonce; the nonce itself never enters the ledger and is revealed beside the audit log at run end), `probe_receipt_sha256` (the PASSing tunnel-probe receipt the run was admitted with). A ledger whose earlier `run_start` names another `config_sha256` (or `member_exec`) is refused |
| `member_exec` | str | (`run_start`) `host` (pre-registered: member Bash runs on the host) or `sandbox` (amendment proposal: member Bash replaced by `mcp__eqbox__sandbox_exec`, every command in the class container) |
| `orphans_removed` | int | containers of THIS invocation (label `eq-inv`) removed by the sweep at start (`run_start`) / end (`run_end`), plus other invocations' containers older than the longest allowed run + `container_orphan_grace_s` (label `eq-started`); live ones of other invocations and lib.sh's probe containers are only reported on stderr. Also swept (this invocation only) before and after every item-arm |

## `run_abort` (R1 F3: isolation lost mid-run; the invocation then exits 2)

Written instead of `run_end` when the container services (`container system status`) or the image (`container image
inspect TAG`: present, with the pinned digest, checked before and after every run) no longer answer after a
container run, or any other `IsolationError` is raised while an item-arm runs. The item-arm has no
`item_arm` record, so a later `run` redoes it; nothing of the lost execution is recorded as a `check` FAIL or a
REFUTED fact.

| field | type | meaning |
|---|---|---|
| `item`, `label`, `arm` | str | the item-arm that was running |
| `error` | str | the `IsolationError` message (≤ 500 characters) |
| `items_run` | int | items completed in this invocation before the abort |

## `call` (one per `claude -p` invocation; the unit for tokens, cost and transcripts)

| field | type | meaning |
|---|---|---|
| `call_id` | str | `<5-digit counter>_<role with / as "of">`; the counter continues from the number of `call` records already in the ledger, so ids are unique within a ledger; `item_arm.calls` lists them |
| `run_tag` | str | `<UTC yyyymmddTHHMMSS>-<pid>` of the `run` invocation; raw data live under `$R/<stage>/<item>/<label>/<run_tag>/` (`calls/<call_id>/`, `work/`, `nodes/`) |
| `item`, `cls` | str | item id and class (PF CP CR RS ES DS OE) |
| `label`, `arm` | str | arm label and arm (`S*`, `G`, `E`, `EG`) whose call this is |
| `charged_to` | list[str] | labels this call's cost and tokens count for. The shared planner call (role `plan`) is `[G label, EG label]` (COMPARE_eq §1: charged to both); every other call has `[label]`. **Item-arm totals = sum over calls whose `charged_to` contains the label** |
| `role` | str | first-line role: `s` (S*), `plan` (planner), `n<j>` (G/EG node j in topological order), `m<i>/<N>` (member i of an N-member E-node; EG lens planners are `m2/3`, `m3/3`, G's plan is member 1 of the planning node), `r<k>` (reconcile or repair round k: a FORKED session, see `parent_session_id`), `sel` (selection judge), `ver` (single-support verifier, also the RS equivalence call), `rt` (E_rt: the one `claude -p --agent equilibrium` leader call of the runtime arm, A6.5) |
| `agent` | str | `--agent` type |
| `member` | int or null | member number inside its E-node (E, EG E-nodes, EG planning node) |
| `node` | str or null | plan node id (EG E-nodes and G/EG plain nodes) |
| `round` | int | 0 for first calls, k for `r<k>` |
| `cap_usd` | str | the `--max-budget-usd` value (also inside `argv`) |
| `argv` | list[str] | exact argv; the `--json-schema` value is replaced by `<schema sha256 …>`. The prompt is on stdin, not in argv |
| `prompt_sha256`, `prompt_path` | str | prompt hash and file (first line `<ITEM> <label> <role>`) |
| `raw_path` | str | the call's stdout (the `--output-format json` envelope); `stderr.txt` beside it |
| `cwd` | str | the call's working directory: a fresh fixture copy, except `r<k>` calls, which run in the member's own copy (a forked session needs its cwd) and the `rt` call, which runs in `work/E_rt` of the arm directory (a fresh fixture copy the runtime's own subagents work from) |
| `resume` | str or null | session id passed to `--resume` (with `--fork-session` for `r<k>`: see `parent_session_id`) |
| `parent_session_id` | str or null | (E2, COMPARE_eq §12 A6.1) the session a reconcile or repair call forked (`--resume <it> --fork-session`; the call's own `session_id` is the new fork): the member's LATEST session, i.e. round 0's for round 1, the member's round-(k-1) fork for round k (A6 implementation note, USER decision (a) of 2026-10-06), so every round-0 session stays pristine for the p7 branches; null for unforked calls |
| `branch_workdir` | str or null | (forked calls of `workdir_answer_classes`, CP) the branch's saved copy `<cwd>.<branch>` (`live` for the E arm's own repair, else the p7 branch): the call runs in `cwd` (restored to that branch's state under a per-member lock; `<cwd>.r0` keeps the round-0 bytes, which `cwd` holds again afterwards), and its resulting state is saved here; checks and `answer_workdir` use it |
| `cell`, `branch` | str or null | (A6.3) `p6` / `p7` for calibration-cell calls (own labels), null otherwise; `branch`: the p7 LOO variant (`none`, `rotation`, `random`, `leader`), null otherwise (always null for p6) |
| `loo_view`, `loo_exclude` | str, int or null | (`r<k>` calls only: reconcile and repair rounds; absent on every other call; RUNTIME_EQUILIBRIUM §4.2) the LOO variant that built this member's view (`none`, `rotation`, `random`, `leader`; the E arm's is flags.json `loo_view`, default `none` = the pre-registered shared summary, byte-identical; a p7 branch's is its own) and the member excluded from it (1-based, never the member itself; null when nothing is excluded: `none`, round 0, N = 1) |
| `e_arm`, `run8` | str | (`rt` call only) `runtime` and the 8-hex run id `R` of the runtime run (see `e_rt`) |
| `model_ids`, `model_ids_reason` | list[str], str or null | (D3, A6.2) the sorted keys of the envelope's `modelUsage` (the concrete model ids the call ran on); `[]` with the reason (`no result envelope …`, `no modelUsage in the result envelope`, `modelUsage is not a non-empty object`) when missing, never a guess |
| `view` | object or null | see *view* below; null for planner nodes, judges, verifiers, resumed calls |
| `decisive_seen` | bool or null | whether the item's decisive segment is in this call's view (null: no view or no annotation) |
| `started_utc`, `ended_utc` | str | harness clock around the subprocess |
| `exit_code` | int or null | null = harness timeout (`call_timeout_s`) |
| `session_id` | str or null | from the envelope; transcript = `~/.claude/projects/<slug of cwd>/<session_id>.jsonl` |
| `total_cost_usd` | float or null | Claude Code's own cost figure (null if the envelope lacked it) |
| `usage` | object | `input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens` (ints; 0 if absent). P1 tokens = the sum of the four |
| `is_error` | bool | envelope `is_error` (true if absent and exit code ≠ 0) |
| `subtype` | str or null | envelope subtype; `cap_stop` = subtype contains `budget` (unverified label, PLAN 5a checks it) |
| `cap_stop` | bool | see above (P3 cap-hit) |
| `schema_valid` | bool | structured output validated against the class schema (or the plan/selection schema) |
| `answer` | any or null | `structured_output.answer` when schema-valid, else null |
| `answer_sha256` | str or null | sha256 of `json.dumps(answer, sort_keys=True)` |
| `confidence` | number or null | member confidence (logged, never used by a reducer) |
| `evidence_kinds` | list[str] | kinds of the cited evidence items (the first `max_evidence_per_call` = 8 only: the rest is never fact-checked) |
| `evidence_n` | int | number of evidence items the call cited (before the cap of 8) |
| `member_exec` | str | (sandboxed calls only, `member_exec` = `sandbox` and the class has Bash) `sandbox`: `argv` then lists `mcp__eqbox__sandbox_exec` instead of Bash, `--disallowedTools Bash` and `--mcp-config` (the eqbox server, spec `eqbox.json` 0600 beside the raw output) |
| `wall_channel` | str or null | (sandboxed calls) the WALL channel (`c<32 hex>`) mounted at `/eq/tunnel` in this call's containers; null without the WALL |
| `member_exec_calls` | int | (sandboxed calls) `sandbox_exec` invocations (from `eqbox.jsonl`: per call `argv_sha256`, `rc`, `duration_s`) |

*view* object: `kind` (`canonical`, `lens`, `perm`, `kcover`; the effective kind after fallbacks), `member_key`
(`m<i>`, `<node>|m<i>` inside EG, `plan|m<i>` for EG lens planners, `canonical`), `seed` (§3 view seed of
`<item>|<member_key>`), `order` (segment indices of the item manifest in the order shown; unseen segments absent),
`blocks` (k-cover block ids or null), `full` (bool; false = k-cover partial member), `lens_index` (0-based index into
`lenses.json[<CLS>]` or null), `lens_text`, `decisive_pos` (relative position 0..1 of the decisive segment in `order`,
null if unseen or unannotated: M6), `note` (fallbacks, e.g. `kcover->perm (n=3, s=5)` or a perm shift collision).
For k-cover, `order` always contains the item's `pinned_segments` (CR source modules); `blocks` refer to the split of the
remaining (test) segments.

## `plan` (every planner call)

`label`, `role` (`plan` or `m2/3`, `m3/3`), `member`, `call_id`, `valid` (bool), `plan` (list of nodes `{id, owner,
brief, deps, kind, weight}` in topological order, or null when invalid).

## `reduce` (one per reducer decision; `arm`, `label`, `node` as in `call`)

Records of a calibration cell (A6.3: p6 everywhere; p7 `reduce`/`reconcile`; p6 `check`/`equivalence`) additionally carry `cell` (`p6`/`p7`) and `branch` (the p7 LOO variant; null for p6); records of every other arm have neither key. This holds for `reduce`, `reconcile` and `check` below. p6 `reduce` records are round-0 reductions of the 9-member set (`round` 0 where the reducer has one); p7 `reduce`/`reconcile` records are one set per branch, rounds 0..`cells.p7.rounds` (forced: the κ stop and the fixed point are ignored live).

| `reducer` | extra fields |
|---|---|
| `plurality`, `median_ln` | `round` (0 = round 0, k after reconcile round k), `answer` (reduced answer; `median_ln` = exp(median ln)), `top` (members in the top cluster; numeric: members within a factor 2 of the median), `n`, `kappa` (top / n), `quorum` (members needed: ⌈τn⌉ under the pre-registered rule), `stop` (quorum met, or no accepted change: fixed point), `tie_seed` |
| `verify_then_select` | `selected_member` (or null), `repaired` (bool: a repair round ran), `answer`, `select_seed` |
| `finding_clusters` | `t` (support threshold), `kappa` (share of round-0 clusters with support ≥ t, null if none), `clusters` (`{key "<file>\|<claim class>\|<first line>", support, members}`), `verified_singles` (cluster keys a verifier confirmed), `answer` (accepted findings, one representative each) |
| `borda` | `candidates` (member numbers that had an answer), `scores` (Borda sums, same order), `selected_member`, `answer` |
| `medoid_plan` | (`node` = `planning`) `valid` (per plan: G's, lens 1, lens 2), `selected` (index or null), `switched` (true iff the medoid is not G's plan: H3 subgroup) |
| `equivalence` | (RS answer equivalence, COMPARE_eq §12 A0.2; only when round 0 leaves > 1 answer key) `call_id`, `keys` (distinct answer keys shown, by index), `groups` (the verifier's partition of indices, or null), `valid` (false → the string clusters were kept). When valid, plurality, κ, the summary and the gate use the merged key |

## `reconcile` (one per member per reconcile round; M4)

`round`, `member`, `call_id`, `prev_answer`, `proposed_answer`, `changed` (proposal differs from the previous answer),
`accepted` (changed and at least one NEW evidence item verified by the harness), `conformity` (changed and not
accepted), `reason` (`unchanged` | `accepted: verified new evidence` | `conformity: no new evidence` |
`conformity: new evidence not verifiable`), `new_evidence` and `verified_evidence` (lists of `[kind, ref, detail]`,
whitespace-normalised). Conformity rate = conformity / changed.

## `check` (public check runs of checkable answers)

`member`, `round` (0 or 1 = after repair; p6: 0, `cell` `p6`), `passed` (exit code 0 of the item's `public_check` argv run in the member's
copy, minimal environment, with `{"answer": …}` in a file OUTSIDE the copy whose path is `$EQ_ANSWER`; for classes in
`flags.json` `answer_file`, e.g. PF, also the answer text as that file at the top of the copy),
`output_tail` (last 500 characters), `isolation` (`container` / `off`) and `image` (the digest-pinned image, null for
`off`). Under container the check copy is the only writable mount (`/work`), the pristine fixture is mounted read-only
(`/fixture`), `$EQ_ANSWER` is not provided (no pool's public check reads it), `EQ_LEAN_TOTAL` = `check_timeout_s` −
`check_deadline_margin_s`.

## `node` (G and EG: one per plan node, after it ran)

`node` (plan node id), `role` (`n<j>`), `kind`, `owner`, `answer_workdir` (the node's copy; for an EG E-node the
selected passer's copy or null), `chain_source` (CP: the dependency whose copy this node started from, i.e. the one
latest in topological order, ties by node id; null otherwise), `ignored_dep_diffs` (CP: per other dependency with a
copy, `{added, removed, changed}` file lists against the pristine fixture; logged, never merged; COMPARE_eq §12 A1.2).

## `item_arm` (one per item and arm: the analysed unit)

| field | type | meaning |
|---|---|---|
| `item`, `cls`, `label`, `arm` | str | as above |
| `run_tag` | str | as in `call` |
| `status` | str | `ok` (an answer exists) or `partial` (no answer: scored as failure, COMPARE_eq §2) |
| `answer` | any or null | the arm's final answer (input to `oracle.py --answer`) |
| `answer_path` | str | `{"item","label","answer","status"}` JSON file |
| `B_usd` | str | the item-arm cap B |
| `started_utc`, `ended_utc` | str | P4 wall time = ended − started |
| `calls` | list[str] | this arm's own `call_id`s (the shared planner call is listed under both G and EG) |
| `kappa0`, `kappa`, `rounds` | | E with discrete/numeric reducers: round-0 κ (M5, M8), final κ, reconcile rounds run |
| `kappa0`, `t` | | E with the finding-set reducer |
| `selected_member`, `repaired` | | E with verify-then-select or Borda |
| `medoid` | int | EG: index of the plan used (0 = G's plan) |
| `answer_workdir` | str or null | the directory to pass as `oracle.py --workdir` for workdir-scored classes (CP): S* its call's copy; E the selected member's copy (null if none passed); G and EG the final node's copy (for classes in `workdir_answer_classes` every node's copy starts from its last dependency's copy, so edits carry through the graph) |
| `reason` | str | partial G/EG: `invalid plan` / `no valid plan` |
| `wall_requests`, `wall_approved` | int | (WALL runs only) WALL decisions on this item-arm's channels (every authenticated request, denied or approved) and approvals. Requests and their cost count toward the arm that made them (amendment proposal) |
| `wall_used` | bool | (WALL runs only) `wall_requests > 0`: the analysis flag separating item-arms that used the broker |
| `cell` | str | (A6.3, p6 and p7 item-arms only; `eq_analyse` ignores these labels) `p6` or `p7` |
| `n_members` | int | (p6) the round-0 member count (`cells.p6.N` = 9); the arm's `selected_member`/`answer_workdir` (checkable), `kappa0`/`kappa`/`rounds` = 0 (discrete, numeric) or `kappa0`, `t` (finding sets) are as for E, computed on the 9-set |
| `base_label` | str | (p7) the E arm label whose pristine round-0 sessions were branched (`p3`) |
| `branches` | object | (p7) per LOO variant (`none`, `rotation`, `random`, `leader`): `{answer, kappa0, kappa, rounds}`; the item-arm's `answer` is `{variant: answer}`. A p7 item-arm is only written when `base_label` has a complete harness E round 0 in this stage's ledger (else the row is skipped on stderr, nothing recorded) |
| `e_arm` | str | (E_rt item-arms) `runtime` |
| `run8`, `rt_session_id` | str | (E_rt) the runtime run id `R` = first 8 hex of sha256(`<session id>\|headless`) and the leader session uuid passed as `--session-id`; the store is `<XDG_STATE_HOME>/claude-agent-stack/<session id>/eq/<R>/` |
| `h5` | str | (E_rt) the constant note that H5's forked `none` branch is not run under E_rt (the runtime's members are the leader's subagents, not forkable harness sessions): reported, not run |
| `rt_validated`, `rt_status_reason`, `rt_partial` | any | (E_rt, when `result.json` parsed) the runtime's own `validated`, `status_reason` and `partial` verbatim; logged, never scored |
| `answer_workdir_reason` | str | (E_rt, workdir classes (CP), when `answer_workdir` is null) why the runtime's selected patch was not applied: no selected patch in `result.json`; the patch is not a file inside the leader's project dir; or `git apply failed (exit N): …` |
| `result_error` | str | (E_rt) exception class name when the store's `result.json` could not be read or parsed (`OSError`, `JSONDecodeError`); the item-arm is then `partial` |
| `bundle_mismatch` | object | (E_rt; **planned**, the code does not write it yet; the lead's decision) when `plan.json`'s bundle differs from the q cell's selected bundle (the calibrated `params` the q arm is meant to run), the item-arm records `bundle_mismatch` = `{plan_bundle, expected_bundle}` (both full bundle objects as read), `status` `partial`, no `rt` call, the item is excluded from the q tests (report only). Written after the `plan` step, before `start` |

## `e_rt` (E_rt only: one per `stack-eq` step; A6.5, `eq_harness.py run --e-arm runtime`)

The runtime arm's headless sequence (the harness's `run_e_rt`): `stack-eq plan --run R --headless --session S
--brief-file F`, then the consent file (0600; `{"token": "Run eq:R", "plan_sha256"}`, sha256 of the store's
`plan.json`), then `stack-eq start --run R --headless --consent-file P`, then the `rt` call. Environment: `member_env`
plus `XDG_STATE_HOME` and the `STACK_EQ*` knobs of the harness's terminal; `CLAUDECODE` absent; header `eq-mode:
manual` in the leader prompt (COMPARE_eq §12 A6 implementation note (d)). A refused step ends the item-arm as `partial`
with `reason` `stack-eq plan refused`, `no plan.json in the store (<error class>)` or `stack-eq start refused`.

| field | type | meaning |
|---|---|---|
| `item`, `label`, `arm` | str | the item-arm (`arm` is `E`) |
| `step` | str | `plan` or `start` |
| `argv` | list[str] | the exact stack-eq argv |
| `rc` | int or null | exit code; null = OSError or timeout (`E_RT_STEP_TIMEOUT_S` = 300) |
| `output_tail` | str | last 1000 characters of stdout + stderr (or the exception) |
| `run8` | str | the runtime run id `R` |

## `wall` (WALL runs only: the broker's audit log, copied into the ledger)

The broker (`../wall/eq_wall.py serve`) writes an append-only, hash-chained audit log in its host-only state dir
(`<state_dir>/audit/<run_id>.jsonl`; never under the tunnel root, never mounted). The harness verifies the whole chain
and copies every new record into the ledger after each sandboxed call's channel is closed and at run end (a broken
chain, or a broker that died or stalls, is an `IsolationError`: `run_abort`). The raw request bytes (`raw_b64`) stay in
the audit log only. `eq_wall.py replay` re-derives every decision from the audit log, the policy and the store
prefixes (`verdicts_n`, `consents_n` + their sha256).

| field | type | meaning |
|---|---|---|
| `wall_run_id` | str | the WALL run id (as `run_start.wall.run_id`) |
| `wall_seq`, `wall_sha256`, `wall_ts_utc` | int, str, str | the audit record's own `seq`, `record_sha256`, `ts_utc` |
| `wall_record` | str | `broker_start`, `channel_open`, `request`, `decision`, `result`, `abuse`, `store_error`, `channel_close`, `broker_stop` |
| `item`, `label` | str or null | the item and arm label whose call owns the channel |
| `channel` | str | the channel (`c<32 hex>`); `call_id` on `channel_open` = the member call |
| `broker_start` | | `run_id`, `nonce_sha256`, `policy_sha256`, `broker_sha256`, `mechanism`, `kinds_allowed`, `limits`, `manifest_tools_n` (tools in the TOOLS manifest, null if unreadable), `pid` |
| `request` | | `file` (`req-<id>.json`), `raw_sha256`, `verdicts_n`, `verdicts_sha256`, `consents_n`, `consents_sha256` (store prefixes seen; −1 = integrity failure), `snapshot_error` (the entry was refused before parsing, e.g. hard-linked or too large), `infiles` (`{name: sha256 or null}`: each `in-<name>` file the request names, snapshotted WITH the request; the decision, the consent's `action_sha256` and the execution all use these bytes; null = refused) |
| `decision` | | `request_seq` (the `request` record's audit `seq`), `request_id`, `approved` (bool), `code` (`approved`, `kind`, `not_allowlisted`, `no_verdict`, `consent_required`, `tools_manifest`, `manifest_unavailable`, `never`, `args`, `argv`, `url`, `domain`, `identity`, `token`, `content_hash`, `replay`, `quota`, `schema`, `malformed`, `too_large`, `entry`, `store_broken`), `reason` (one line), `next` (`ASK USER: …` when only the user can unblock it), `class_sha256` (what a security-auditor verdict binds to), `action_sha256` (what a user consent binds to), `consent_used` (the consent record consumed, single use) |
| `result` | | `request_seq`, `request_id`, `rc` (null = timeout), `timed_out`, `truncated`, `error`, `output_sha256`, `output_bytes`, `scrubbed` (secret patterns replaced), `duration_s`, `web` |
| `abuse` | | `what` (non-regular entry removed, tunnel quota exceeded, channel dir unusable, response blocked), `tripped` (the channel is never served again) |
| `store_error` | | `store` (`verdicts` / `consents`), `error` |
| `channel_close` | | `requests` (authenticated requests on the channel), `tripped` |
| `broker_stop` | | `requests` (run total), `channels_closed`, `tripped` (channel list) |

Joins: `call.item, call.label` (or `charged_to`) → `item_arm`; `call.session_id` → transcript; `reconcile.call_id`
and `item_arm.calls` → `call.call_id` (unique within a ledger). Tokens and cost of an item-arm: sum over `call` records
whose `item` matches and whose `charged_to` contains its label. An item-arm interrupted by an environment failure has
`call` records but no `item_arm` record; its declared `p9`/`q9` re-run (COMPARE_eq §10) is a separate item-arm.

# Mediator ledger (`$R/<stage>/<item>/<label>/mediator.jsonl`; MEDIATOR.md §1, COMPARE_eq §12 A0)

Written by `eq_mediator.LiveMediator` for E and for every E-node of EG (live), and by `eq_mediator.py offline-facts`
for S*, G and the plain nodes of EG (after the freeze; `fact` records only, `offline: true`). Append-only JSONL with the
same common fields as above (`schema_version`, `seq`, `ts_utc`, `record`), plus `stage`, `item`, `label` and, for live
records, `arm`, `node` (null for E) and `run_tag`; every record also carries `isolation` and `image` (as in `check`:
the backend that ran the fact re-runs). Members are anonymised as `m1`..`mN`. Fractions are written as
`{"num", "den", "float"}`; accepted findings as the finding objects. `eq_freeze.sh --collect` copies these files to
`$EQ/runs/<stage>/inputs/mediator/<item>/<label>/mediator.jsonl`.

The mediator of a p7 branch (A6.3) writes to the p7 label's own file and adds `cell` (`p7`) and `branch` (the LOO
variant) to EVERY record of that mediator (the base fields); no other mediator has these keys.

| record | fields |
|---|---|
| `claim` | one per member per round: `member`, `round` (0, then reconcile round k), `answer_raw`, `answer_norm` (= `cluster_id`: the class answer key, after any RS equivalence merge; numeric: null), `cluster_id`, `confidence` (logged only), `fact_keys` (the cited evidence, as fact keys, in citation order) |
| `fact` | one per distinct fact per item-arm, written when first checked (round-0 facts right after round 0): `fact_key`, `kind`, `ref`, `detail_norm`, `status` (`verified` / `refuted` / `unverifiable`), `method` (how it was decided, e.g. `substring of lines l-1..l+1`, `re-run twice in fresh copies`, `not allow-listed`, `timeout 60s`, `wall-time budget exhausted`), `output_sha256` (commands), `cited_by` (`[{member, round, cluster}]` at write time; later citations are in `claim.fact_keys`), `offline` |
| `change` | one per changed answer in a reconcile round: `member`, `round`, `prev_answer`, `from_cluster`, `to_cluster`, `new_fact_keys` (evidence new to that member), `gate` (`evidence` = accepted with a verified new fact; `conformity` = rejected, the previous answer kept) |
| `result` | one per E-node: `answer` (the R0 end answer; checkable and long-form: the selected member number), `reducers` (discrete, numeric and finding sets: `R0`, `R1`, `R2`, `R3`, `ENS` over the round-0 outputs, plus `R0_final` = the live end answer; R2 is R0 until weights are fitted offline; other families: `R0` only), `kappa` (`{value, label: "agreement, not probability"}`), `provenance` (`[{fact_key, kind, status, members, clusters}]`), `dissent` (per cluster not adopted: `{cluster, size, verified (≤ 2 keys), refuted}`) |
| `attribution` (per round) | (A6, RUNTIME_EQUILIBRIUM §4.1; discrete, numeric, finding-set, long-form and checkable E-nodes; written after round 0 and after every reconcile or repair round, BEFORE the end-of-node line below) one per round: `round` (int: 0, k), `loo` (`{"m<i>": {answer, selected, same, stable}}`: the round's reducer without member i; `same` = R(S∖i) equals R(S); `stable` = `same`, for checkable S∖i still holds a passer), `lambda` (λ_r = share of members with `stable`), `pivotal` (`["m<i>", …]`: members with not `same`), `seed` (the tie seed `derive(eq\|ties, <seed key>\|loo\|r<round>)`, keyed by the answer, never the member index). The end-of-node `attribution` below has NO `round`: analysis keeps the two apart on that key (`eq_analyse`/`eq_route2` M11-M13 read only lines without `round`; `eq_calibrate` only lines with it) |
| `attribution` (end of node) | one per E-node: `loo_round0`, `loo_final` (member → R0 result without that member; checkable: first passer, long-form: Borda over the STORED judge rankings, no new call), `shapley` (agreement game, member → φ; finding sets: share of final findings recovered), `hhi` (Σ (φ_i/Σφ)², null if Σφ = 0), `decisive_facts` (`{reconcile, R1, R3}`: fact keys; see MEDIATOR §2), `cpu_s` (M18) |

Fact keys (dedupe): `file_line|<path>|<line>|<sha256 of the whitespace-normalised quote>`, `quote|<path>|<sha256>`,
`command|<argv JSON>|<fixture id>|<sha256 of the claim>` (also `test|…`), `url|<url>`, `<kind>|<sha256 of ref and
detail>` otherwise.

# Grading files (`$EQ/runs/<stage>/`; written after the freeze, never read by any arm)

- `grading/CR/batch.json`: the grader's input, a JSON list of `{rid, type (match | unmatched), finding {file, line,
  claim}, seeded_bug {file, line, description} (match only), code_excerpt}`; `rid` = batch token `g<8 hex>`.
- `grading_keys/CR.key.json`: `tokens` (token → `{unit, rid}`; `unit` = JSON `[item, label, node, member]`, node and
  member null for the item-arm's own answer; `rid` = the oracle's `f<i>` within that answer), `units` (unit → file
  stem under `grading_keys/CR_units/`), `regrade` (tokens of the 20 % regrade sample). Also `grading_keys/<CLS>.key.json`
  for RS/DS/OE batches.
- `grading_results/CR.jsonl`: one line per unit per `cr-grade` run: `ts_utc`, `verdicts_file`, `item`, `label`, `node`,
  `member`, `exit` (oracle exit code), `score`, `detail` (the oracle's).
- `grading_results/<PF|CP|ES>.jsonl`: one line per item-arm per `score` run: `ts_utc`, `item`, `label`, `exit`, `score`
  (verbatim; ES may be the string `"inf"`), `score_num` (float, null if infinite or missing), `score_inf` (bool),
  `detail`, `isolation` and `image` (PF/CP: the backend and image that ran the oracle; ES: `host (oracle runs no
  answer code)`). A `partial` item-arm with no answer is not sent to the oracle: `exit` null, score 0 (ES: `"inf"`).
  PF and CP results (and CR's) come only from the oracle's single `EQV1 <nonce> <json>` line (R1 F1); without
  exactly one such line: `exit` 1, `score` null, `detail` `oracle error: N authenticated verdict lines (exit R)`.
  What `score` does then, and when the one authenticated line is a JSON verdict whose score parses to null (answer
  code killed the checker: `checker error`, R2c F1), is `flags.json` `no_verdict_policy` (N24#5: answer code shares
  the oracle's uid and output stream and can suppress the line, e.g. `kill -9 -1` at compile time or more than 64 KiB
  written after the verdict, turning a 0 into "unscored", which both routes drop):
  - `"zero"` (DEFAULT since the USER's decision of 2026-10-05, `COMPARE_eq.md` §12 A3; it changes the pre-registered
    scoring; PF/CP only, the EQV1 classes `score` runs): isolation is re-checked (`preflight`; an unhealthy backend
    stops `score` with exit 2 and writes nothing for the item-arm), the oracle runs once more, and if there is still
    no score: `exit` kept (1 without the line, else the oracle's; counted as an oracle failure), `score` 0,
    `score_num` 0.0, `score_inf` false, `detail` `no authenticated verdict (scored 0)` or `authenticated verdict
    without a score (scored 0)`. A verdict with a score from the re-run is recorded as usual. A host-side
    `oracle error: …` (e.g. OSError; no answer code ran) is never zeroed;
  - `"unscored"` (the originally pre-registered behaviour; sensitivity re-scores only): the line above, or the null
    verdict as is, `score` null (the item-arm is unscored).
  Any other value: `score` refuses (exit 2). A flags file without the key (frozen before N24) scores `"unscored"`.

## Member-level grades (`grading_results/members/`; A6.3; written after the freeze, read by `eq_calibrate.py`)

Member answers of p3 (round 0 and the checkable repair round), p6 (9 members) and p7 (per branch) are graded like
item-arm answers, blinded. **Planned: the commands below are being added to `eq_harness.py` (branch eqr-harness) and
the fields marked "planned" are the harness builder's checkpoint, not yet written by any code; `eq_calibrate.py`
(`read_stage`) is the reader and fixes the names it consumes.**

- `members/<CLS>.jsonl` (`PF`, `CP`, `RS`; ES needs none: the frozen truth file scores a member answer): one line per
  graded member answer, `{item, label, member, round, branch, score, …}`. `label` the arm label (`p3`, `p6`, `p7`);
  `member` the 1-based member number (**0 = a branch's reduced answer**, the H5 comparison: `branch` `none`);
  `round` 0 (round-0 answer) or the reconcile/repair round; `branch` the p7 variant, null for p3/p6. `score`: 1/0 as in
  `grading_results/<CLS>.jsonl` (the planned further fields mirror that file: `ts_utc`, `exit`, `score_num`,
  `score_inf`, `detail`, and for PF/CP `isolation`, `image`). Written by `eq_harness.py score --members` for PF and CP
  (round-0 and repair members, `node` null; CP's directory is the member's `cwd`, or the p7 member's `branch_workdir`,
  through `check_copy`, never the member's own copy) and by `eq_harness.py rs-grade --verdicts` for RS (planned).
- `members/CR_findings.jsonl` (planned): written by `cr-grade` (batch built by `cr-grader-input --with-members`), one
  line per member finding: `item`, `label`, `member`, `round`, `finding` (the answer element, the object as the member
  gave it), `bug` (the index of the seeded bug it matches, from the oracle's `detail.per_finding`; null), `verdict`,
  `n_seeded` (seeded bugs of the item). A duplicate finding takes the grade of the kept index it duplicates.
- RS member grading (planned): `eq_harness.py rs-grader-input` runs the RS oracle's `--grader-input` on every RS member
  answer (deduplicated by `rid`), shuffles one blinded batch (seed `eq|grader ^ sha256("<stage>|RS|members")`) into
  `grading/RS/` with its key in `grading_keys/RS.key.json`; `rs-grade --verdicts <file>` routes the verdicts back, runs
  the oracle's `--grade` and writes `members/RS.jsonl`.
