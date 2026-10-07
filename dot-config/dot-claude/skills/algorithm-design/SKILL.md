---
name: algorithm-design
description: Use for non-trivial algorithms and data structures — techniques, solvers, proofs, stress tests.
---
# Algorithm design

## Scope
- Covers: turning a problem into a formal model, choosing and proving an algorithm, bounding its cost, implementing it without numeric or structural bugs, and testing it against a reference.
- Not here: tuning a fixed algorithm's constant factors (`cpu-performance`), GPU kernels (`gpu-kernel-dev`), machine-checked proofs and model checking (`formal-methods`), fuzzing (`test-fuzzing`), property-based test design (`test-property-based`), MIP/CP/LP models with solvers (`opt-modeling`).

## 1. Model before choosing
1. **Formal statement.** Input types and ranges, output, objective. Decision, optimization, counting or enumeration? Exact or approximate? Offline (all queries known) or online? Static or with interleaved updates? Worst-case or expected-case guarantee?
2. **Constraints.** n, m, value range C (drives overflow and pseudo-polynomial options), number of queries q, time and memory limits, streaming (one pass, sublinear memory), determinism, parallel hardware.
3. **Budget.** Convert limits into an operation count (table below). Compiled code does roughly 1e8–1e9 simple operations/s; CPython roughly 1e7 bytecode-level operations/s, so vectorize (NumPy) or move the hot core to a compiled language. Memory: 1e8 eight-byte values = 800 MB.
4. **Small cases.** Brute-force n ≤ 8 and look at the answers: monotonicity, convexity, periodicity, a known integer sequence (OEIS). This often reveals the structure (and later becomes the test reference).
5. **Recognize or reduce.** Is it a known problem in disguise (shortest path in a state graph, matching, flow, 2-SAT, LIS, interval scheduling, knapsack)? Check hardness early: if it is NP-hard, decide between exact-with-solver, a parameterized algorithm, approximation or heuristics (§2.9–2.10).

| n (≈1 s, compiled) | Feasible complexity | Typical techniques |
|---|---|---|
| ≤ 10–11 | O(n!·n) | permutations, exhaustive search |
| ≤ 20–25 | O(2^n·n); ≤ 40 with meet-in-the-middle | bitmask DP, subset enumeration |
| ≤ 500 | O(n^3) | Floyd–Warshall, interval DP |
| ≤ 5·10^3 | O(n^2) | pairwise DP, all-pairs checks |
| ≤ 10^6 | O(n log n) | sorting, heaps, segment/Fenwick trees |
| ≤ 10^8 | O(n), tiny constant | scans, two pointers, counting |
| larger or streaming | O(1)/O(log n) per item | sketches, sampling |

## 2. Technique catalog (cue → technique → pitfalls)

Read `references/techniques.md` when picking or checking a technique — greedy, DP and its optimizations, divide and conquer/FFT, graphs (paths, MST, SCC/2-SAT, matching, flows, DSU), range data structures, strings, geometry, randomized algorithms and hashing, approximation and heuristics.

### 2.10 Exact search with solvers
Read `references/solvers.md` when a problem may go to an exact solver (SAT/SMT/MIP/CP).

## 3. Correctness arguments
- Loop invariant: holds initially, is preserved by each iteration, and at exit implies the postcondition; termination by a variant (well-founded measure that strictly decreases).
- Greedy: exchange argument (transform an optimal solution into the greedy one without loss) or stays-ahead induction; matroid structure.
- DP: the state is sufficient (future depends only on it); the recurrence covers every case — for counting, disjointly and exhaustively; base cases; evaluation order respects dependencies.
- Graphs: cut property (MST); Dijkstra's invariant (settled distances exact — breaks with negative edges); augmenting-path theorem (flow, matching); duality certificates (min cut, LP dual, König cover).
- Amortization: aggregate, accounting, or potential Φ ≥ 0 with Φ₀ = 0 and amortized cost = actual + ΔΦ (dynamic arrays, union-find, monotone stacks, splay trees).
- Randomized: linearity of expectation with indicators; Markov/Chebyshev/Chernoff for high-probability bounds.
- Prefer certifying algorithms: output a witness (path, cut, dual, matching + cover) and verify it in O(output). Bounded invariant claims can be checked by SMT (`formal-methods` `references/smt-z3.md`).

