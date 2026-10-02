---
name: debug-native
description: Use for crashes, hangs or memory corruption in native code — sanitizers, lldb/gdb, rr.
---
# Debugging native code (C, C++, Rust, extensions)

## Scope
Crashes (SIGSEGV, SIGABRT, panics across FFI), hangs and deadlocks, memory corruption, in C/C++/Rust programs and native Python/Node extensions on macOS and Linux. Language rules: `cpp-engineering`, `rust-engineering`. Finding the commit or the minimal input: `debug-bisect-minimize`. Performance: `perf-profilers`.

## First minutes
1. Reproduce with the exact command, input and environment; record OS, compiler and flags, commit.
2. Get a symbolized stack: build with debug info (`-g`, Rust `debug = true` or `"line-tables-only"`), keep frame pointers; Rust `RUST_BACKTRACE=1` (or `full`).
3. Rebuild with sanitizers before reading code — they usually point at the real bug, not the symptom:
   - AddressSanitizer (`-fsanitize=address -fno-omit-frame-pointer`): out-of-bounds, use-after-free, double free; LeakSanitizer is included on Linux.
   - UndefinedBehaviorSanitizer (`-fsanitize=undefined`): overflow, misaligned access, invalid shifts and casts.
   - ThreadSanitizer (`-fsanitize=thread`, separate build): data races.
   - MemorySanitizer (clang, Linux, fully instrumented build): uninitialized reads.
   - Rust: Miri for unsafe code paths and sanitizers on nightly (`formal-methods` `references/rust-kani-miri.md`).
4. If it doesn't reproduce under sanitizers, look for timing (races), environment (locale, stack size, ulimits) and input differences.

## Debuggers
- macOS: lldb (`lldb -- ./app args`, `run`, `bt all`, `frame variable`, `register read`, `memory read`, `watchpoint set variable x`); `atos` symbolizes addresses from crash reports.
- Linux: gdb (`gdb --args ./app args`, `run`, `bt`, `thread apply all bt`, `info locals`, `watch x`, `catch throw`); lldb works too. `rust-lldb`/`rust-gdb` add Rust pretty-printers.
- Attach to a hung process: `lldb -p <pid>` / `gdb -p <pid>`, then all-thread backtraces — look for threads waiting on each other's locks (deadlock) or a thread spinning.
- Record and replay (Linux, x86-64): rr (`rr record ./app`, `rr replay`, then reverse-continue to the corrupting write with a watchpoint) — the fastest path for heisenbugs it can capture.

## Core dumps and crash reports
- Linux: enable with `ulimit -c unlimited`; with systemd, `coredumpctl list` and `coredumpctl debug <pid>`.
- macOS: crash reports in `~/Library/Logs/DiagnosticReports/`; core files need `ulimit -c unlimited` and a writable `/cores` (check the OS's current policy).
- Keep the exact binary and debug symbols (dSYM on macOS, split DWARF/debuginfo on Linux) for every shipped build; a crash address without matching symbols is nearly useless.

## Native extensions (Python, Node)
- Python: `uv run python -X faulthandler app.py` (or `PYTHONFAULTHANDLER=1`) prints the Python stack on a crash; run under lldb/gdb with the interpreter as the program; a debug build of the extension with ASan may need `LD_PRELOAD`/`DYLD_INSERT_LIBRARIES` of the ASan runtime (platform-specific: unverified).
- Check the GIL/threading contract, reference counting, and buffer lifetimes at the FFI boundary first.

## Verify
- [ ] Root cause stated as a specific invalid operation (file:line, what was read/written, why), not "memory corruption".
- [ ] A regression test reproduces the crash before the fix; sanitizer build clean after it.
- [ ] Fix confirmed under the original conditions (same flags, same input) and under the sanitizer that found it.

## Sources
- Verified 2026-10-02 https://github.com/rr-debugger/rr/releases/latest — rr 5.9.0 (repository moved to rr-debugger/rr).
- Unverified as of 2026-10-02: rr platform limits, macOS core-dump policy, debugger command spellings (stable for many releases; check `help` in the debugger).
