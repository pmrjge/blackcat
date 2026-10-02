---
name: hpc-computing
description: Use for scientific and HPC code — cluster cost rules, reproducibility; map of MPI, SLURM, Fortran, I/O, PDE modules.
---
# Scientific computing and HPC (hub)

## Scope
Parallel scientific codes, cluster jobs, scaling studies, PDE solvers and their data. Numerics: `numerical-methods` (+ `num-linear-algebra`, `num-ode-sde`); CPU profiling: `cpu-performance`; GPU kernels: `gpu-kernel-dev`; Julia: `julia-engineering`; C++/CMake: `cpp-engineering`, `cmake-ninja-builds`.

## Modules
| module | load when |
|---|---|
| `hpc-mpi-openmp` | MPI, OpenMP, hybrid parallelism, collectives, affinity, scaling studies |
| `hpc-slurm` | job scripts, arrays, allocations, accounting, modules/Spack, cluster etiquette |
| `hpc-fortran` | modern Fortran, gfortran/flang/ifx, fpm, coarrays, C interop, legacy modernization |
| `hpc-io` | HDF5, NetCDF, ADIOS2, parallel I/O, checkpoints, file systems |
| `sci-pde-fem` | PDE discretization, FEM/FVM, PETSc, FEniCSx, Firedrake, deal.II, MFEM, verification |

## Cost and safety rules
- **Cluster allocations are money and shared quota.** Submitting (`sbatch`, `srun`, `salloc`, PBS `qsub`, cloud HPC) needs the user's consent with the estimate: nodes × cores/GPUs × wall time = core-hours (and the account/partition charged). Small test jobs first, then the scale-up, each submit confirmed.
- Remote clusters through ssh use the user's own keys and config; never copy keys, never store passwords, never change remote dotfiles without asking.
- Login nodes are for editing, compiling and submitting — no heavy runs there.
- Scratch file systems are purged and not backed up: results that matter are copied to project storage; say where outputs live.
- Local heavy runs (long or memory-hungry) count as accelerator/heavy jobs: one at a time on the machine, announced, run in the background with a log.

## Engineering baseline
- Correctness before speed: a serial reference result and a verification test (manufactured solution, conservation check, known benchmark) exist before parallelization or optimization.
- Reproducibility: record compiler, MPI, library versions (module list or Spack spec/lock), build flags, input files, rank/thread counts and the git commit with every result.
- Builds: CMake or Meson with explicit options; vendor-optimized BLAS/LAPACK (OpenBLAS, MKL, Accelerate on macOS) chosen deliberately; `-O3 -march=native` only when binaries never move between node types.
- Floating point: results compared with tolerances; summation order changes with rank counts — set tolerances accordingly, never require bitwise equality across decompositions unless reproducible reductions are implemented.
- Performance claims: strong and weak scaling plots with parallel efficiency, wall time and its spread across repeats, hardware description; roofline position for kernels.

## Verify
Verification test passes (convergence order or benchmark match) · parallel run matches the serial reference within tolerance · scaling measurements with environment recorded · job cost estimated and approved before each cluster submit · output locations and versions reported.
