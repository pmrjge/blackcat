---
name: debug-bisect-minimize
description: Use when a bug needs its first bad commit or smallest failing input — pass/fail check scripts, git bisect run, delta debugging, cvise.
---
# Bisecting and minimizing

## Scope
Two searches that shrink a bug before anyone reads code: which change introduced it (bisect), and which smallest input still triggers it (minimize). Git mechanics beyond `bisect`: `git-workflows`. Crash analysis: `debug-native`. Property-test shrinking: `test-property-based`.

## 1. A reliable oracle first
- Write a script that exits 0 when the behaviour is good, 1–124 or 126–127 when bad, and 125 when the revision cannot be tested (build failure) — the `git bisect run` convention.
- Make it deterministic (seeds, fixed inputs, timeouts). For flaky bugs, run the check N times and call "bad" if any run fails; state N.
- Check the oracle on a known-good and a known-bad revision before bisecting.

## 2. Bisect the history
```sh
git bisect start <bad> <good>
git bisect run ./check.sh          # 0 good, 125 skip, other non-zero bad
git bisect log > bisect.log        # keep it for the report
git bisect reset
```
- Narrow the search space: `git bisect start <bad> <good> -- path/` limits to commits touching a path; `--first-parent` follows merges only.
- Build failures in the middle: exit 125 (skip); too many skips → bisect on merge commits first.
- Not only git history: the same binary search works over dependency versions (lockfile states), compiler versions (e.g. a Rust nightly bisector), configuration flags, or data partitions.

## 3. Minimize the input
- Delta debugging: repeatedly remove chunks of the input (halves, then smaller pieces) while the oracle still says "bad".
- Tools: cvise (C-Reduce successor; works on C/C++ and, with care, any text), shrinkray (unverified as of 2026-10-02), fuzzers' minimizers (`cargo fuzz tmin`, `afl-tmin`; `test-fuzzing`), hypothesis shrinking for generated inputs.
- The "interestingness" test must check the specific failure (same error message or crash site), or reduction drifts to a different bug.
- Also minimize the environment: fewer threads, smaller configs, no network, a single file.

## 4. Use the result
- The first-bad commit plus the minimal input usually explain the bug; read that diff first.
- Turn the minimal input into the regression test.

## Verify
- [ ] Oracle validated on known-good and known-bad points; flakiness handled and stated.
- [ ] `git bisect log` and the first-bad commit reported; the result reproduced by checking out first-bad and its parent.
- [ ] Minimal input still fails the same way; committed as a regression test.

## Sources
- Verified 2026-10-02 https://github.com/marxin/cvise/releases/latest — cvise 2.12.0.
- Unverified as of 2026-10-02: `git bisect` exit-code convention and options above (long-standing git behaviour; check `git help bisect`), shrinkray.
