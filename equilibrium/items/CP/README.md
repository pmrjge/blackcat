# CP pool (code patch), agent-equilibrium experiment

Contract: ../../CONTRACT.md. Score (COMPARE_eq 2): 1 iff the hidden tests pass on the patched fixture copy.

## Made how
- 26 frozen pure-stdlib base modules (`oracle/bases/`, 40-90 lines, docstrings state the behaviour) with a test file
  each (`oracle/tests/`): the part above `# ---- HIDDEN ----` is the public test file, the whole file is the hidden suite.
- `gen_cp.py` (frozen seed `eq|CP|pool|v1`, operators in `mutlib.py`) applies ONE token-level mutation per item
  (boundary, off-by-one constant, arithmetic/boolean operator, inverted test, wrong exception, mutable default...).
  A mutant is kept only if public tests fail AND hidden tests fail (no timeouts); selection is round robin over
  shuffled modules (max 9 per module), then shuffled. Segment order shuffled once with numpy default_rng(3725927731).
- Fixture = `<module>.py` + `tests/` (public tests). Prompt is one constant for all items (cannot encode the bug).
- Answer: `answer` = one-sentence fix description; the patched working directory is what is scored
  (`uv run oracle.py --item CP-0001 --answer a.json --workdir <patched copy>`; hidden tests come from `oracle/hidden/`).

## Counts
200 non-dev (CP-0001..0200) + 3 dev (CP-DEV1..3), 26 modules, 4-9 items per module.

## Checks (run them)
- `./selftest.sh`: dev items, reference fix scores 1.0, seeded fixture 0.0 (6/6 PASS).
- `uv run prove_pool.py [--regen]`: every item fails (public and hidden) on its seed and passes on its reference,
  the seed differs from the reference in exactly the recorded token, regeneration is byte-identical. Report: `proof_report.txt`.
- `pool.sha256`: `shasum -a 256 -c pool.sha256` from this folder; rewrite with `uv run gen_cp.py --hash-only`.

## Known weaknesses
- Bugs are synthetic single-token mutations (mostly constants and operator flips), not mined from real history.
- Every item has a failing PUBLIC test, so verify-then-select (public tests) is informative here; items whose bug the public
  tests miss are not in this pool.
- Only 26 distinct programs: items of one module share code (4-9 each); not independent in program, independent in bug.
- Hidden tests encode the documented behaviour; an unusual but valid fix that changes documented-adjacent behaviour could fail.
- The oracle does not stop an arm from special-casing the tests (hidden tests are not visible to it, so unlikely).
- Public check runs through `uv run --no-project python`; needs uv and a local Python, no network.

## Verdict channel (security finding F1)
`oracle.py` reads the harness nonce from the first stdin line before anything else (missing, empty or multi-word: exit 4,
nothing on stdout), sets PR_SET_DUMPABLE=0 on Linux only (macOS host / off mode run without prctl), runs the hidden
tests with stdin=DEVNULL in their own session (group killed afterwards), and prints `EQV1 <nonce> <json>` as its very last
act; nothing else it prints starts with `EQV1 `. The harness must accept exactly one such line carrying its nonce.
Proofs: `items/test_f1_verdict_channel.py`. Residuals: the hidden tests run in-process with the answer's module, so
answer code can still influence the child's own output and exit status (for example print `Ran N tests` and exit 0 at
import, scoring 1) and can read the hidden tests copied next to it; only a second, separate container for the
hidden run closes this. Not fixed here (would change the frozen judge).
