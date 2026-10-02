---
name: hpc-fortran
description: Use for Fortran — modern style, fpm, compilers, C/Python interop, legacy modernization.
---
# Modern Fortran

Baseline: `hpc-computing`. MPI/OpenMP: `hpc-mpi-openmp`.

## Toolchain
- Compilers: gfortran (GCC), LLVM Flang (`flang`), Intel `ifx` (oneAPI; `ifort` is discontinued), NVIDIA `nvfortran` (GPU offload with OpenACC/do concurrent), Cray `ftn` on HPE systems. Report `<compiler> --version`; test with two compilers when portability matters.
- fpm 0.13.0 (Fortran Package Manager; `fpm new`, `fpm build`, `fpm test`, `fpm.toml`) — Verified 2026-10-02 https://github.com/fortran-lang/fpm/releases/latest
- LFortran 0.66.0 (alpha-quality compiler, also interactive; useful for quick checks, not production builds) — Verified 2026-10-02 https://github.com/lfortran/lfortran/releases/latest
- CMake (`enable_language(Fortran)`, module output directories) for mixed-language projects.
- Test frameworks: test-drive (fpm), pFUnit (CMake, MPI-aware), veggies.
- Formatting/linting: fprettify or findent for layout; `-Wall -Wextra -fcheck=all -fbacktrace -ffpe-trap=invalid,zero,overflow -g` (gfortran) in debug builds, `-warn all -check all -traceback` (ifx).

## Rules for new code
- Free form (`.f90`), `implicit none` in every program unit (or `implicit none (type, external)`), everything in modules (`use mod, only: …`); no common blocks, no `include` of variable declarations, no `goto`/arithmetic `if`.
- Kinds from `iso_fortran_env` (`real64`, `int32`, `int64`) via a `kinds` module; literals with kind suffix (`1.0_dp`); never `real*8` or `double precision` in new code.
- `intent(in|out|inout)` on every dummy argument; `pure`/`elemental` where possible; `contiguous` for assumed-shape arrays passed to performance-critical code.
- Allocatables over pointers (automatic deallocation, no aliasing); `allocate(x(n), source=0.0_dp)`; `move_alloc` to grow arrays.
- Array syntax and intrinsics (`matmul`, `sum`, `maxloc`, `pack`) where clear; explicit loops when they're faster or clearer — column-major order: the first index varies fastest in inner loops.
- Derived types with type-bound procedures for abstractions; `abstract interface` + `procedure(…)` for callbacks.
- Error handling: `stat=` and `errmsg=` on allocate/I/O; `error stop` with a message (or return status codes in libraries).
- `do concurrent` expresses independent iterations (some compilers parallelize/offload it); OpenMP/OpenACC directives for explicit control.
- Coarrays (`[*]`, `sync all`) for PGAS parallelism with compilers that support them (gfortran + OpenCoarrays, ifx, Cray).

## Interoperability
- C: `bind(c)` with `iso_c_binding` types (`c_double`, `c_int`, `c_ptr`, `c_f_pointer`); character strings as `character(kind=c_char), dimension(*)`; never rely on compiler name mangling.
- Python: f2py (NumPy; Meson backend since NumPy 1.26/Python 3.12) for quick wrappers, or a C-bound API wrapped with Cython/nanobind; build through uv projects (`uv run --with numpy …`).
- Arrays across languages: column-major vs row-major — transpose or swap indices consciously; 1-based vs 0-based.

## Modernizing legacy code
Read `references/legacy-modernization.md` when converting fixed-form/FORTRAN 77, common blocks or implicit typing.

## Pitfalls
Missing `implicit none` (typos become new variables); `real` literals without kind (single precision silently); intent(out) on allocatables deallocating them on entry; aliasing of dummy arguments (undefined behavior); module compile order in builds; different `.mod` file formats between compilers/versions (rebuild everything after switching).

## Verify
Builds with warnings on and runtime checks in debug (`-fcheck=all`) passing the test suite · results match reference within tolerance with two compilers or two optimization levels · no implicit typing (`implicit none` grep) · interop tested from the calling language.
