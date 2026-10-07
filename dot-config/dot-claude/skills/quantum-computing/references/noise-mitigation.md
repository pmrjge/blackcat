# quantum-computing — noise mitigation (reference)
Read when modelling noise or applying error mitigation. Parent: `quantum-computing` SKILL.md.

## 5. Noise and error mitigation
- Noise model components: depolarizing; T1/T2 thermal relaxation (T2 ≤ 2T1), via
  `thermal_relaxation_error(t1, t2, time)`; readout confusion; crosstalk; leakage; coherent over-rotation
  (twirl it into stochastic Pauli noise).
- Aer (verified):
```python
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel, depolarizing_error, ReadoutError
nm = NoiseModel()
nm.add_all_qubit_quantum_error(depolarizing_error(0.01, 1), ["sx", "x", "rz"])
nm.add_all_qubit_quantum_error(depolarizing_error(0.02, 2), ["cx"])
nm.add_all_qubit_readout_error(ReadoutError([[0.98, 0.02], [0.03, 0.97]]))
sim = AerSimulator(noise_model=nm)          # or AerSimulator.from_backend(FakeSherbrooke())
```
  `NoiseModel.from_backend(backend)` builds a model from calibration data.
- Mitigation reduces the bias of expectation values. It does not correct errors, and its sampling
  overhead grows exponentially with circuit size × error rate (review: Cai et al. 2210.00921).
  - Readout: invert per-qubit confusion matrices.
  - ZNE (Temme–Bravyi–Gambetta 1612.02058): fold gates (G → GG†G) at scale factors 1, 3, 5 and
    extrapolate. A toy run moved 0.882 to 0.986 against an ideal 1.0. Report the fit; extrapolation
    can overshoot. With Mitiq (`executor` maps a circuit to an expectation value):
    ```python
    from mitiq import zne
    from mitiq.zne.inference import RichardsonFactory
    from mitiq.zne.scaling import fold_global
    value = zne.execute_with_zne(circuit, executor,
                                 factory=RichardsonFactory(scale_factors=[1, 3, 5]),
                                 scale_noise=fold_global)
    ```
  - PEC: unbiased, with exponential sampling cost (van den Berg et al. 2201.09866).
  - Pauli twirling / randomized compiling (Wallman–Emerson 1512.01098); dynamical decoupling.
  - IBM Runtime exposes these through its options (resilience level, twirling, ZNE, DD); read the
    current options documentation.
