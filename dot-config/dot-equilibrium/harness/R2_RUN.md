# R2 independent run (test-engineer), 2026-10-05, after the R1 review fixes

Environment: cwd /tmp/claude-501, TMPDIR=/tmp/claude, Bash cannot write under T, so a copy of EQ-T was made at
`/tmp/claude/eq/equilibrium` for the runs that need to write beside the sources (suite re-run, isolation suite,
route fixture). No product file changed (no git diff possible under T; only `harness/tests/mutations.out` and this
file were written, via Edit/Write). No tests were added: no defect found. Sequential, no docker/brew/claude -p/spend.

## 1. Harness suite

Command (cwd /tmp/claude-501, from EQ-T):
`uv run --no-project --with pytest --with duckdb --with-requirements harness/eq_harness.py pytest -q -p no:cacheprovider harness/tests`

| Where | Result |
|---|---|
| real EQ-T | 393 passed, 2 failed (80 s) |
| copy under /tmp/claude/eq | 395 passed, 0 failed (83 s), same command from the copy |

The 2 failures, both classified as location/sandbox effects (both pass in the /tmp copy, so not product bugs):
- `test_shell.py::test_freeze_installs_and_writes_sidecar` (known). First error lines:
  `E AssertionError: assert False` / `E + where False = exists()` on
  `.../equilibrium/runs/p/inputs/raw/p/RS-0001/p...` (`--collect` output missing under the real location; root
  cause inside T not isolated, unverified; DRYRUN.md recorded the same).
