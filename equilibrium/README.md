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
outputs. Absolute paths inside the documents (`/Users/pmrj/...`, `STAGE=`, `DEFAULT_M` in `harness/eq_harness.py`)
record where the work was done. They are left as written; for runs, use `EQ_ROOT`/`EQ_RAW` or `--eq-root`/`--raw-root`.

## Layout

| path | what |
|---|---|
| `PROPOSAL.md`, `COMPARE_eq.md`, `CONTRACT.md` | the design, the pre-registration (wins), and the item-pool/harness contract |
| `MEDIATOR.md`, `ISOLATION.md` | the mediator design (COMPARE_eq §12 A0) and the isolation backend assessment |
| `derive_numbers.py`, `mediator_numbers.py`, `shift_check.py`, `refute_check.py`, `r3_check.py` (+ `*.out`), `seeds.out` | the derivations behind COMPARE_eq §8 and MEDIATOR, with their recorded outputs |
| `harness/` | `eq_harness.py` (uv PEP 723 script: seeds, flags, views, schedule, run, scoring, the `container` isolation backend), `eq_mediator.py`, `eq_analyse.py` and `eq_route2.py`/`.sql` (analysis routes 1 and 2), `eq_check.sh`, `eq_freeze.sh`, `flags.json` (`common_tools: ["Skill"]`, A4), `stub_claude`, `tests/`. Details: `harness/README.md`, `harness/LEDGER_SCHEMA.md` |
| `items/<CLS>/` | the pools PF, CP, CR, RS, ES, DS, OE: `manifest.jsonl`, `schema.json`, `oracle.py` + `oracle/`, `fixtures/`, `selftest.sh`, generator, and `pool.sha256` over all of them. `items/graders/` holds the grader briefs |
| `wall/` | the WALL broker, client and policy as staged for the harness (`harness/tests/test_wall_integration.py` reads it). The installed copy is [`../lib/eq-wall`](../lib/eq-wall/) (hash-pinned in its `REVIEW`). `policy.default.toml`, `WALL_DESIGN.md` and `INSTALLER_WALL.md` differ from the lib copy, and the lib copy is the one installed |
| `isolation/` | the superseded Docker staging scripts (user decision 2026-10-05; the harness never uses them). The live backend is [`../lib/eq-container`](../lib/eq-container/) |
| `analysis-r1/`, `analysis-r2/` | the zero-spend fixtures of analysis routes 1 and 2 |
| `proof-check/` | the Lean check of a PF statement |

Not tracked (`.gitignore`): `runs/` at this level (a stage's ledger, transcripts and raw JSON when `EQ_ROOT` points
here), `.eq_deps/` work files, logs (`isolation/build.log` stayed in EQ-T), caches. Tracked on purpose:
`items/RS/fixtures/corpus/runs/` (a cleaned-up fixture in `RS/pool.sha256`, not run output) and
`items/PF/oracle/build/` (the PF oracle's build records). `items/RS/manifest.jsonl` (2.8 MB) is the only file over
1 MiB. `tests/test_equilibrium_layout.py` pins all of this: the layout, every `pool.sha256`, the size cap, the ignores
and the executable bits.

## Tests (zero spend)

Run the harness suite in its own pytest process: its `tests/conftest.py` collides with the repo's `tests/conftest.py`
in one run. Run it from a scratch copy, so nothing it writes lands in the checkout:

```sh
T=$(mktemp -d) && rsync -a equilibrium/ "$T/equilibrium/" && cd "$T/equilibrium" &&
  EQ_CONTAINER_DIR=<repo>/lib/eq-container \
  uv run --no-project --with pytest --with duckdb --with-requirements harness/eq_harness.py \
  pytest -q -p no:cacheprovider harness/tests
```

Expected on 2026-10-06:
- From the copy with `EQ_CONTAINER_DIR`: 442 passed, 1 skipped (the in-place layout check).
- From the copy without it: 438 passed, 5 skipped (the 4 tests that need `lib/eq-container`, plus that check).
- In place (`cd equilibrium` in a checkout, no `EQ_CONTAINER_DIR`): 443 passed.

The WALL suite runs separately (`uv run --no-project --with pytest pytest -q -p no:cacheprovider wall/tests`), and so
does each pool's `items/<CLS>/selftest.sh`. PF's selftest needs Lean.

Isolation backend `container`: Apple `container` 1.5.0 through the repo's [`lib/eq-container`](../lib/eq-container/)
(images, `probe.sh`, `lib.sh`, `eqc_json.py`). The harness finds it through `$EQ_CONTAINER_DIR`. Failing that, it
looks beside the harness (`../lib/eq-container`, the staging layout) and then at the repo layout
(`../../lib/eq-container`, i.e. `<repo>/lib/eq-container` from `equilibrium/harness`). The tests use the same order
(`harness/tests/conftest.py` `container_dir()`). The tests drive a fake `container` CLI
(`harness/tests/fake_container`). Building the real images and running `isolation-probe` is the user's step
(`harness/README.md`, Commands).

## Paid steps (the user's)

- The A4 probe (one `claude -p` call, cap $0.25): [`../hand_off/A4_FOLD.md`](../hand_off/A4_FOLD.md). It still names
  EQ-T's path in `P=`. Point `P` at a git-ignored directory, never into the tracked tree.
- The freeze and the stages: `harness/README.md` and `COMPARE_eq.md` §5 (`eq_freeze.sh`, `run --spend-ok`). Without
  `--spend-ok` the harness refuses the real `claude`.

## Differences from EQ-T

All files are byte-identical to EQ-T, with these exceptions. The lookup of `lib/eq-container` also searches the repo
layout, in `harness/eq_harness.py` `probe_script_candidates()`, in `harness/tests/conftest.py` `container_dir()` and in
the matching copy in `harness/tests/mutations.py`. `harness/tests/test_repo_layout.py` is new and pins that lookup.
This README is new. `diff -rq` (EQ-T against `equilibrium/`, caches excluded), 2026-10-06:

```
Files EQ-T/harness/eq_harness.py and equilibrium/harness/eq_harness.py differ
Files EQ-T/harness/tests/conftest.py and equilibrium/harness/tests/conftest.py differ
Files EQ-T/harness/tests/mutations.py and equilibrium/harness/tests/mutations.py differ
Only in equilibrium/harness/tests: test_repo_layout.py
Only in EQ-T/isolation: build.log
Only in equilibrium: README.md
```
