# equilibrium: the agent-equilibrium experiment (EQ-T, tracked)

The stack's pre-registered experiment on agent equilibria: does an ensemble of same-type agents with views, a reducer and
a mediator (arm E), or a planner graph with E-nodes (EG), beat the single expert agent (S\*) and the plain planner graph
(G) at equal USD budget per item? `PROPOSAL.md` is the design. `COMPARE_eq.md` is the pre-registration and wins where the
two differ: arms, stages, hypotheses, scores, statistics, grading, stop rules and the dated §12 amendments, including A4
(the `Skill` tool for every arm). `CONTRACT.md` is the pool and harness interface. Status: **pre-freeze**. Nothing here
has made a paid call. The tests run `harness/stub_claude` as `claude`.

This tree is the working tree that lived untracked at `.claude-work/worktrees/eq-t-1005/.claude-work/equilibrium`
(EQ-T, as of 2026-10-06). It is tracked here with all its features: the harness with the Apple `container` backend (the
R3 port), the T1b A4 edits, the seven item pools with their oracles, the probes and the derivation scripts with their
outputs. Paths are relative to the repository root. The former STAGE is `equilibrium`, and the former main checkout M
is `.`. Where a script needs a path, it derives it from its own location. The one exception is the host Lean project,
`$HOME/lean/stack_mathlib`, which lies outside the repository. This is amendment A5 in `COMPARE_eq.md`, with the
per-file record in [`PATH_RELATIVISATION.md`](PATH_RELATIVISATION.md).

Since 2026-10-07 the tree lives at `dot-config/dot-equilibrium/` (amendment A9, "repository move"; `lib/` did not
move). Earlier texts, the amendments A0-A8 and the A5 record name it `equilibrium/`: read that as
`dot-config/dot-equilibrium/`. The A5 record's keys follow the new path; `tests/equilibrium_paths.py` maps them back
to `equilibrium/` for the commits before the move.

## Layout

| path | what |
|---|---|
| `PROPOSAL.md`, `COMPARE_eq.md`, `CONTRACT.md` | the design, the pre-registration (wins), and the item-pool/harness contract |
| `PATH_RELATIVISATION.md`, `.json` | the A5 record: the rules and every changed file with its old and new sha256. The checker is `../../tests/equilibrium_paths.py` |
| `MEDIATOR.md`, `ISOLATION.md` | the mediator design (COMPARE_eq §12 A0) and the isolation backend assessment |
| `derive_numbers.py`, `mediator_numbers.py`, `shift_check.py`, `refute_check.py`, `r3_check.py` (+ `*.out`), `seeds.out` | the derivations behind COMPARE_eq §8 and MEDIATOR, with their recorded outputs |
| `harness/` | `eq_harness.py` (uv PEP 723 script: seeds, flags, views, schedule, run, scoring, the `container` isolation backend), `eq_mediator.py`, `eq_analyse.py` and `eq_route2.py`/`.sql` (analysis routes 1 and 2), `eq_check.sh`, `eq_freeze.sh`, `flags.json` (`common_tools: ["Skill"]`, A4), `stub_claude`, `tests/`. Details: `harness/README.md`, `harness/LEDGER_SCHEMA.md` |
| `items/<CLS>/` | the pools PF, CP, CR, RS, ES, DS, OE: `manifest.jsonl`, `schema.json`, `oracle.py` + `oracle/`, `fixtures/`, `selftest.sh`, generator, and `pool.sha256` over all of them. `items/graders/` holds the grader briefs |
| `wall/` | the WALL broker, client and policy as staged for the harness (`harness/tests/test_wall_integration.py` reads it). The installed copy is [`../../lib/eq-wall`](../../lib/eq-wall/) (hash-pinned in its `REVIEW`). In this repo the harness takes that copy first (A5). `policy.default.toml`, `WALL_DESIGN.md` and `INSTALLER_WALL.md` differ from the lib copy, and the lib copy is the one installed |
| `isolation/` | the superseded Docker staging scripts (user decision 2026-10-05; the harness never uses them). The live backend is [`../../lib/eq-container`](../../lib/eq-container/) |
| `analysis-r1/`, `analysis-r2/` | the zero-spend fixtures of analysis routes 1 and 2 |
| `proof-check/` | the Lean check of a PF statement |

