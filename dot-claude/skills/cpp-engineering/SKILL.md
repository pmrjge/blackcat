---
name: cpp-engineering
description: Use for C or C++ — UB traps, RAII and lifetimes, concurrency, sanitizers, clang-tidy, ABI.
---
# C and C++ engineering

## Scope
The languages and their tooling. Build systems (CMake presets, Ninja, vcpkg/Conan, ccache, CTest wiring, sanitizer build types) → `cmake-ninja-builds`; CUDA kernels → `gpu-kernel-dev`; performance measurement → `cpu-performance`; formal checks → `formal-methods`; fuzzing → `test-fuzzing`; property tests → `test-property-based`; native crashes and debuggers → `debug-native`; untrusted input → `secure-coding`; ROS 2 C++ → `robotics-engineering`.

## Compilers and standards (checked 2026-09-29)
- Toolchains: GCC 16 (default `-std=gnu++20` since 16; C++26 reflection with `-std=c++26 -freflection`, contracts P2900, `std::inplace_vector`, erroneous behaviour for uninitialized reads P2795), upstream LLVM/Clang 23.1, **Apple Clang 21** on this Mac (Xcode, macOS SDK 27) — Apple Clang lags upstream and has neither contracts nor reflection.
- Before using a feature, check it on the actual compiler: cppreference compiler-support tables, `clang.llvm.org/cxx_status.html`, `gcc.gnu.org/projects/cxx-status.html`, and feature-test macros in code:
  ```cpp
  #include <version>
  #if defined(__cpp_lib_expected) && __cpp_lib_expected >= 202211L   // std::expected
  #endif
  ```
  Quick probe: `echo '#include <version>\n__cpp_lib_expected __cpp_lib_print __cpp_pack_indexing' | clang++ -std=c++26 -x c++ -E - | tail -1` (unexpanded name = unsupported).
- Default for new code: C++20 (or C++23 where all target compilers support the features used); set `CMAKE_CXX_STANDARD` + `CMAKE_CXX_EXTENSIONS OFF`. C: C17 baseline, C23 when the compilers allow (`-std=c23`).
- Warnings: `-Wall -Wextra -Wpedantic -Wshadow -Wconversion -Wsign-conversion -Wnon-virtual-dtor -Wold-style-cast -Woverloaded-virtual -Wnull-dereference -Wimplicit-fallthrough`; `-Werror` in CI only.

## Ownership and lifetimes
- Rule of zero: members that manage themselves (`std::vector`, `std::unique_ptr`, `std::string`); write the five special members only for a resource-owning type, and then all of them.
- `std::unique_ptr` by default; `std::shared_ptr` only for genuinely shared ownership (cycles → `weak_ptr`); raw pointers and references are non-owning observers.
- Dangling traps: `std::string_view`/`std::span` outliving their buffer (returning a view of a local or a temporary `std::string`), iterators and references invalidated by `push_back`/`insert`/rehash, lambdas capturing `this` or references into async work, range-for over a temporary's member (`for (auto& x : make().items())` dangles before C++23 P2718, and still on compilers that lack it).
- `const` and `noexcept` correctness; move-only types for handles; `[[nodiscard]]` on functions whose result must be checked.

## Undefined behaviour catalogue → detector
| UB | Detector |
|---|---|
| Out-of-bounds, use-after-free/return/scope, double free, leaks | ASan (`-fsanitize=address`; LSan on Linux) |
| Signed overflow, bad shifts, misaligned access, invalid enum/bool, null deref | UBSan (`-fsanitize=undefined -fno-sanitize-recover=all`) |
| Data races, lock-order inversions | TSan (`-fsanitize=thread`; not together with ASan) |
| Uninitialized reads | MSan (Clang, **Linux only** — `-fsanitize=memory` is unsupported on macOS arm64); C++26 makes them erroneous behaviour; `-ftrivial-auto-var-init=pattern` as mitigation |
| Strict aliasing violations | `-fno-strict-aliasing` masks; fix with `std::memcpy`/`std::bit_cast` |
| Hardened library checks | libc++ `-D_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_FAST`, libstdc++ `-D_GLIBCXX_ASSERTIONS` |

