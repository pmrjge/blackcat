# Modernizing legacy Fortran

Change in small steps, each verified bit-for-bit (or within a stated tolerance) against outputs captured from the original code on representative inputs — capture those first.

1. **Build and characterize**: compile the original with today's compiler (`-std=legacy` / `-fallow-argument-mismatch` for gfortran ≥ 10 if needed), record outputs for regression tests.
2. **Fixed form → free form**: convert mechanically (e.g. `findent --input_format=fixed --output_format=free`, or a conversion script), rename `.f`/`.for` to `.f90`; diff outputs.
3. **`implicit none`** everywhere; declare all variables; fix the bugs it exposes (typos, wrong types).
4. **Modules**: move subroutines into modules so interfaces are checked; argument mismatches the compiler now reports are real bugs (passing a scalar to an array dummy, wrong kinds).
5. **COMMON blocks → module variables** (then derived types passed explicitly); watch for COMMON blocks with different layouts in different units (equivalence-like aliasing) — map them carefully.
6. **EQUIVALENCE, computed/assigned GOTO, arithmetic IF, statement functions, ENTRY** → structured equivalents.
7. **Kinds**: `REAL*8`/`DOUBLE PRECISION` → `real(dp)`; check literals (`1.0` → `1.0_dp`) — this may change results (previously single-precision constants), document it.
8. **Dynamic memory**: fixed-size work arrays → allocatables sized from inputs.
9. **Intents and purity** on arguments; then parallelization (`hpc-mpi-openmp`).
10. Keep the public interface (subroutine names, argument order) stable for callers until the end; add a C-bound API if other languages need it.

Record each step in the commit message with the regression result.