Not tracked (`.gitignore`): any `runs/` below this directory (a stage's ledger, transcripts and raw JSON when
`EQ_ROOT` or `EQ_RAW` points here), `.eq_deps/` work files, logs (`isolation/build.log` stayed in EQ-T), caches. Tracked on purpose:
`items/RS/fixtures/corpus/runs/` (a cleaned-up fixture in `RS/pool.sha256`, not run output) and
`items/PF/oracle/build/` (the PF oracle's build records). `items/RS/manifest.jsonl` (2.8 MB) is the only file over
1 MiB. `tests/test_equilibrium_layout.py` pins all of this: the layout, every `pool.sha256`, the size cap, the ignores
and the executable bits.

## Tests (zero spend)

Run the harness suite in its own pytest process: its `tests/conftest.py` collides with the repo's `tests/conftest.py`
in one run. Run it from a scratch copy, so nothing it writes lands in the checkout:

```sh
T=$(mktemp -d) && rsync -a dot-config/dot-equilibrium/ "$T/dot-equilibrium/" && cd "$T/dot-equilibrium" &&
  EQ_CONTAINER_DIR=<repo>/lib/eq-container \
  uv run --no-project --with pytest --with duckdb --with-requirements harness/eq_harness.py \
  pytest -q -p no:cacheprovider harness/tests
```

Expected on 2026-10-06:
- From the copy with `EQ_CONTAINER_DIR`: 451 passed, 1 skipped (the in-place layout check).
- From the copy without it: 447 passed, 5 skipped (the 4 tests that need `lib/eq-container`, plus that check).
- In place (`cd dot-config/dot-equilibrium` in a checkout, no `EQ_CONTAINER_DIR`): 452 passed.

The other suites, from the same copy: `wall/tests` 100 passed, 2 skipped. The selftests all pass: CP 6, CR 15,
RS 24, DS 33, OE 33, ES 24, and PF 39 (PF with Lean at `$HOME/lean/stack_mathlib`).

The WALL suite runs separately (`uv run --no-project --with pytest pytest -q -p no:cacheprovider wall/tests`), and so
does each pool's `items/<CLS>/selftest.sh` (`bash selftest.sh` inside the pool). PF's selftest needs Lean.

Lookups from the script's own location (A5): `eq_check.sh`/`eq_freeze.sh` take M to be the git checkout that holds
them, and `eq_harness.py` takes `DEFAULT_M` to be the nearest ancestor holding `.git`. Either way the default
`EQ_ROOT` (`claude_next_steps/work_carried/equilibrium`) and `EQ_RAW` (`.claude-work/equilibrium/runs`) land in
git-ignored places of the checkout. The WALL is `$EQ_WALL_DIR`, else `<repo>/lib/eq-wall`, else the staging `wall/`.
`<repo>` is three levels up from `harness/` (only in this layout and the frozen copy's), then the git top level of
the checkout holding the harness (A9; depth first, so a `.git` planted inside the tree never outranks `<repo>/lib`).

Isolation backend `container`: Apple `container` 1.5.0 through the repo's [`lib/eq-container`](../../lib/eq-container/)
(images, `probe.sh`, `lib.sh`, `eqc_json.py`). The harness finds it through `$EQ_CONTAINER_DIR`. Failing that, it
takes the repo layout, `<repo>/lib/eq-container` (`../../../lib/eq-container` from
`dot-config/dot-equilibrium/harness`, then the git top level), and only then a `lib/eq-container` beside the harness (the old staging
layout; A9 put the repo's copy first). The tests use the same order (`harness/tests/conftest.py` `container_dir()`). The tests drive a fake `container` CLI
(`harness/tests/fake_container`). Building the real images and running `isolation-probe` is the user's step
(`harness/README.md`, Commands).

## Paid steps (the user's)

- The A4 probe (one `claude -p` call, cap $0.25): [`../../hand_off/A4_FOLD.md`](../../hand_off/A4_FOLD.md). It still names
  EQ-T's path in `P=`. Point `P` at a git-ignored directory, never into the tracked tree.
- The freeze and the stages: `harness/README.md` and `COMPARE_eq.md` §5 (`eq_freeze.sh`, `run --spend-ok`). Without
  `--spend-ok` the harness refuses the real `claude`.

## Differences from EQ-T

`diff -rq` (EQ-T against `equilibrium/`, caches excluded, 2026-10-06) lists 247 entries:

- **233 files changed by the path relativisation only** (A5). For each of them, EQ-T's bytes equal the "old" digest in
  `PATH_RELATIVISATION.json`. `tests/test_equilibrium_paths.py` proves that reversing the recorded substitutions gives
  those bytes back.
- **3 more files in that record whose "old" version already carried a non-path edit**:
  - `COMPARE_eq.md`: amendment A5 appended;
  - `harness/eq_harness.py`: the `lib/eq-container` and `lib/eq-wall` lookups;
  - `harness/eq_freeze.sh`: the `--collect` destination check from the security review.
- **2 re-derived pins:** `items/PF/pool.sha256` and `items/RS/pool.sha256`.
- **4 more non-path edits:**
  - `harness/tests/conftest.py` and `harness/tests/mutations.py`: the repo-layout `lib/eq-container` lookup;
  - `harness/README.md`: the frozen WALL policy is `../lib/eq-wall/policy.default.toml`;
  - `harness/tests/test_shell.py`: the `--collect` refusal test.
- **New:** this README, `PATH_RELATIVISATION.md` and `.json`, and `harness/tests/test_repo_layout.py`.
- **After that count (2026-10-06, branch `eq-distroless`), two more non-path edits:** `harness/tests/fake_container` is
  re-synced byte-identical with the repo's `tests/fake-container/container` (`test_argv_agrees_with_lib_sh` compares
  them), which gained `EQ_FAKE_CONTAINER_FAIL_TARGETS`/`_FAIL_RC` (a build whose `--target` is listed fails) and
  `EQ_FAKE_CONTAINER_REPORT`/`_REPORT_ERR` (a `bash-report` build prints them); `harness/tests/conftest.py` clears the
  four new knobs. Neither file is in `PATH_RELATIVISATION.json`, so the A5 record is unchanged. EQ-T's own copy of
  the fake CLI (outside this repository) is now one version behind.
- **Not copied:** `isolation/build.log`.

Kept as written: `/home/<user>` in `isolation/probe_inner.sh` and `isolation/repo-stage/lib/eq-docker/probe_inner.sh`.
It is a negative probe target, a Linux path that must not exist inside the container.
