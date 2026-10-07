# Independent dry run (test-engineer), 2026-10-05

Everything ran in copies under `$TMPDIR/dr` (a copy of EQ-T made after the F1 oracle patch; no product file touched).
Zero spend: stub_claude only, isolation off, no docker, no `claude -p`.

## 1. Test suites

| Suite | Result |
|---|---|
| harness pytest (`eq_harness.py` requirements, duckdb) | 365 passed (copy). In the real worktree: the 2 known failures, cause below |
| `harness/tests/mutations.py` | 120/120 killed, 0 problems |
| `wall/tests` | 93 passed, 2 skipped |
| `wall/tests/mutations.py` | 43/43 killed, 0 problems |
| `items/test_f1_verdict_channel.py` | 16 passed (and 16 failed on the pre-patch oracles) |
| real pools through the real `eq_freeze.sh` | CP, CR, PF and the other pools verify (`shasum -c`); freeze rc 0 |

Cause of the two known failures (both pass in a `$TMPDIR` copy, so both are location/sandbox effects, not product bugs):
- `test_verifier_lows.py::test_low1_score_copy_keeps_tests_pristine`: confirmed. `PermissionError: Operation not
  permitted` on `harness/tests/fixtures/items/CP/fixtures/base/tests` (the test chmods a path under the
  sandbox-denied `next-steps-7c1c7f` tree).
- `test_shell.py::test_freeze_installs_and_writes_sidecar`: fails at the last assert (`inputs/raw/.../stdout.json`
  missing after `eq_freeze.sh --collect`), passes outside the worktree. Root cause inside the worktree not isolated
  (unverified); the only difference between the two runs is the location of the harness files.

## 2. Route 1 vs route 2 on one stub ledger

Ledger: `analysis-r2/make_fixture.sh` (dev stage, 84 item-arms, 740 ledger lines, synthetic grading). Route 1 was
given the mediator files as `inputs/mediator/<item>/<label>/mediator.jsonl` (otherwise it skips M11-M15, M18), route 2
`--mediator-root raw`. Rows: route 1 1405, route 2 1839. Same bootstrap seeds, so CIs also match.

Name map used (route 1 -> route 2): `win/tie/loss` -> `H_desc`; H stats `delta, n, discordant, pi` -> `delta_hat,
n_comparison, n_discordant, pi_hat`; `P1/P5 sens_*` -> `P1_sens/P5_sens`; `Over-cap` -> `over_cap`; M11
`share_dictator, k_dictator, hhi_mean` -> `dictator_share, n_dictator, mean_hhi`; M12 `facts_per_answer, k_refuted,
k_unverifiable, share_*` -> `facts_per_item_arm, refuted, unverifiable, *_rate`; M14 `k_decisive, share_decisive` ->
`n_with_decisive, decisive_share`; M15 `k_disagree, share_disagree` -> `n_disagree, disagreement_rate`; M18
`equivalence_n` -> `equivalence_calls`.

**Disagree: 0 values** out of all mapped cells. Agree (cells): H1 44, H2 44, H3 44, H_desc 40, M10 96, M11 40, M12 70,
M14 30, M15 12, M18 32, over_cap 64, P1 96, P1_sens 96, P2 56, P3 160, P4 96, P5 96, P5_sens 96 (tolerance 1e-6 rel).

Only in one route (by design or by stated assumption):

| Quantity | Only in | Likely cause |
|---|---|---|
| H1/H2/H3/H_desc, M10-M15, M18, M12 with class `all` | route 2 | route 2 pools a class `all` row; route 1 pools only P1/P4/P5 (route 1 assumption: primary family per scored class) |
| P1, P4, P5 for contrast `EG-S*` (all classes) | route 2 | route 1 computes E-G, E-S*, EG-G only; EG-S* is win/tie/loss only (route 1 assumption) |
| P1/P4/P5/P*_sens `measured`, `ratio` | route 2 | route 2 reports ratio and a measured flag |
| `n_dropped` (P1/P4/P5), `n_inf` (P2), `n_missing` (H, win/tie/loss), `hhi_median`, `n_hhi_null`, `n_item_arms`, `cpu_s_max`, `n_auroc` | route 1 | route 2 does not emit these counts |
| M2, M3 | route 2 | route 1 does not implement them |
| M13 | both, different stats | route 1 `share_stable_round0/final`, route 2 one `estimate`; both 1 on stub data, so which one route 2 means is not testable here |
| M12 `verified` count | route 2 | route 1 has `share_verified` only |
| warning for non-numeric CR score `999` | route 1 | route 2 ignores it silently (same rows) |

