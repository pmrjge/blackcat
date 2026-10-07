# quantum-computing — hardware (reference)
Read when running circuits on real quantum hardware. Parent: `quantum-computing` SKILL.md.

## 8. Running on hardware
- Transpile first:
  - `pm = generate_preset_pass_manager(optimization_level=2, backend=backend)` (levels 0–3);
    `isa = pm.run(qc)`.
  - An ISA circuit uses only native gates and the device's connectivity.
  - Record its depth and two-qubit gate count.
- Primitives take PUBs:
  - Sampler: `run([isa], shots=N)` → `result[0].data.meas.get_counts()` (`meas` is the register
    `measure_all` creates).
  - Estimator: `run([(isa, obs.apply_layout(isa.layout), params)])` → `result[0].data.evs` and `.stds`.
  - Local stand-ins: `qiskit.primitives.StatevectorSampler/StatevectorEstimator`,
    `qiskit_aer.primitives.SamplerV2/EstimatorV2`, and fake backends such as
    `qiskit_ibm_runtime.fake_provider.FakeSherbrooke` for dry runs with realistic noise.
- IBM Runtime:
  - `QiskitRuntimeService()` with the account saved once. Keep API keys out of code and repos.
  - Pick a device with `service.least_busy(operational=True, simulator=False)`; execution modes are
    job, `Batch` and `Session`.
  - As of qiskit-ibm-runtime 0.50.0 (2026-09-24), server-side `SamplerV2`/`EstimatorV2` are deprecated
    for the client-side `qiskit_ibm_runtime.executor_sampler.Sampler` and
    `qiskit_ibm_runtime.executor_estimator.Estimator` (same PUB interface, built on `Executor`). In
    0.50 the top-level `Sampler`/`Estimator` imports still alias the deprecated V2 classes.
    `backend.run()` was removed in 0.35 and the V1 primitives in 0.28. Read the release notes before
    writing runtime code.
- Budget:
  - Queues take minutes to hours and QPU time is metered.
  - Batch parameter sweeps into few PUBs, cap the execution time, and debug on fake backends or Aer
    first.
- Statistics:
  - Error bars come from shots, so group qubit-wise-commuting Paulis to share them.
  - Calibrations drift daily: rerun reference circuits (Bell fidelity, readout) in the same batch.
  - Follow the provider's terms of use, and do not publish credentials.
