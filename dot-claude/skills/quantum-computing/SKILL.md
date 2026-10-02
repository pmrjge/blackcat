---
name: quantum-computing
description: Load before quantum-circuit work — derivations, simulation, hardware runs, Qiskit, Cirq, stim, QEC.
---
# Quantum computing

## Scope and versions
- Covers:
  - the math of finite-dimensional quantum information;
  - circuits and their verification; choosing a simulator;
  - algorithms; noise and error mitigation; error correction;
  - hardware runs; resource estimates.
- Elsewhere: general proof technique in `proof-craft`; floating point in `numerical-methods`.
- Environment: the sci venv has no quantum libraries. Make a project env with only what you need:
  `uv venv && uv pip install qiskit qiskit-aer pennylane cirq-core stim pymatching sinter mitiq`.
- Every snippet and number below ran in Sept 2026 against Qiskit 2.5.2, qiskit-aer 0.17.2,
  qiskit-ibm-runtime 0.50.0, PennyLane 0.45.1, Cirq 1.7.0, stim 1.16.0, PyMatching 2.4.0, sinter 1.16.0
  and mitiq 1.1.0. mitiq 1.1.0 pins `cirq-core<1.7`, so the one-env install above resolves Cirq 1.6.1.
- These APIs churn:
  - Qiskit 1.0 removed `execute` and BasicAer; 2.0 removed the V1 primitives.
  - Qiskit 2.1 deprecated the circuit-library classes (§2).
  - qiskit-ibm-runtime 0.50 deprecated `SamplerV2` and `EstimatorV2` (§8 in `references/hardware.md`).
  - PennyLane deprecated `shots=` on devices in 0.43; use the `qml.set_shots` transform or
    `qml.qnode(dev, shots=N)`.
- For any other version, check `mcp__libdocs` (`get_library_docs("qiskit", "<topic>")`) or the
  release notes before writing code.

## 2. Circuit identities and gate sets
- Check any identity with `Operator(a).equiv(Operator(b))`, which ignores global phase; `==` does not.
- Single-qubit identities:
  - HXH = Z, HZH = X, HYH = −Y, SXS† = Y.
  - Rz(θ) = e^{−iθ/2}P(θ): the global phase becomes relative once controlled.
  - Any U = e^{iα}Rz(β)Ry(γ)Rz(δ).
- Multi-qubit identities:
  - CNOT = (I⊗H)·CZ·(I⊗H), with H on the target; CZ is symmetric.
  - SWAP = CNOT·CNOT·CNOT with alternating direction (verified).
  - H on both qubits before and after a CNOT swaps control and target.
  - Controlled-U needs at most 2 CNOTs; any two-qubit unitary at most 3 CNOTs (KAK). Toffoli needs 6
    CNOTs and 7 T/T† gates.
- Pauli propagation through CNOT (control c, target t): X_c → X_cX_t, Z_t → Z_cZ_t, while Z_c and X_t
  are unchanged.
- Native gates: read them from the target, never assume. IBM backends expose `rz`, `sx`, `x` plus one
  two-qubit gate (e.g. `ecr` on `FakeSherbrooke`); see `backend.operation_names`.
- Circuit library after Qiskit 2.1: the classes `QFT`, `GroverOperator`, `PhaseEstimation`,
  `RealAmplitudes`, `EfficientSU2`, `TwoLocal` and the `NLocal` family (including `QAOAAnsatz`) are
  deprecated, for removal in Qiskit 3. Use `QFTGate`, `grover_operator`, `phase_estimation`,
  `real_amplitudes`, `efficient_su2`, `n_local`, `qaoa_ansatz`.
- `QFTGate(n)` equals the DFT matrix F_jk = ω^{jk}/√N in Qiskit's little-endian basis (verified).
  Transpiling it to {cx, rz, sx, x} at n = 3 gave 6 CX.

## 3. Choosing a simulator
| method | memory / cost | use for | tools |
|---|---|---|---|
| statevector | 2ⁿ amplitudes (complex128: 16 GiB at n = 30) | exact pure-state circuits | `Statevector`, `StatevectorSampler/Estimator`; Aer `method="statevector"`; PennyLane `default.qubit`, `lightning.qubit`; `cirq.Simulator` |
| density matrix | 4ⁿ (16 GiB at n = 15) | exact noisy runs, small n | Aer `density_matrix`; `default.mixed`; `cirq.DensityMatrixSimulator` |
| noisy trajectories | 2ⁿ per shot | noisy runs, larger n | Aer statevector with a `noise_model` (samples trajectories) |
| stabilizer (tableau) | poly(n) | Clifford circuits, QEC with Pauli noise, thousands of qubits | stim; Aer `stabilizer`; `cirq.CliffordSimulator` |
| extended stabilizer | exponential in the non-Clifford count | Clifford + few T | Aer `extended_stabilizer` |
| MPS | poly(n)·χ³ | low-entanglement or 1-D-like circuits | Aer `matrix_product_state` |
| unitary / superop | 4ⁿ / 16ⁿ | verifying small circuits and channels | Aer `unitary`, `superop`; `Operator`, `SuperOp` |

