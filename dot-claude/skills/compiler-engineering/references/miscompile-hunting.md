# Miscompile hunting

1. **Reproduce deterministically**: a single input program whose output differs between optimization levels, backends or the reference interpreter. Record compiler commit, flags, target.
2. **Rule out UB in the input**: if the source language has UB (C-like), check the program with sanitizers (UBSan, ASan) or the interpreter's UB checks — a "miscompile" of a UB program is not a compiler bug.
3. **Minimize the program**: C-Reduce/cvise for C-like sources, your language's reducer (or a generic one like `shrinkray`/`halfempty`), `llvm-reduce` once you have failing LLVM IR; keep an interestingness test that checks the output difference, not just "it compiles".
4. **Find the guilty pass**:
   - your IR: bisect the pass pipeline (disable passes one by one or binary search the pipeline list); dump IR before/after with the verifier on;
   - LLVM: `opt -passes=… -opt-bisect-limit=N` to bisect the number of transformations; `-print-changed` to see the change; `-print-before=<pass>`/`-print-after=<pass>`.
5. **Check the transformation**: for LLVM IR rewrites use Alive2 (`alive-tv before.ll after.ll`) — it reports whether `after` refines `before`; for your IR, write the pre/post as a test and reason with the pass's invariants.
6. **Look for the usual suspects**: missing alias information or wrong `noalias`; `nsw`/`nuw`/`inbounds` flags emitted without language guarantees; wrong dominance after CFG edits; stale analyses not invalidated; integer width/sign extension mistakes; floating-point flags (`fast`, `reassoc`) applied too broadly; calling convention mismatches.
7. **Fix and pin**: add the minimized program as an end-to-end regression test and the IR snippet as a lit/FileCheck or golden test of the pass.
8. If it is an upstream LLVM bug: confirm on the latest release, file with the reduced `.ll` and `opt` command line (the user files; publishing is their step).
