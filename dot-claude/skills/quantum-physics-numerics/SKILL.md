---
name: quantum-physics-numerics
description: Load before simulating a quantum system numerically outside the circuit model — Hamiltonians in truncated bases, exact diagonalization with symmetries, sparse eigensolvers, time evolution (Krylov, Trotter, split-operator), open systems (Lindblad, Bloch–Redfield, trajectories, HEOM), tensor networks (DMRG, TEBD, TDVP), QuTiP 5, QuSpin, quimb, TeNPy, ITensors.jl, units and verification.
---
# Quantum physics numerics

## Scope and baseline
- Spectra, dynamics and steady states of quantum systems: spins, bosons, fermions, cavities, driven and open systems, many-body lattices. Qubits and circuits live in `quantum-computing`; floating point, conditioning and ODE solver choice in `numerical-methods`; derivations in `proof-craft`.
- Environments: a project env (`uv venv && uv pip install qutip scipy numpy quimb physics-tenpy quspin`); QuTiP 5.3.1 is current (Aug 2026). Julia alternatives: QuantumToolbox.jl (QuTiP-like, GPU), QuantumOptics.jl, ITensors.jl + ITensorMPS.jl (`julia-engineering`). Check each package's current docs (mcp__libdocs) — QuTiP 5 changed solver options and data layers from 4.x.

## Setting up the problem
- Write the Hamiltonian with units: either ħ = 1 with energies as angular frequencies, or SI via `scipy.constants`. **The #1 bug is ω vs f (a factor 2π)** — state which one every parameter is.
- Truncate infinite spaces deliberately (Fock cutoff N for a cavity, grid size and spacing for continuous variables) and prove convergence: repeat at N and 1.5N (or halve dx) and show the observable doesn't move beyond tolerance.
- Frames: rotating frames and the rotating-wave approximation need g, Ω ≪ ω (and state which terms you drop); counter-rotating terms matter in ultrastrong coupling.
- Fermions: Jordan–Wigner (or a library's fermionic operators) with signs checked on a 2-site example against hand calculation.
- Memory: dense H of dimension d costs 16 d² bytes (complex128) — d = 2¹⁴ is already 4 GiB; use sparse matrices and symmetries early.

## Exact diagonalization
- Block-diagonalize with symmetries before diagonalizing: particle number / magnetization sector (U(1)), momentum (translation), parity, spin flip. QuSpin builds symmetry-reduced bases for spins, bosons and fermions.
- Sparse eigensolvers: `scipy.sparse.linalg.eigsh(H, k=6, which="SA")` for the lowest states; shift-invert (`sigma=E0`) for interior eigenvalues (needs a factorization — memory); dense `numpy.linalg.eigh` only up to d ≈ 10⁴.
- Degenerate levels: eigenvectors are only defined up to rotation within the degenerate subspace — compare subspaces (projectors) or symmetry-resolved states, never raw vectors. Phases are arbitrary.
- Checks: `np.allclose(H, H.conj().T)`; ground-state energy against a known limit; variational bound (any trial state gives ⟨H⟩ ≥ E0); energy variance ⟨H²⟩ − ⟨H⟩² ≈ 0 for eigenstates.

## Time evolution (closed systems)
- Small or medium sparse systems: `scipy.sparse.linalg.expm_multiply(-1j*H*t, psi)` (Krylov-type, no dense exponential), or QuTiP `sesolve(H, psi0, tlist, e_ops=[…])` with `options={"atol": 1e-10, "rtol": 1e-8, "nsteps": 10**6}` when accuracy matters.
- Time-dependent H: QuTiP `QobjEvo` (`[H0, [H1, coeff_fn_or_array]]`); for periodic drives, Floquet (`FloquetBasis`) instead of long integrations.
- Trotter–Suzuki: second order has error O(dt²) per unit time; check by halving dt. Norm and energy (for time-independent H) must be conserved — track both.
- Continuous variables: split-operator FFT (`exp(-iV dt/2) · FFT⁻¹ exp(-iT dt) FFT · exp(-iV dt/2)`); grid spacing must resolve the largest momentum (dx < π/k_max), the box must contain the wavepacket (or use absorbing boundaries), and dt must resolve the largest energy.

## Open systems
- Lindblad master equation: collapse operators carry the rate, `C = sqrt(γ) a`; QuTiP `mesolve(H, rho0, tlist, c_ops=[…], e_ops=[…])`. Valid under Born–Markov and secular approximations — say so; temperature via `sqrt(γ(n̄+1)) a` and `sqrt(γ n̄) a†`.
- Bloch–Redfield (`brmesolve`) when the bath spectrum matters; HEOM (`qutip.solver.heom`) for strong coupling or structured, non-Markovian baths (expensive: check convergence in hierarchy depth and bath exponents).
- Monte Carlo trajectories (`mcsolve`) for large Hilbert spaces: report the ensemble mean with its standard error and show convergence in `ntraj`.
- Steady states: `steadystate(H, c_ops)`; check the Liouvillian gap and that the result is Hermitian, positive semidefinite and trace 1 (`rho.tr()`, eigenvalues ≥ −1e-12).

## Tensor networks
- MPS/DMRG for 1D ground states (and quasi-1D cylinders): bond dimension χ, truncation error, sweeps; converge χ until energy and observables stop moving; check energy variance; add noise/subspace expansion early to escape local minima. Libraries: TeNPy (Python), quimb, ITensorMPS.jl.
- Dynamics: TEBD (nearest-neighbour, Trotter error + truncation error), TDVP (long-range, conserves energy; watch the projection error at small χ); entanglement growth after quenches limits reachable times — report the χ needed and stop where truncation error explodes.
- Area law vs volume law: critical 1D systems need χ growing with system size; 2D (PEPS) is hard — say when the method is out of its regime.

## Standard benchmarks to verify against
- Two-level Rabi: P_e(t) = (Ω²/Ω_R²) sin²(Ω_R t/2) with Ω_R = √(Ω² + Δ²).
- Harmonic oscillator levels ħω(n + ½); coherent states stay coherent under H = ωa†a.
- Jaynes–Cummings vacuum Rabi splitting 2g√n; collapse and revival for coherent fields.
- Transverse-field Ising chain: exact via Jordan–Wigner/free fermions; critical point at h = J.
- Free fermions (quadratic Hamiltonians) via single-particle diagonalization; Heisenberg chain ground-state energy per site → 1/4 − ln 2 in the thermodynamic limit (J = 1).
- Sum rules, commutation relations, detailed balance (thermal steady states), Hellmann–Feynman (dE/dλ = ⟨∂H/∂λ⟩).

## Beyond: chemistry and variational methods
PySCF for molecular Hamiltonians; OpenFermion/Qiskit Nature to map them to qubits (`quantum-computing`); NetKet (JAX) for neural quantum states; quantum Monte Carlo has a sign problem for fermions and frustrated magnets — say when it applies.

## Performance
Sparse CSR matrices; reuse factorizations; avoid building dense Liouvillians (d² × d²) beyond a few thousand states; parallelize parameter sweeps across processes (one BLAS thread each), not within tiny problems. GPUs: QuantumToolbox.jl or qutip-jax/CuPy on NVIDIA; MLX supports complex64 — check that the linear-algebra routines you need run on its GPU before planning around it.

## Report
Model and units · truncation/grid/χ with convergence evidence · method and tolerances · independent checks passed (limits, conservation, second method) · uncertainty (trajectory error bars, truncation error) · versions and script paths.
