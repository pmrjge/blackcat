---
name: test-property-based
description: Use for property-based and stateful model tests — hypothesis, proptest, fast-check, generators, shrinking.
---
# Property-based and stateful testing
Hub: `test-strategy`. What the evidence guarantees (evidence on executed inputs only, not proof): `formal-methods` §7.

Properties that pay off: round trip (`decode(encode(x)) == x`), differential against a reference or older version, invariants after every operation, metamorphic relations, idempotence, algebraic laws, "only documented errors".
```python
from hypothesis import settings, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule, precondition, invariant

class QueueVsModel(RuleBasedStateMachine):
    def __init__(self):
        super().__init__(); self.sut, self.model = MyQueue(), []      # system under test + model
    @rule(x=st.integers())
    def push(self, x):
        self.sut.push(x); self.model.append(x)
    @precondition(lambda self: self.model)
    @rule()
    def pop(self):
        assert self.sut.pop() == self.model.pop(0)
    @invariant()
    def same_size(self):
        assert len(self.sut) == len(self.model)

TestQueue = QueueVsModel.TestCase
TestQueue.settings = settings(max_examples=300, stateful_step_count=50, deadline=None)
```
- hypothesis: `@settings(max_examples=..., deadline=None)` for slow code; `@example(...)` pins regressions; `st.data()` for dependent draws; avoid heavy `assume`/`.filter` (health-check failures) — build valid values constructively so shrinking works; failing examples replay from `.hypothesis/`. A mutation check (break the implementation on purpose, or a mutation tool, `test-strategy` `references/mutation.md`) confirms the machine has teeth. Long runs as a fuzzer: HypoFuzz drives existing hypothesis tests (`test-fuzzing`).
- proptest (Rust): `proptest! { #[test] fn prop(xs in prop::collection::vec(any::<i64>(), 0..64)) { prop_assert_eq!(fast(&xs), reference(&xs)); } }`; commit `proptest-regressions/`; stateful testing with `proptest-state-machine`.
- fast-check (JS/TS): `fc.assert(fc.property(fc.array(fc.integer()), (xs) => ...))`; model-based testing with `fc.commands([...])` + `fc.modelRun(setup, cmds)`.
- Numerical properties (solve then multiply back, scaling invariances, matrices with a controlled condition number): `numerical-methods` §9.

## Verify
- [ ] Each property is written in words next to the test (what must hold, for which inputs).
- [ ] A seeded bug makes the property fail and shrink to a small counterexample.
- [ ] Regression stores committed (`.hypothesis/` examples pinned with `@example`, `proptest-regressions/`).
- [ ] Generators cover edge cases explicitly (empty, one element, max size, duplicates, unicode, negative zero/NaN where relevant).

## Sources
- Verified 2026-10-02 https://pypi.org/pypi/hypothesis/json — hypothesis 6.168.3 is current; https://registry.npmjs.org/fast-check/latest — fast-check 4.10.2.
- Verified 2026-10-02 https://hypofuzz.com/docs/ — HypoFuzz is a fuzzing backend and dashboard for hypothesis tests.
- Unverified as of 2026-10-02: the exact `proptest-state-machine`, `fc.commands`/`fc.modelRun` APIs (re-check against the crate/package docs).