Run the test suite under ASan+UBSan and separately under TSan in CI. Compile sanitizer builds with `-O1 -g -fno-omit-frame-pointer`. On macOS, ASan/UBSan/TSan work with Apple Clang (checked); Valgrind does not run on Apple Silicon — use Instruments/leaks or Linux.

## Errors
Exceptions for exceptional failures in application code; `std::expected<T, E>` (C++23) or error codes at API boundaries, in hot paths, or with `-fno-exceptions` codebases; never both styles for the same failure. Destructors never throw. `std::optional` for "no value", not for errors.

## Concurrency
`std::jthread` + `std::stop_token` over raw `std::thread`; `std::scoped_lock` for multiple mutexes; condition variables always with a predicate; atomics default to `seq_cst` — use `acquire`/`release` only with a written argument, `relaxed` only for counters; no data races on non-atomics (TSan). Thread pools/executors from a library (e.g. Taskflow, oneTBB) rather than hand-rolled; `std::execution` (P2300) availability depends on the standard library — check before use.

## Tooling
- `compile_commands.json` (`CMAKE_EXPORT_COMPILE_COMMANDS=ON`) for clangd and clang-tidy. clangd ships with Xcode (`/usr/bin/clangd`); clang-tidy and clang-format come from Homebrew `llvm` (`$(brew --prefix llvm)/bin`), not Xcode.
- clang-tidy baseline: `bugprone-*`, `cert-*`, `cppcoreguidelines-*` (prune noisy ones), `modernize-*`, `performance-*`, `readability-identifier-naming`; run `run-clang-tidy -p build` on changed files; fix, don't blanket-NOLINT.
- `.clang-format` committed (based on a named style); include-what-you-use for header hygiene.
- Debugging: lldb on macOS, gdb on Linux; `-g3 -O0` debug builds; core dumps / `lldb --core`.

## Testing
GoogleTest 1.18 or Catch2 v3.16 registered with CTest (`gtest_discover_tests`, `catch_discover_tests`); property tests with RapidCheck; fuzz parsers with libFuzzer (`-fsanitize=fuzzer,address`, Clang) and keep the corpus; benchmark with Google Benchmark (`cpu-performance`). Tests run under sanitizers in CI.

## C specifics
Integer promotions and usual arithmetic conversions (`uint8_t + uint8_t` is `int`); `size_t` vs signed loops; `restrict` semantics; bounds via explicit lengths; no VLAs in new code; `-Wvla`. Interop: `extern "C"` for exported symbols, POD/standard-layout types across the boundary, no exceptions crossing it.

## ABI, linking, portability
ODR violations (same inline function/class defined differently in two TUs — LTO and `-Wodr` help); symbol visibility (`-fvisibility=hidden` + explicit exports) for shared libraries; macOS uses libc++ only, Linux defaults to libstdc++ — don't pass `std::` types across a library boundary built with a different standard library; `-D_GLIBCXX_USE_CXX11_ABI` mismatches on old binaries; universal binaries on macOS via `CMAKE_OSX_ARCHITECTURES="arm64;x86_64"` (`macos-app-distribution`).

## Review checklist
Ownership explicit · no views outliving owners · no UB under ASan/UBSan/TSan on the tests · warnings clean at the project level · errors handled in one consistent style · features used exist on every target compiler (Apple Clang included) · clang-tidy clean on changed files · tests added.

Sources (checked 2026-09-29): https://en.cppreference.com/w/cpp/compiler_support/26 · https://gcc.gnu.org/gcc-16/changes.html · https://clang.llvm.org/cxx_status.html · https://github.com/llvm/llvm-project/releases (llvmorg-23.1.2) · https://isocpp.github.io/CppCoreGuidelines/CppCoreGuidelines · https://github.com/google/googletest/releases · https://github.com/catchorg/Catch2/releases · local checks: `clang --version` (Apple clang 21.0.0), feature macros, `-fsanitize` support on macOS 27
