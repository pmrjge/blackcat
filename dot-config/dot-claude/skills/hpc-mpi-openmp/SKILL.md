---
name: hpc-mpi-openmp
description: Use for MPI and OpenMP — decomposition, collectives, hybrid runs, binding, scaling.
---
# MPI and OpenMP

Cost and baseline rules: `hpc-computing`. Cluster launch details: `hpc-slurm`.

## Versions
- Open MPI 5.0.11 stable; 6.0.0 at release-candidate stage — Verified 2026-10-02 https://github.com/open-mpi/ompi (tags)
- MPICH 5.0.2 — Verified 2026-10-02 https://github.com/pmodels/mpich/releases/latest
- OpenMP specification 6.0 (Nov 2024); compilers implement it partially — check the compiler's OpenMP status page — Verified 2026-10-02 https://www.openmp.org/specifications/
- On clusters, use the site's MPI (built against its interconnect and scheduler), not a pip/conda/Homebrew one.

## MPI rules
- Decompose the domain to balance work and minimize surface (halo) per rank; ghost/halo exchange with nonblocking `MPI_Isend`/`MPI_Irecv` + `MPI_Waitall`, overlapping interior computation.
- Collectives over hand-rolled loops (`MPI_Allreduce`, `MPI_Alltoallv`, neighborhood collectives on Cartesian/graph topologies); nonblocking collectives (`MPI_Iallreduce`) to overlap.
- Derived datatypes (`MPI_Type_vector`, `MPI_Type_create_subarray`) for strided halos instead of manual packing where it simplifies code.
- Communicators per concern (`MPI_Comm_split`); never use `MPI_COMM_WORLD` inside a library.
- Deadlock avoidance: no blocking send/recv pairs that rely on buffering; consistent collective call order on all ranks.
- Error handling: check return codes or set `MPI_ERRORS_RETURN` where recovery is possible; abort with a message otherwise.
- Bindings: C/C++ API, Fortran `use mpi_f08`, Python `mpi4py` (buffer-based uppercase methods for arrays), Julia MPI.jl.
- GPU-aware MPI only when the build supports it (`ompi_info | rg -i cuda`, MPICH/Cray docs); otherwise stage through host memory.

## OpenMP rules
- `#pragma omp parallel for` / `!$omp parallel do` with explicit data-sharing (`default(none)` + `shared`/`private`/`firstprivate`), `reduction` clauses instead of atomics in loops.
- `schedule(static)` for uniform work, `dynamic`/`guided` with a chunk size for irregular work; `collapse(n)` for small outer loops.
- First-touch NUMA: initialize arrays in parallel with the same schedule used for computation.
- Tasks (`omp task`, `taskloop`, `depend`) for irregular parallelism; `omp simd` for vectorization hints.
- Offload (`target teams distribute parallel for`, `map` clauses) only with a compiler that supports the GPU; keep data resident with `target data` regions.
- Race checks: ThreadSanitizer builds (with an OpenMP runtime built for it, e.g. LLVM's Archer) on small inputs.

## Hybrid MPI + OpenMP
- Typical: one rank per NUMA domain or socket, threads within it; `OMP_NUM_THREADS`, `OMP_PLACES=cores`, `OMP_PROC_BIND=close|spread`.
- `MPI_Init_thread` with the level actually needed (`MPI_THREAD_FUNNELED` when only the master thread communicates); check the provided level.
- Binding: `srun --cpus-per-task=$OMP_NUM_THREADS --cpu-bind=cores` (SLURM) or `mpirun --map-by ppr:1:numa:pe=<n> --bind-to core` (Open MPI); print the binding (`--report-bindings`, `OMP_DISPLAY_AFFINITY=true`) once per configuration.

## Scaling studies
Read `references/scaling-study.md` when designing or reporting strong/weak scaling, or when performance does not scale.

## Local testing
`mpirun -n 4 ./app` (Open MPI: `--oversubscribe` on a laptop) or `mpiexec -n 4`; small problem sizes; run the same test with 1, 2, 3 and 4 ranks (odd counts find decomposition bugs).

## Pitfalls
Unbalanced decompositions; serial bottlenecks (I/O on rank 0, setup) dominating at scale; oversubscription from threads × ranks > cores; false sharing on per-thread counters; reductions giving rank-count-dependent results without tolerance; missing `MPI_Finalize` on error paths hanging jobs.

## Verify
Same result (within tolerance) for 1, 2, 3, 4 ranks and 1/N threads · no races (TSan/Archer on a small case) · binding report matches intent · scaling table with efficiency and repeats.