- Capacities: the 512 GB Mac holds a complex128 statevector up to 34 qubits and a density matrix up to
  17. The 12 GB GPU holds about 30 qubits in complex64.
- GPU packages:
  - `pennylane-lightning-gpu`;
  - `qiskit-aer-gpu`, which lags the CPU package (0.15.1 vs 0.17.2); check CUDA and GPU support first.
- A 200-qubit GHZ circuit is trivial for Aer `stabilizer`; the same circuit is impossible as a
  statevector.

## 4. Algorithms, with honest caveats
- QFT: O(n²) gates, or O(n log n) approximately by dropping small rotations. Check whether your QFT
  includes the final swaps.
- Phase estimation:
  - t = n + ⌈log₂(2 + 1/(2ε))⌉ counting qubits give n bits with success ≥ 1−ε (Nielsen & Chuang §5.2).
  - The controlled-U^{2^k} gates dominate the cost; preparing the eigenstate is the practical
    bottleneck.
- Grover:
  - ⌊(π/4)√(N/M)⌋ iterations for M marked items; overshooting lowers the success probability.
  - Unknown M: randomized schedules or quantum counting.
  - The speedup is only quadratic and the oracle cost counts.
- Shor:
  - Order finding with modular exponentiation dominating.
  - RSA-2048 estimates: 20 million noisy qubits for 8 hours (Gidney–Ekerå 1905.09749); under a million
    noisy qubits for under a week (Gidney 2505.15917). Both assume 0.1% gate error, a 1 µs cycle and a
    nearest-neighbour grid.
  - Small "demonstrations" (factoring 15 or 21) usually compile in knowledge of the answer; treat them
    skeptically.
- VQE (Peruzzo et al. 1304.3061) and QAOA (Farhi et al. 1411.4028):
  - Heuristics with no proven advantage (reviews: Cerezo et al. 2012.09265, Bharti et al. 2101.08448).
  - Barren plateaus (McClean et al. 1803.11173) hit expressive ansätze and global costs.
  - Shot noise dominates the optimization budget (O(1/ε²) shots per measured group).
  - Always compare with strong classical baselines: exact diagonalization or DMRG; Goemans–Williamson or
    annealing for MaxCut.
- Gradients:
  - Parameter shift for gates e^{−iθP/2}: ∂⟨O⟩/∂θ = ½[⟨O⟩(θ+π/2) − ⟨O⟩(θ−π/2)]. It is exact, and
    PennyLane `diff_method="parameter-shift"` matched −sin 0.4 to 1e-16.
  - Finite differences are noisy under shots.

## 7. Verification
- [ ] Structural checks:
  - states normalized; density matrices Hermitian, PSD (min eigenvalue ≥ −1e-12) and trace 1;
  - `Operator(qc).is_unitary()`; channels `Kraus(...).is_cptp()`.
- [ ] Exact reference: build the expected matrix in numpy (mind the kron order), then use
      `Operator(qc).equiv(...)`, or check |tr(U†V)|/d ≈ 1 for equality up to phase.
- [ ] Sampled vs exact: total variation distance within shot noise (of order √(K/N) for K
      outcomes); expectation values within 3 standard errors.
- [ ] Cross-framework: the same circuit agrees in Qiskit and PennyLane/Cirq after bit reversal.
- [ ] Invariants: equal entropies for complementary parts of a pure state; ⟨P⟩ ∈ [−1,1];
      probabilities sum to 1.
- [ ] QEC:
  - `circ.without_noise()` produces no detection events;
  - `detector_error_model(decompose_errors=True)` succeeds;
  - logical error falls with d below threshold, with enough errors collected for a tight interval.

## 9. Resource estimation
- Logical level: qubits, T/Toffoli count (non-Clifford gates dominate under surface-code fault
  tolerance), depth, and the number of arbitrary rotations (each costs O(log 1/ε) T gates).
- Physical level:
  - Choose d so that p_L × (logical qubits × rounds) ≪ 1.
  - Add magic-state factories and a lattice-surgery layout (Litinski 1808.02892).
  - State the assumptions: physical error rate, cycle time, connectivity, decoder latency.
- Tools: the Azure Quantum Resource Estimator via the `qsharp` package (Beverland et al. 2211.07629)
  and Google's `qualtran`. Check their current APIs before use.
- Sanity-check any estimate against the RSA-2048 figures above.

## Report
- Circuits, with the qubit-ordering convention; framework versions; simulator or device.
- Shots, noise model, transpiler settings, and the resulting depth and two-qubit counts.
- Results with error bars; the verification performed; mitigation used and its overhead.
- Caveats: classical baselines, scaling assumptions.

## References
- `references/math-essentials.md` — read when you need the linear-algebra and measurement formalism (states, channels, Pauli algebra).
- `references/noise-mitigation.md` — read when modelling noise or applying error mitigation.
- `references/error-correction.md` — read when working on quantum error-correcting codes, decoders or thresholds.
- `references/hardware.md` — read when running circuits on real quantum hardware.
