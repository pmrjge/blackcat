---
name: test-fuzzing
description: Use for fuzzing parsers and untrusted-input code — cargo-fuzz, atheris, AFL++, Go fuzzing, corpora, crashes.
---
# Fuzzing
Hub: `test-strategy`. Fuzzing is evidence on executed inputs and paths only: report coverage and budget, not "safe" (`formal-methods` §7).

Targets: parsers, decoders, deserializers, protocol state machines, anything reading untrusted bytes; differential fuzzing of two implementations.
- cargo-fuzz (libFuzzer; nightly; x86-64/aarch64 Unix): `cargo install cargo-fuzz`, `cargo fuzz init`, `cargo fuzz add parse`, `cargo +nightly fuzz run parse -- -max_total_time=600 -max_len=4096`. Crashes land in `fuzz/artifacts/parse/`; reproduce with `cargo +nightly fuzz run parse <artifact>`; `cargo fuzz tmin`, `cmin`, `coverage`. AddressSanitizer is on by default. Structured inputs: `libfuzzer-sys = { version = "0.4", features = ["arbitrary-derive"] }` and `#[derive(Arbitrary, Debug)]` types as the closure argument.
```rust
#![no_main]
use libfuzzer_sys::fuzz_target;
fuzz_target!(|data: &[u8]| {
    if let Ok(s) = std::str::from_utf8(data) { let _ = mycrate::parse(s); }   // must not panic, hang or UB
});
```
- atheris (Python 3.11–3.14 in current source; older Pythons stay on older PyPI releases; Linux wheels (macOS wheel availability unverified); on macOS it needs a non-Apple LLVM with libFuzzer):
```python
import sys, atheris
with atheris.instrument_imports():
    import mylib                                   # pure-Python code gets coverage feedback
def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    text = fdp.ConsumeUnicodeNoSurrogates(fdp.ConsumeIntInRange(0, 4096))
    try:
        value = mylib.parse(text)
    except mylib.ParseError:
        return                                     # the documented failure mode
    assert mylib.parse(mylib.render(value)) == value
atheris.Setup(sys.argv, TestOneInput); atheris.Fuzz()
```
Run `uv run python fuzz_parse.py corpus/ -atheris_runs=1000000 -max_len=4096` (libFuzzer flags pass through). C-implemented modules give no coverage feedback unless built with instrumentation. Existing hypothesis tests can also run as long fuzz campaigns under HypoFuzz.
- AFL++ (C/C++ binaries): build with `CC=afl-clang-fast CXX=afl-clang-fast++` (or `afl-clang-lto`), `AFL_USE_ASAN=1`; run `afl-fuzz -i seeds -o out -- ./target @@`; a CMPLOG build (`AFL_LLVM_CMPLOG=1`, then `-c ./target.cmplog`) cracks magic values; `afl-cmin`/`afl-tmin` minimize; parallelize with one `-M` and several `-S` instances; persistent mode for speed. libFuzzer harnesses (`LLVMFuzzerTestOneInput`) build with `clang -fsanitize=fuzzer,address`.
- Go (1.18+): `func FuzzParse(f *testing.F)` with `f.Add(seed)` and `f.Fuzz(func(t *testing.T, b []byte) { ... })`; run `go test -fuzz=FuzzParse -fuzztime=60s` (a duration or `1000x`); seed corpus and crashers in `testdata/fuzz/FuzzParse/` (commit them), generated corpus in `$GOCACHE/fuzz`.
- Corpus and hygiene: seed with real samples and edge cases, add a dictionary (`-dict=`) for tokens, minimize periodically, keep the corpus as an artifact, turn every crash into a regression test. Sanitizers: ASan (memory), UBSan (UB), MSan (uninitialized; needs a fully instrumented build), TSan (races; separate build). Track executions/s and coverage growth; a plateau means the harness or corpus needs work, not that the code is safe.

## Verify
- [ ] The harness reaches the target: a planted `panic!`/`abort()` behind a magic prefix is found within the budget.
- [ ] Budget, executions/s, corpus size and coverage reported with the tool version.
- [ ] Every crash minimized, fixed and committed as a regression test; the fuzzer re-run on the fix.

## Sources
- Verified 2026-10-02 https://github.com/google/atheris — current source supports Python 3.11–3.14 (atheris 3.1.0 on PyPI).
- Verified 2026-10-02 https://rust-fuzz.github.io/book/cargo-fuzz/setup.html — cargo-fuzz requires nightly.
- Verified 2026-10-02 https://go.dev/doc/security/fuzz/ — `go test -fuzz`, `-fuzztime`, `testdata/fuzz/<Name>/`, `$GOCACHE/fuzz`, Go 1.18+.
- Unverified as of 2026-10-02: AFL++ flag names (`afl-clang-lto`, `AFL_LLVM_CMPLOG`); latest AFL++ release shown as v5.03c.
