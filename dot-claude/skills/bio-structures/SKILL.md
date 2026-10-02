---
name: bio-structures
description: Load for protein structures — mmCIF parsing, AlphaFold 3 and Boltz predictions, pLDDT/PAE, preparation, alignment, docking.
---
# Protein structures

Data, license and biosecurity rules: `bio-chem-computing`. Simulation of structures: `chem-md`; ligands: `chem-informatics`.

## Versions and licenses
- AlphaFold 3 v3.0.4 (code CC BY-NC-SA 4.0; model weights only by request from Google DeepMind under non-commercial terms, per user — never redistribute them) — Verified 2026-10-02 https://github.com/google-deepmind/alphafold3/releases/latest
- Boltz v2.2.1 (MIT; Boltz-2 adds binding-affinity prediction) — Verified 2026-10-02 https://github.com/jwohlwend/boltz/releases/latest
- Alternatives (Chai-1, Protenix, OpenFold3, ColabFold/AF2 for monomers): check license and version before use; unverified here.
- AlphaFold 3 needs a Linux NVIDIA GPU and large genetic databases for MSAs; on a Mac, run Boltz/ColabFold-style tools where they support the hardware, or use a Linux GPU host or cluster (consent rules in `hpc-computing`).

## Files and parsing
- mmCIF is the archive format (PDB format can't hold large structures); read with gemmi (fast, C++/Python), Biopython (`MMCIFParser`), or biotite; write mmCIF for anything large.
- Fetch from RCSB/PDBe by ID (`https://files.rcsb.org/download/<ID>.cif`); AlphaFold DB for predicted models by UniProt accession.
- Check: chains, residue numbering (author vs label IDs), alternate locations, missing residues/atoms (`_pdbx_unobs_or_zero_occ_residues`), ligands and waters, resolution and R-free for experimental structures.

## Prediction
- Inputs as JSON/YAML job files (sequences, ligands as SMILES/CCD codes, modifications, seeds) committed with the outputs; several seeds and samples, rank by the tool's confidence score.
- Confidence: pLDDT per residue (< 50 likely disordered; > 90 high), PAE for relative domain/chain placement, pTM/ipTM for complexes (ipTM > ~0.8 confident interfaces, < 0.6 likely wrong). Report them; never present a low-confidence region as structure.
- Predictions are hypotheses: no claims about mechanism or binding from a prediction alone; compare with experimental structures where they exist.

## Structure preparation and analysis
- Preparation for simulation/docking: PDBFixer (missing atoms/residues), protonation at the target pH (PROPKA, pdb2pqr, reduce), check histidine states, disulfides, metal sites.
- Superposition and similarity: US-align/TM-align (TM-score > 0.5 same fold), RMSD on aligned Cα after specifying the atom set; DockQ for complexes; lDDT for model quality.
- Visualization: PyMOL (open-source build) or ChimeraX scripted to PNG for reports; Read images before describing them.
- Interfaces and pockets: PLIP/ProLIF for interactions, fpocket for pockets, SASA via FreeSASA or biotite.

## Docking
AutoDock Vina/smina or gnina for classical docking with a defined box; DiffDock-style ML docking with confidence; validate poses with PoseBusters (physical plausibility) and redocking of a known ligand (RMSD < 2 Å) before screening; docking scores are rankings, not binding free energies.

## Pitfalls
Author vs label residue numbering mix-ups; ignoring alternate conformations; treating pLDDT as accuracy of side chains or ligand poses; one seed only; MSA-free runs reported as full predictions; docking into apo structures with closed pockets; redistributing AF3 weights or outputs against its terms.

## Verify
Inputs and seeds archived · confidence metrics reported per model · structural comparisons with stated atom sets and alignment tool · prepared structures pass a minimization or validation check (MolProbity-style clashes) · licenses respected.
