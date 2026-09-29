---
name: cmake-ninja-builds
description: Load before writing, fixing or speeding up a CMake or Ninja build for C, C++ or CUDA — targets, presets, dependencies (FetchContent, vcpkg, Conan), ccache, CTest, sanitizers.
---
# CMake and Ninja builds

## Scope and baseline
- Covers configuring and building C/C++/CUDA with CMake + Ninja. The C/C++ language, UB and sanitizer triage in `cpp-engineering`; kernel code in `gpu-kernel-dev`; profiling in `cpu-performance`; Rust in `rust-engineering`; Python extensions built with scikit-build-core also land here.
- Versions (GitHub releases, Sep 2026): CMake 4.4.3, Ninja 1.13.2. CMake 4.0 removed compatibility with `cmake_minimum_required` below 3.5 — old projects fail to configure until the minimum is raised (or `-DCMAKE_POLICY_VERSION_MINIMUM=3.5` as a stopgap). Check `cmake --version` and `ninja --version` first.
- Install: `brew install cmake ninja ccache` (macOS), or `uv tool install cmake` / `uv add --dev ninja` for pinned versions per project.

## Modern CMake in one page
```cmake
cmake_minimum_required(VERSION 3.28...4.4)   # min...policy-max: new policies up to 4.4
project(demo VERSION 1.2.0 LANGUAGES CXX)

add_library(core src/core.cpp)
add_library(demo::core ALIAS core)
target_compile_features(core PUBLIC cxx_std_23)
target_include_directories(core PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>)
target_link_libraries(core PRIVATE fmt::fmt)

add_executable(app src/main.cpp)
target_link_libraries(app PRIVATE demo::core)
```
- Everything is a target with usage requirements: `PUBLIC` (me and my consumers), `PRIVATE` (me), `INTERFACE` (consumers only). Never `include_directories`, `add_definitions`, `link_libraries` or `CMAKE_CXX_FLAGS +=` for per-target settings.
- Warnings on your own targets only: `target_compile_options(core PRIVATE $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Wall -Wextra -Wpedantic>)`; `set(CMAKE_COMPILE_WARNING_AS_ERROR ON)` in CI presets (3.24+), overridable with `--compile-no-warning-as-error`.
- `CMAKE_CXX_EXTENSIONS OFF` for portable `-std=c++23` instead of `gnu++23`.
- Source lists: explicit. `file(GLOB … CONFIGURE_DEPENDS)` if you must glob.
- Out-of-source builds only (`build/`); `cmake --fresh` to discard the cache.

## Presets (the reproducible entry point)
`CMakePresets.json` (committed) + `CMakeUserPresets.json` (personal, git-ignored):
```json
{ "version": 6,
  "configurePresets": [
    { "name": "dev", "generator": "Ninja", "binaryDir": "build/dev",
      "cacheVariables": { "CMAKE_BUILD_TYPE": "Debug", "CMAKE_EXPORT_COMPILE_COMMANDS": "ON",
                          "CMAKE_CXX_COMPILER_LAUNCHER": "ccache" } },
    { "name": "release", "inherits": "dev", "binaryDir": "build/release",
      "cacheVariables": { "CMAKE_BUILD_TYPE": "Release", "CMAKE_INTERPROCEDURAL_OPTIMIZATION": "ON" } },
    { "name": "asan", "inherits": "dev", "binaryDir": "build/asan",
      "cacheVariables": { "CMAKE_CXX_FLAGS": "-fsanitize=address,undefined -fno-omit-frame-pointer" } } ],
  "buildPresets": [ { "name": "dev", "configurePreset": "dev" } ],
  "testPresets":  [ { "name": "dev", "configurePreset": "dev", "output": { "outputOnFailure": true } } ] }
```
- `cmake --preset dev && cmake --build --preset dev && ctest --preset dev`; workflow presets chain all three (`cmake --workflow --preset <name>`).
- `compile_commands.json` feeds clangd/clang-tidy; symlink it to the repo root or point clangd at `build/dev`.
- Multi-config (`"generator": "Ninja Multi-Config"`): `CMAKE_BUILD_TYPE` is ignored; pick with `cmake --build build --config Release`, and use `$<CONFIG:Debug>` generator expressions, never `if(CMAKE_BUILD_TYPE …)`.

