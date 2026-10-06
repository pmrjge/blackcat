# CR pool (code review), agent-equilibrium experiment

Contract: ../../CONTRACT.md. Score (COMPARE_eq 2): recall of seeded bugs - 0.5 x false findings / #seeded; a finding
matches a bug if same file, line within +-3 and the blinded grader does not mark the claim false.

## Made how
- Same 26 frozen base modules and tests as CP (copied into `oracle/bases`, `oracle/tests`). A fixture is TWO modules
  (random pair, every pair used at most once) plus their public tests; 1-3 seeded defects spread over the two files
  (68 items with 1, 101 with 2, 34 with 3 defects).
- `gen_cr.py` (frozen seed `eq|CR|pool|v1`, `mutlib.py` operators): a defect is a single-token mutation that PASSES the
  module's public tests (not trivially revealed), FAILS its hidden tests alone (a real behaviour defect), never times out;
  defects in one file are > 6 lines apart; the combined fixture is re-verified. Lines never move, so the manifest line is
  the line of the mutated statement. Segments (2 sources + 2 test files) shuffled once with numpy default_rng(3725927731).
- Manifest extras (k-cover): `segment_roles` (parallel to `segments`: "source" | "test") and `pinned_segments` (indexes of
  the two source modules). A k-cover/partial view MUST include every pinned segment (tests may be split freely), so each
  member sees both source modules. `segments` order is unchanged.
- Prompt is one constant for all items; arms return `answer` = [{file, line, claim}], nothing is edited.
- `oracle/items.json` holds the bug manifest (file, line, kind, function, claim, original and seeded line text).

## Counts: 200 non-dev (CR-0001..0200) + 3 dev (CR-DEV1..3)

## Scoring modes of oracle.py
`--grader-input out.json` writes the blinded grader records exactly as graders/grader_brief_CR.md (`rid` f<i>, `type` match|unmatched, `finding`, `seeded_bug`{file,line,description}, `code_excerpt` line +-6); `--grade grader.json` finalises from the brief's output list
[{"rid":"f0","verdict":"true|false|unclear","note":""}] (old {"verdicts":[{"id":..}]} also accepted); neither flag gives a PROVISIONAL score (location match only,
every unmatched finding counts as false, so it is a lower bound). Duplicate findings count once.


## Checks (run them)
- `./selftest.sh`: dev items, reference findings score 1.0 (provisional and graded), wrong lines < 0, empty 0.0 (15/15 PASS).
- `uv run prove_pool.py [--regen]`: per item public passes / hidden fails on the seed, every bug alone fails hidden and
  passes public, manifest lines equal the differing lines, reference findings score 1.0, +3 line shift matches and +4 does
  not, wrong file does not match, regeneration byte-identical. Report: `proof_report.txt`.
- `pool.sha256`: `shasum -a 256 -c pool.sha256`; rewrite with `uv run gen_cr.py --hash-only`.

## Known weaknesses
- Defects are operator mutations (135 of 372 seeded bugs are off-by-one constants, then arithmetic, boundary, exception type); the kinds are
  skewed to constants and simple operator flips, which are easier to spot than semantic defects.
- The grader step is not exercised here (selftest/proof use synthetic all-true / all-false verdicts); a real unseeded
  defect an arm reports would be adjudicated by the grader, base modules were not audited for latent real bugs.
- 26 base modules only (~15 items each); the +-3 window can credit a finding aimed at a neighbouring line.

## Verdict channel (security finding F1)
In every mode `oracle.py` reads the harness nonce from the first stdin line before anything else (missing, empty or
multi-word: exit 4, nothing on stdout), sets PR_SET_DUMPABLE=0 on Linux only, and prints `EQV1 <nonce> <json>` as its very
last act (the JSON is the old one-line verdict, sorted keys). CR runs no answer code and starts no children, so no
residual of the CP/PF kind applies; the grader remains a separate agent step whose output is data. Proofs:
`items/test_f1_verdict_channel.py`. `selftest.sh` and `prove_pool.py` send a fixed nonce and read only the `EQV1` line.
