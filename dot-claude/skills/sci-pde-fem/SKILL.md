---
name: sci-pde-fem
description: Load before solving PDEs numerically — FEM/FVM choices, PETSc, FEniCSx, Firedrake, deal.II, MMS.
---
# PDE solvers (FEM, FVM, FD)

Baseline and cost rules: `hpc-computing`. Linear algebra and time integration theory: `num-linear-algebra`, `num-ode-sde`; derivations and proofs go through `proof-craft`.

## Versions
- PETSc 3.26.0 — Verified 2026-10-02 https://gitlab.com/petsc/petsc (tags)
- FEniCSx DOLFINx 0.11.0 (API changes every minor: read the changelog and demos of the installed version) — Verified 2026-10-02 https://github.com/FEniCS/dolfinx/releases/latest
- Firedrake 2026.10.0 — Verified 2026-10-02 https://github.com/firedrakeproject/firedrake/releases/latest
- deal.II 9.8.0 — Verified 2026-10-02 https://github.com/dealii/dealii/releases/latest
- MFEM 4.10 — Verified 2026-10-02 https://github.com/mfem/mfem/releases/latest
- Install FEniCSx/Firedrake through their documented channels (conda-forge/pixi, Docker images, Firedrake's installer); they bring PETSc and MPI builds that must match.

## Choosing a discretization
| problem | method |
|---|---|
| elliptic/parabolic on complex geometry, structural mechanics | continuous Galerkin FEM |
| conservation laws, shocks, CFD with strict local conservation | finite volume (Godunov/upwind, limiters) or DG |
| simple geometry, smooth solutions, spectral accuracy | finite differences or spectral methods |
| incompressible flow | inf-sup stable pairs (Taylor–Hood P2–P1, MINI) or stabilized equal-order (PSPG/SUPG) |
| advection-dominated transport | SUPG/streamline diffusion, DG with upwind fluxes, or FV with limiters |
| high order on GPUs, matrix-free | MFEM, deal.II matrix-free, libCEED |

## Workflow
1. Write the strong form, boundary and initial conditions, and the weak form on paper (function spaces, test functions); check well-posedness assumptions.
2. Nondimensionalize; identify the regime (Péclet, Reynolds numbers) — it decides stabilization and solver.
3. Mesh: Gmsh (`.msh` with physical groups for boundaries) or the library's generators; mesh quality (aspect ratio, min angle) checked; boundary tags verified by plotting.
4. Implement in the library's form language (UFL for FEniCSx/Firedrake) or assembly loops (deal.II, MFEM).
5. Verify with a manufactured solution and observed convergence orders before any physical run — read `references/verification-mms.md` when setting up a convergence study.
6. Solve with an appropriate solver (below), then validate against experiments or benchmarks (e.g. lid-driven cavity, Turek–Hron, NAFEMS) where they exist.
7. Output to XDMF/VTX/VTU for ParaView (`hpc-io`), with units.

## Solvers (PETSc vocabulary; the libraries expose it)
- SPD (Poisson, elasticity): CG + algebraic multigrid (`-ksp_type cg -pc_type gamg` or hypre BoomerAMG); elasticity needs the near-nullspace (rigid body modes) set for AMG.
- Nonsymmetric (advection-diffusion): GMRES + AMG/ILU; check that the preconditioner matches the physics.
- Saddle point (Stokes, mixed): `-pc_type fieldsplit` with Schur complement factorization and a pressure mass-matrix approximation; never plain ILU on the full system.
- Direct solvers (MUMPS, SuperLU_DIST, `-pc_type lu`) for small 2-D problems and as reference; memory grows superlinearly in 3-D.
- Nonlinear: Newton (`-snes_type newtonls`) with line search, a good initial guess, continuation in the hard parameter; check quadratic convergence near the solution (if not, the Jacobian is wrong — test with `-snes_test_jacobian`).
- Always run with `-ksp_converged_reason -snes_converged_reason -ksp_monitor_true_residual` while developing; `-log_view` for performance.
- Time stepping: implicit (BDF, Crank–Nicolson with care for oscillations, DIRK) for stiff diffusion; explicit with a CFL-limited step for hyperbolic problems; PETSc TS for adaptive schemes.

## Pitfalls
Unstable element pairs (pressure checkerboarding); unresolved boundary layers; wrong sign or missing boundary terms in the weak form; Neumann-only problems without fixing the nullspace; tolerances relative to a tiny initial residual; comparing results on different meshes without interpolation; claiming accuracy from a single mesh.

## Verify
MMS convergence rates match theory (e.g. order k+1 in L² for degree-k Lagrange on smooth solutions) on ≥ 3 refinements · solver converged reasons are CONVERGED_* with stated tolerances · mesh independence for the quantity of interest · conservation or energy checks where applicable · library versions reported.