## 4. Complexity beyond big-O, and when to stop
- State time and memory in all parameters (n, m, q, alphabet σ, value range C) with realistic constants.
- Memory access dominates: a DRAM miss costs on the order of 100 ns vs about 1 ns for an L1 hit. Prefer flat arrays and CSR adjacency (offsets + targets) to pointer-linked nodes, struct-of-arrays for scans, B-tree fanout over binary trees, sort + two pointers over hashing for batch joins.
- Worst-case vs amortized matters for latency (rehash and reallocation spikes).
- Lower bounds: comparison sorting and element distinctness Ω(n log n) (comparison / algebraic decision-tree models — hashing and integer tricks escape them); NP-hardness by reduction from 3-SAT, Partition (weakly NP-hard — pseudo-polynomial DP exists), 3-Partition (strongly NP-hard), Hamiltonian cycle, clique, coloring; fine-grained conjectures: 3SUM (~n^2), APSP (~n^3), SETH/OV (edit distance and LCS not in n^{2−ε}). A design that beats one of these means the model or the problem statement is wrong: recheck before celebrating.

## 5. Implementation hygiene
- **Overflow.** Bound every intermediate (sums ≤ n·max, products, prefix sums of products). Rust release builds wrap silently (plain `cargo test` checks overflow; `--release` runs need `overflow-checks = true` in `[profile.release]`; or use `checked_*`/`wrapping_*` deliberately). Signed overflow is UB in C/C++ (`__builtin_add_overflow`, `-fsanitize=undefined`). NumPy fixed-width integers wrap silently — choose the dtype. JavaScript numbers are exact only to 2^53. Modular arithmetic: reduce after each product; 64×64-bit products need 128-bit intermediates. "Infinity" constants must survive an addition.
- **Recursion depth.** Use an explicit stack for DFS on deep graphs (a path of 1e6 vertices). Python (measured on 3.11–3.14): plain Python recursion is limited only by `sys.setrecursionlimit`, but recursion through C-implemented wrappers such as `functools.cache`/`lru_cache` consumes the C stack — 3.11 can segfault, 3.12–3.13 raise RecursionError at a fixed C limit whatever `setrecursionlimit` says, 3.14 checks the real stack and succeeds inside a thread started after `threading.stack_size(...)`. Portable fix: bottom-up DP, an explicit stack, or a dict memo inside plain recursion.
- **Floating point.** No `==`; use relative + absolute tolerances (`math.isclose(a, b, rel_tol=..., abs_tol=...)`); compare squared distances in integers; sum with `math.fsum`, pairwise or Kahan summation; NaN breaks comparison sorts; binary search on reals with a fixed iteration count, not `while hi - lo > eps`; use exact arithmetic (`fractions.Fraction`, scaled integers) where branches depend on results.
- **Invalidation and aliasing.** Mutating a container while iterating (Python dict/set errors, C++ reallocation invalidating iterators and references); stale heap entries under lazy deletion need a validity check on pop.
- **Boundaries.** Half-open intervals [lo, hi) throughout; binary search on a predicate with the invariant pred(lo) = false, pred(hi) = true.
- **Determinism.** Stable sorts when ties matter; Python sets of strings (hash randomization) and Rust `HashMap` iterate in run-dependent order — sort before output.
- **I/O.** For 1e6+ numbers use bulk reads (`sys.stdin.buffer.read().split()`, buffered readers).

## 6. Testing
Read `references/testing.md` when writing tests for an algorithm (oracles, generators, stress tests).

## Verify
- [ ] Formal statement and budget written down; chosen complexity fits the budget with margin.
- [ ] Correctness argument written (invariant, exchange, potential or certificate), not just "tests pass".
- [ ] Differential test vs the reference passed on ≥ 1000 random cases plus the edge and adversarial generators.
- [ ] Overflow bounds and recursion depth checked at maximum input; no float equality in decisions.
- [ ] Measured scaling matches the derived bound at realistic sizes; solver results include status and gap.

## Report
```
PROBLEM: formal statement, constraints, budget
ALGORITHM: idea in 3–5 lines; data structures
CORRECTNESS: invariant / exchange / potential argument (or certificate check)
COMPLEXITY: time, memory (all parameters); lower bound or hardness note
TESTS: reference used, #random cases, generators, regressions added
BENCHMARK: | n | time | memory | (slope of log T vs log n)
LIMITS: assumptions, input ranges, known worst cases, solver gap
FILES: paths
```