Caveat: stub arms answer alike (grading is synthetic, M13/M15 flat, AUROC undefined), so agreement on those
quantities is weak evidence.

## 3. Fault injection (stage d, stub run, real items frozen with the real `eq_freeze.sh`)

`eq_check.sh` baseline: PASS (rc 0).

| Fault | eq_check.sh | Route 1 | Route 2 | Caught? |
|---|---|---|---|---|
| truncated last ledger line | FAIL E11 (by accident: `jq -s` fails, spend = NaN) | warns "torn last line skipped" | warns malformed line and "no run_end" | yes (3 detectors) |
| truncated middle ledger line | FAIL E11 (same accident) | rc 2, hard error | rc 0, skips with a warning in meta.json | yes, but routes differ |
| duplicated item_arm | PASS | warns "2 item_arm records; using ..." | silent, same rows | route 1 only |
| wrong CP pool hash at freeze | `eq_freeze.sh` refuses: "pool CP does not verify" (rc 1) | n/a | n/a | yes |
| CP pool.sha256 edited after freeze | FAIL E4 (sidecar) | no | no | yes (eq_check) |
| CP oracle.py edited after freeze, pool.sha256 untouched | FAIL E4; `shasum -c pool.sha256` rc 1 | no | no | yes |
| grading line removed (item with a current line) | PASS | silent in warnings, `n` 3 -> 2 and `n_missing` 1 | silent, `n_comparison` 3 -> 2 | not flagged, only visible in the counts |
| forged non-EQV1 verdict (raw `{"score":1.0}`, wrong-nonce EQV1) | n/a | n/a | n/a | yes: `run_oracle` -> `(1, "oracle error: 0 authenticated verdict lines")` |
| two EQV1 lines | n/a | n/a | n/a | yes: `(1, "oracle error: 2 ...")` |
| forged lines then the real EQV1 line | n/a | n/a | n/a | forged ignored, real verdict `0.0` returned (correct) |
| real CP oracle + answer that prints forged lines (off backend, end to end) | n/a | n/a | n/a | score 0.0 |
| oracle without EQV1 (unpatched style) | n/a | n/a | n/a | refused: `(1, "oracle error: 0 ...")` |
| tunnel receipt, result FAIL | n/a | n/a | n/a | refused by `Wall.check_probe` |
| tunnel receipt, result PASS, one required row missing | n/a | n/a | n/a | **accepted** |
| tunnel receipt, result PASS, no `rows` key | n/a | n/a | n/a | **accepted** |
| tunnel receipt, result PASS, a FAIL row | n/a | n/a | n/a | **accepted** |

## Defects, by owner

- security-engineer (harness/wall), low: `Wall.check_probe` (`harness/eq_harness.py` around lines 1973-1991) checks only
  `result == "PASS"`, `config_sha256` and the image ids. It never re-reads `rows`, so a receipt marked PASS with a
  missing required row, no rows or a FAIL row is accepted. The rows are checked only when the probe writes the receipt.
  Suggest re-validating `rows` against `TUNNEL_PROBE_REQUIRED` in `check_probe`. Needs write access to the state dir to
  exploit, so defence in depth.
- security-engineer (harness), info: `eq_check.sh` has no ledger-integrity check of its own; a truncated ledger is
  caught only through E11's jq failure. It has no check on grading files or duplicate item_arms (pre-item gate by
  design).
- data-engineer (route 2): duplicated `item_arm` is silent (no warning, no count); route 1 warns. No `n_missing`/`n_dropped`
  counts, so a missing grading line shrinks `n_comparison` without any trace beyond the number.
- data-scientist / data-engineer (routes): a torn line in the middle of the ledger is a hard error in route 1 (rc 2) and a
  skipped line in route 2: the policies should be aligned. Route 1 does not warn when `run_end` is missing, route 2 does.
  Route 1 omits M2, M3 and the EG-S* P-contrasts; route 2 omits several count stats (list above). M13 stat naming
  differs and cannot be checked on stub data.
- No defect found in the F1 verdict channel on the harness side: forged, wrong-nonce, duplicate and missing EQV1 lines
  are all refused or ignored as designed.

Last check: `; date '+%F %R'` printed below.
