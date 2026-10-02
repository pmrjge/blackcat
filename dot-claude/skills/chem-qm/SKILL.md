---
name: chem-qm
description: Load before quantum-chemistry runs — PySCF, Psi4, xtb, ORCA; methods, basis sets, convergence.
---
# Quantum chemistry

Baseline: `bio-chem-computing`. Quantum many-body numerics outside chemistry: `quantum-physics-numerics`; quantum computing: `quantum-computing`.

## Versions and licenses
- PySCF 2.14.0 (Apache-2.0, Python) — Verified 2026-10-02 https://github.com/pyscf/pyscf/releases/latest
- Psi4 1.11 (LGPL) — Verified 2026-10-02 https://github.com/psi4/psi4/releases/latest
- xtb 6.7.1 (GFN-xTB semiempirical) — Verified 2026-10-02 https://github.com/grimme-lab/xtb/releases/latest
- ORCA: free for academic use only, registration required; version unverified here — check the user's install (`orca` output header) and license before commercial use.

## Choosing a level of theory
| task | method |
|---|---|
| conformer search, screening thousands of molecules, large systems | GFN2-xTB (CREST for conformer ensembles), or ML potentials (MACE, AIMNet2) validated on the chemistry at hand |
| geometries and frequencies of normal organics | composite DFT (r2SCAN-3c) or a hybrid with dispersion (e.g. ωB97X-D, B3LYP-D3(BJ)) / def2-SVP→def2-TZVP |
| reaction energies and barriers | hybrid or double-hybrid DFT with dispersion / def2-TZVP or larger, checked against DLPNO-CCSD(T) single points |
| benchmark accuracy, small molecules | CCSD(T) near the basis-set limit (extrapolation), DLPNO-CCSD(T) for medium size |
| transition metals, open shells, multireference character | check spin states and stability; CASSCF/NEVPT2 when diagnostics demand it |
| solvation | implicit (PCM/SMD/CPCM; ALPB in xtb), explicit molecules for specific interactions |
Always include dispersion correction for DFT; state functional, basis, dispersion, grid and solvent model in every result.

## Workflow
1. Geometry: reasonable start (RDKit ETKDG, xtb pre-optimization), correct charge and multiplicity stated explicitly.
2. Optimization to tight criteria; then **frequencies** at the same level: minima have zero imaginary frequencies, transition states exactly one along the reaction coordinate (confirm with IRC).
3. Single points at a higher level on the optimized geometry when needed.
4. Thermochemistry: ZPE and thermal corrections from frequencies (quasi-harmonic treatment of low modes), standard-state correction (1 atm → 1 M: +1.89 kcal/mol at 298 K) for solution free energies.
5. Units: 1 Hartree = 627.509 kcal/mol = 27.2114 eV = 2625.50 kJ/mol; report in the units the user asked for.

## SCF and convergence
- Check SCF stability (wavefunction stability analysis) for open shells and stretched bonds; broken-symmetry solutions when appropriate; ⟨S²⟩ for spin contamination.
- Convergence aids: better initial guess (from a smaller basis or xtb), level shifting, damping, DIIS settings, fractional occupation (xtb electronic temperature); never loosen convergence thresholds to "get a number".
- Integration grids fine enough for meta-GGAs (r2SCAN, M06) — grid artifacts show up in low frequencies.
- Interaction energies: counterpoise correction for BSSE or large basis sets.

## Running
- PySCF in a uv project (`uv add pyscf`), scripts run with `uv run`; Psi4 and xtb via conda-forge/pixi; ORCA as the user's local binary (parallel runs need its matching Open MPI).
- Memory and cores set explicitly (`mol.max_memory`, `psi4.set_memory`, `%pal`/`%maxcore` in ORCA, `OMP_NUM_THREADS` for xtb); big jobs announced and run in the background with logs; cluster runs follow `hpc-slurm` consent rules.

## Pitfalls
Wrong charge or multiplicity; optimized geometries with imaginary frequencies; mixing levels of theory in an energy difference; missing dispersion; tiny basis sets for anions (use diffuse functions); comparing gas-phase numbers with solution experiments; single conformer for flexible molecules.

## Verify
Frequencies checked for every stationary point · SCF stability checked for open shells · method/basis/dispersion/solvent/grid reported · a small known system reproduced against literature or a benchmark set (e.g. GMTKN55 subset) when validating a protocol · energies in consistent units.