## Dependencies
- Prefer `find_package(fmt CONFIG REQUIRED)` against an installed package or a package manager.
- FetchContent for small or header-only deps, trying an installed copy first:
  `FetchContent_Declare(fmt GIT_REPOSITORY https://github.com/fmtlib/fmt GIT_TAG <exact tag or SHA> FIND_PACKAGE_ARGS CONFIG)` then `FetchContent_MakeAvailable(fmt)`. Pin a tag or commit — never a branch.
- vcpkg manifest mode: `vcpkg.json` + `builtin-baseline`, configure with `-DCMAKE_TOOLCHAIN_FILE=$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake` (put it in the preset).
- Conan 2: `conan install . --output-folder=build --build=missing -s build_type=Release`, then configure with the generated `conan_toolchain.cmake` and `CMakeDeps` config files.
- Python extensions: scikit-build-core + nanobind or pybind11 (`pyproject.toml` `build-backend = "scikit_build_core.build"`), built through `uv build`.

## Tests, install, packaging
- `enable_testing()` (or `include(CTest)`), `add_test`, GoogleTest `gtest_discover_tests(tests)`, Catch2 `catch_discover_tests`. `ctest -j8 --output-on-failure -R <regex>`, `--repeat until-fail:50` for flakes.
- Install and export so others can `find_package` you: `install(TARGETS core EXPORT demoTargets …)`, `install(EXPORT demoTargets NAMESPACE demo:: DESTINATION lib/cmake/demo)`, `configure_package_config_file` + `write_basic_package_version_file`. Test with `cmake --install build/release --prefix /tmp/stage` and a consumer project.
- CPack for archives and installers when asked.

## Ninja
- `cmake --build build -j` (Ninja already parallelizes to cores+2), `ninja -C build -k 0` (keep going to see all errors), `ninja -C build -t targets all`, `-t compdb`, `-t query <target>`, `-t graph <target> | dot -Tsvg`, `-d explain` (why a target rebuilds), `-t missingdeps` (headers generated without declared deps).
- Rebuilding everything every time → a generated file with a changing timestamp, a `configure_file` that rewrites unconditionally, or `-d explain` will say.
- Memory-heavy link or compile steps: job pools (`set_property(GLOBAL APPEND PROPERTY JOB_POOLS link=2)` + `set(CMAKE_JOB_POOL_LINK link)`).

## Platform notes
- macOS: `CMAKE_OSX_DEPLOYMENT_TARGET` (set before `project()` or in the preset), universal binaries with `CMAKE_OSX_ARCHITECTURES="arm64;x86_64"`, Apple Clang vs Homebrew LLVM (`-DCMAKE_CXX_COMPILER=$(brew --prefix llvm)/bin/clang++`; libc++ mismatches bite), `-G Xcode` only when Xcode is needed. Frameworks via `find_library(ACCELERATE Accelerate)`.
- CUDA: `project(x LANGUAGES CXX CUDA)`, `set(CMAKE_CUDA_ARCHITECTURES 120)` for RTX 50 (sm_120) or `native`, `target_compile_options(k PRIVATE $<$<COMPILE_LANGUAGE:CUDA>:--use_fast_math>)`, `CUDAToolkit` package for cuBLAS etc. `CMAKE_CUDA_HOST_COMPILER` when gcc is too new for nvcc.
- Cross-compiling: a toolchain file (`CMAKE_SYSTEM_NAME`, sysroot, `CMAKE_FIND_ROOT_PATH_MODE_*`) referenced from a preset.

## Debugging configure and link failures
- `cmake --preset dev --fresh --log-level=DEBUG`, `--debug-find-pkg=fmt` (where did find_package look), `--trace-expand --trace-redirect=trace.txt`, `cmake -LAH build | less` (cache), `cmake --graphviz=deps.dot`.
- "Could not find a package configuration file" → the package isn't installed where CMake looks: set `CMAKE_PREFIX_PATH` (in the preset) or install it through the package manager.
- Undefined symbols: link order is target-based now — a missing `target_link_libraries`, a `PRIVATE` that should be `PUBLIC`, or C vs C++ linkage (`extern "C"`).
- ODR and ABI: mixing libstdc++/libc++, `_GLIBCXX_USE_CXX11_ABI`, or different `-std` across static libs.
- Stale cache after changing compilers: `--fresh`; the compiler is fixed at first configure.

## Review checklist
Presets committed and CI uses them · only target_* commands for requirements · deps pinned · warnings-as-errors in CI · compile_commands exported · sanitizer preset passes · install/export tested from a consumer when the project is a library · versions of CMake, Ninja and compilers reported.
