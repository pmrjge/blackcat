# Algorithm design: testing

Read when writing tests for an algorithm (oracles, generators, stress tests) (moved from `algorithm-design` SKILL.md).

## 6. Testing
1. Reference: the most obviously correct implementation (exhaustive search, direct simulation, O(n^3) DP), sharing no code with the fast one.
2. Differential property test on random small inputs; compare outputs or check a certificate.
3. Generators: exhaustive tiny cases (all arrays over {−2..2} up to length 6), skewed distributions (all equal, many duplicates, sorted, reversed), extreme values (0, 1, min, max, negative, empty), structured graphs (path, star, complete, disconnected, self-loops, multi-edges, zero-weight cycles).
4. Adversarial generators: inputs that trigger worst cases — sorted input for naive pivots, anti-hash keys, long chains for recursion depth, maximum n with maximum values for overflow, many equal keys.
5. No reference available: metamorphic relations (permutation invariance, scaling, monotonicity, idempotence, round trips) and certificate checks.
6. Complexity curve: time at n, 2n, 4n, …; the slope of log T vs log n should match the derived bound (≈1 linear, slightly above 1 for n log n, 2 quadratic); record peak memory. Benchmark protocol: `cpu-performance`.

```python
from hypothesis import given, settings, example, strategies as st

def max_subarray(xs):                    # fast: Kadane, empty subarray allowed
    best = cur = 0
    for x in xs:
        cur = max(cur + x, 0); best = max(best, cur)
    return best

def max_subarray_ref(xs):                # obviously correct: O(n^3)
    return max([0] + [sum(xs[i:j]) for i in range(len(xs)) for j in range(i + 1, len(xs) + 1)])

@settings(max_examples=2000, deadline=None)
@given(st.lists(st.integers(-10**6, 10**6), max_size=40))
@example([]).via("empty input")
def test_matches_reference(xs):
    assert max_subarray(xs) == max_subarray_ref(xs)
```
Rust: `proptest!` with `prop_assert_eq!`; JS/TS: fast-check. Keep every failing case as a named regression test.
