# quantum-computing — error correction (reference)
Read when working on quantum error-correcting codes, decoders or thresholds. Parent: `quantum-computing` SKILL.md.

## 6. Quantum error correction
- Stabilizer codes [[n,k,d]] (Gottesman quant-ph/9705052):
  - S is an abelian subgroup of the Pauli group with −I ∉ S; the code space is its +1 eigenspace.
  - There are n−k generators; logical operators are N(S)∖S; d is the minimum weight of a nontrivial
    logical.
  - The syndrome is the error's commutation pattern with the generators; the code corrects
    ⌊(d−1)/2⌋ errors.
- CSS codes (Calderbank–Shor quant-ph/9512032; Steane quant-ph/9601029): X- and Z-check matrices with
  H_X H_Zᵀ = 0 (mod 2). Steane [[7,1,3]] comes from the Hamming code and has a transversal CNOT.
- Surface code (Dennis et al. quant-ph/0110143; Fowler et al. 1208.0928):
  - Rotated layout: d² data qubits plus d²−1 measure qubits.
  - Circuit-level threshold is about 0.5–1% depending on the noise model; p_L ≈ A(p/p_th)^{(d+1)/2}.
  - Lattice surgery: Litinski 1808.02892. Below-threshold experiment: Google 2408.13687.
- qLDPC: bivariate bicycle codes (Bravyi et al. 2308.07915) need long-range connectivity. BP+OSD
  decoding (Roffe et al. 2005.07016).
- Decoders: MWPM via PyMatching v2 (sparse blossom, Higgott–Gidney 2303.15933); union-find
  (Delfosse–Nickerson 1709.06218); neural (Bausch et al. 2310.05900).
- stim (Gidney 2103.02202) + PyMatching (verified):
```python
import numpy as np, stim, pymatching
circ = stim.Circuit.generated("surface_code:rotated_memory_z", distance=5, rounds=5,
    after_clifford_depolarization=0.005, before_measure_flip_probability=0.005,
    after_reset_flip_probability=0.005, before_round_data_depolarization=0.005)
dem = circ.detector_error_model(decompose_errors=True)
matching = pymatching.Matching.from_detector_error_model(dem)
dets, obs = circ.compile_detector_sampler().sample(shots=20_000, separate_observables=True)
p_shot = np.mean(np.any(matching.decode_batch(dets) != obs, axis=1))   # 0.013–0.015 in test runs
```
  - Generated tasks: `repetition_code:memory`, `surface_code:rotated_memory_x|z`,
    `surface_code:unrotated_memory_x|z`, `color_code:memory_xyz`.
  - Threshold sweeps with sinter:
    ```python
    stats = sinter.collect(num_workers=4, decoders=["pymatching"], max_shots=10**6, max_errors=500,
                           tasks=[sinter.Task(circuit=c, json_metadata={"d": d}) for d, c in circuits])
    ```
    - It uses multiprocessing: run it from a script under `if __name__ == "__main__":`. It hangs when
      fed through stdin.
    - At p = 0.003 it gave 1.95e-3 (d=3) and 9.5e-4 (d=5) per shot: below threshold.
  - Per-round rate: `sinter.shot_error_rate_to_piece_error_rate(p_shot, pieces=rounds)`.
