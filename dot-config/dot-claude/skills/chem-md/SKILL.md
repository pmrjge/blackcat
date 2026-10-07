---
name: chem-md
description: Use for molecular dynamics — OpenMM, GROMACS, force fields, equilibration, analysis.
---
# Molecular dynamics

Baseline (heavy jobs, cluster consent): `bio-chem-computing`, `hpc-computing`. Structure preparation: `bio-structures`; ligand handling: `chem-informatics`.

## Versions
- OpenMM 8.6.1 — Verified 2026-10-02 https://github.com/openmm/openmm/releases/latest
- GROMACS 2026.4 — Verified 2026-10-02 https://gitlab.com/gromacs/gromacs (tags)
- OpenMM from conda-forge (pixi) or its PyPI wheels; list the usable platforms (CUDA, OpenCL, CPU, Metal plugin) with `pixi run python -m openmm.testInstallation` (or `uv run python -m openmm.testInstallation` in a uv project).

## Setup workflow
1. Structure: prepared protein (missing atoms, protonation at target pH, disulfides), ligands with correct protonation and charges.
2. Force field: proteins AMBER ff19SB (with OPC water) or ff14SB (TIP3P), or CHARMM36m (CHARMM-modified TIP3P); small molecules with OpenFF (Sage) or GAFF2 through `openmmforcefields`, or CGenFF for CHARMM; water model matched to the protein force field.
3. Box: solvate with ≥ 1.0–1.2 nm padding (rhombic dodecahedron in GROMACS saves atoms), neutralize and add salt to the target ionic strength (e.g. 0.15 M NaCl).
4. Minimize; equilibrate NVT (~100 ps) then NPT (~1 ns) with heavy-atom restraints released stepwise; check temperature, pressure, density and potential energy have plateaued.
5. Production: 2 fs timestep with H-bond constraints (4 fs with hydrogen mass repartitioning), PME electrostatics, cutoff ~0.9–1.2 nm per force field, Langevin (middle) integrator or v-rescale thermostat, Monte Carlo or C-rescale barostat.
6. Replicas: ≥ 3 independent runs with different velocity seeds before any conclusion.

## GROMACS skeleton
`gmx pdb2gmx` → `gmx editconf -bt dodecahedron -d 1.2` → `gmx solvate` → `gmx grompp` + `gmx genion -neutral -conc 0.15` → `em.mdp` → `nvt.mdp` → `npt.mdp` → `md.mdp`; `gmx mdrun -deffnm md -nb gpu -pme gpu` (one GPU job at a time on the machine). Never pass `-maxwarn` without reading and justifying each warning. Checkpoints (`-cpi md.cpt`) for restarts.

## OpenMM skeleton
`ForceField('amber14-all.xml', 'amber14/tip3pfm.xml')` → `Modeller.addHydrogens/addSolvent` → `createSystem(nonbondedMethod=PME, constraints=HBonds)` → `LangevinMiddleIntegrator(300*kelvin, 1/picosecond, 0.002*picoseconds)` → `Simulation` with `minimizeEnergy()`, reporters (`StateDataReporter`, `DCDReporter`/XTC, `CheckpointReporter`). Platform chosen explicitly (`CUDA`, `OpenCL`, `Metal` plugin or `CPU`) and reported.

## Analysis
- MDTraj or MDAnalysis: RMSD (after alignment, stated atom selection), RMSF, radius of gyration, hydrogen bonds, contacts, secondary structure (DSSP), distances of interest.
- Remove periodic artifacts (`gmx trjconv -pbc mol -center`, `image_molecules`) before analysis and visualization.
- Convergence: block averaging, autocorrelation times, agreement across replicas; report means with uncertainty across replicas, not within one trajectory.
- Free energies: alchemical (OpenFE, perses, GROMACS FEP with MBAR via alchemlyb), umbrella sampling with WHAM/MBAR, metadynamics with PLUMED — overlap and convergence diagnostics required.

## Pitfalls
Mismatched water model and force field; wrong ligand protonation or charges; unequilibrated density; too short sampling claimed as converged; single trajectory conclusions; PBC artifacts in RMSD; thermostat choices that break dynamics (Berendsen for production); comparing energies from different force fields.

## Verify
Equilibration plots (T, P, density, energy) stable · production length and replica count stated · observables with uncertainties across replicas · inputs (structures, force-field files, `.mdp`/scripts, seeds) archived · software, platform and GPU recorded.