- `test_verifier_lows.py::test_low1_score_copy_keeps_tests_pristine` (not in the brief's list; same class as DRYRUN.md):
  `PermissionError: [Errno 1] Operation not permitted: '.../harness/tests/fixtures/items/CP/fixtures/base/tests'`
  (the test chmods a path under the sandbox-denied T tree).

## 2. Harness mutations

`cd EQ-T && uv run --script harness/tests/mutations.py` (TMPDIR=/tmp/claude): BASE unmutated 113 selections PASS;
**130/130 KILLED, 0 problems, rc 0, no survivors**. Every verdict is `pytest exit 1` (test failure), none is exit
2/4 (collection/import error), M121-M130 included:

M121 receipt required rows re-checked, M122 FAIL row in PASS receipt refused, M123 broker reports frozen hashes (W5),
M124 close_channel waits out busy broker (N24#3), M125 broker.stderr 0600 (N24#6), M126 eqbox server reads no uv
config / fixed cwd, M127 no_verdict_policy zero scores 0, M128 zero re-checks isolation first, M129 eq_check E12 torn
last line, M130 eq_check E12 seq = line number.

`harness/tests/mutations.out` refreshed (first 120 mutation lines byte-identical to the previous file; BASE 105 -> 113
selections; M121-M130 appended; footer `mutations: 130, problems: 0`; verified identical to the raw run output).

## 3. Wall

- `wall/tests`: 98 passed, 2 skipped (8.5 s) (`uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider wall/tests`).
- `uv run --script wall/tests/mutations.py`: BASE 41 selections PASS; **50/50 KILLED, 0 problems**, all `pytest exit 1`.
  Output identical to the existing `wall/tests/mutations.out` (left unchanged).

## 4. isolation/repo-stage/tests (all)

`python -m pytest -v -p no:cacheprovider isolation/repo-stage/tests` in the /tmp copy: **260 passed, 1 skipped,
0 failed** (22 min 49 s). Not run in the real location: the first attempt there was very slow (the machine was also
running a competing instance of the same suite, which I stopped) and I did not wait it out; the copy is the
complete result. The skip is the suite's own (not investigated, not a failure).

## 5. Route 1 vs route 2

Fixture: `analysis-r2/make_fixture.sh` into /tmp/claude/fx (dev stage, stub_claude, 84 item-arms, 740 ledger lines,
synthetic grading). Two run dirs: A = the ledger as generated (no wall_used anywhere, so the flag is a no-op);
B = the same ledger with `wall_used: true` set by jq on the 56 item_arm records of items matching DEV1|DEV3
(so `--exclude-wall-used` actually removes data). Mediator files copied to `inputs/mediator/<item>/<label>/` for
route 1. Commands, each with and without the flag:
`eq_analyse.py --ledger <rd> --out <o> [--exclude-wall-used]` and `eq_route2.py --ledger <rd> --out <o> [--exclude-wall-used]`
(all rc 0). Compared with `scratchpad/rdiff.py` (DRYRUN.md name map, rel tol 1e-6).

| Run | r1 rows | r2 rows | cells compared and agreeing | DISAGREE |
|---|---|---|---|---|
| A | 1501 | 1935 | 1204 | 0 |
| A --exclude-wall-used | 1501 | 1935 | 1204 | 0 (output byte-identical to A in both routes) |
| B | 1501 | 1935 | 1204 | 0 (n_wall_used sums to 56 in both routes) |
| B --exclude-wall-used | 1484 | 1920 | 1190 | 0 (n_wall_used 0 in both; route 2 meta wall_used_excluded = 56) |

**Verdict: the two routes agree on every shared cell, with and without --exclude-wall-used; 0 disagreements.**
Agreeing quantities (B excl.): H1 38, H2 41, H3 41, M10 96, M11 30, M12 38, M14 20, M15 8, M18 22, P1/P1_sens/P4/P5/P5_sens 96
each, P2 56, P3 160, over_cap 64, n_dup_item_arm 28, n_missing 20, n_unscored 20, n_wall_used 28.
Only-in-one-route cells are the same by-design set as DRYRUN.md section 2 (route 2 class `all`, EG-S*, measured/ratio, M2/M3;
route 1 n_dropped/n_inf/n_missing/hhi_median/cpu_s_max, M13 round0/final split). Caveat as before: stub arms answer alike,
so agreement on M13/M15/AUROC is weak evidence; the wall_used filter, however, is exercised on real excluded rows
(1501 -> 1484 and 1935 -> 1920 rows, same quantities lost in both routes).
Not checked: I did not diff route 1's `lists.excluded_wall_used` against route 2's list (jq query on meta.json errored in my one-liner; counts agree via n_wall_used).

## Defects found

None in product code. Survivors: none.

## R2d — after the R2 review fixes (security-engineer, 2026-10-05)

Fixes, each proof test seen failing first: R2b (a) `check_probe` requires `TUNNEL_PROBE_HOST_ROWS`
(`test_probe_receipt_requires_the_host_side_rows`); R2c F1 `no_score()` at both `score` sites
(`test_zero_policy_scores_an_authenticated_null_verdict_zero`, plus the re-run, `unscored` and host-error cases);
R2c F2 `is_identity()` in `eq_wall.py` (`test_a_directory_named_channel_json_is_purged`,
`test_a_tripped_channel_purges_a_directory_named_channel_json`); `no_verdict_policy` default `"zero"` (USER,
`COMPARE_eq.md` §12 A3; `test_default_policy_is_zero`); `eq_check.sh` E12 comment. Same environment as above (copy at
`/tmp/claude/r2d/equilibrium`, rsynced from EQ-T after every edit):

| Check | Result |
|---|---|
| `wall/tests` | 100 passed, 2 skipped |
| `wall/tests/mutations.py` | BASE 43 selections PASS; 52/52 KILLED (W51-W52 new), all `pytest exit 1` |
| `harness/tests` | 401 passed, 0 failed |
| `harness/tests/mutations.py` | BASE 117 selections PASS; 136/136 KILLED (M131-M136 new; M121/M127 anchors updated), all `pytest exit 1` |
| `ruff check harness wall` | clean |

Both `mutations.out` files refreshed and verified identical to the raw run output (less uv's "Installed" line).
