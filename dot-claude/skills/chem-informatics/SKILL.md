---
name: chem-informatics
description: Load before small-molecule work in RDKit — parsing, standardization, fingerprints, QSAR.
---
# Cheminformatics with RDKit

Baseline and biosecurity rules: `bio-chem-computing` (no help designing toxic agents or controlled substances). Model validation: `ml-experiment`, `tabular-ml`.

## Version
- RDKit 2026.03.6 (releases twice a year, `YYYY.MM.patch`; deprecated APIs removed after a cycle) — Verified 2026-10-02 https://github.com/rdkit/rdkit/releases/latest
- Install in a uv project (`uv add rdkit`) or via conda-forge/pixi; run scripts with `uv run`.

## Parsing and standardization
- `Chem.MolFromSmiles(s)` returns `None` on failure: count and report failures, never drop them silently.
- Standardize before anything else with `rdkit.Chem.MolStandardize.rdMolStandardize`: cleanup (normalize groups, reionize), keep the largest fragment (strip salts and solvents — record what was removed), neutralize charges (`Uncharger`), canonical tautomer (`TautomerEnumerator`) when comparing across sources.
- Identity: canonical SMILES (`Chem.MolToSmiles`) and InChIKey for deduplication; stereo kept (`isomericSmiles=True`) unless the task says otherwise; undefined stereocenters flagged.
- Sources: ChEMBL, PubChem, ZINC — record version/date of the download and the activity filters (assay type, units, confidence score).

## Descriptors and fingerprints
- Fingerprints through generators: `rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)` (ECFP4-like), `GetRDKitFPGenerator`, atom-pair, topological torsion; count fingerprints for ML, bit vectors for similarity search; MACCS keys for quick screens. The old `GetMorganFingerprintAsBitVect` functions are deprecated.
- Similarity: Tanimoto on Morgan bits (`DataStructs.BulkTanimotoSimilarity`); thresholds depend on fingerprint type — don't reuse a 0.7 cutoff across fingerprints.
- Descriptors: `Descriptors.CalcMolDescriptors(mol)` (all RDKit 2D descriptors), Lipinski/Veber rules, QED, SA score (contrib); Mordred-community for larger descriptor sets.
- Substructure: SMARTS via `Chem.MolFromSmarts`, `HasSubstructMatch`; PAINS and Brenk filters with `FilterCatalog` for screening triage.

## 3-D
Conformers with ETKDGv3 (`AllChem.EmbedMultipleConfs(mol, n, params)` after `Chem.AddHs`), then MMFF94 or UFF optimization; seed fixed for reproducibility; conformer ensembles, not single structures, for 3-D descriptors and docking prep. Quantum refinement: `chem-qm`.

## QSAR and ML
- Split by scaffold (Bemis–Murcko) or time, never only random — random splits overestimate performance on new chemotypes.
- Activity data: consistent units (pIC50 = −log10 IC50 [M]), aggregated replicates (median), censored values (`>10 µM`) handled explicitly.
- Baselines: kNN on Tanimoto and a random forest/GBM on Morgan counts before deep models (GNNs via chemprop).
- Applicability domain: report the nearest-training-neighbor similarity of predictions.
- Chemical-space plots (PCA/UMAP on fingerprints) are illustrations, not evidence.

## Reactions and enumeration
`AllChem.ReactionFromSmarts` for library enumeration; check products sanitize; retrosynthesis tools (AiZynthFinder, ASKCOS) give suggestions to be reviewed by a chemist.

## Pitfalls
Silent parse failures; salts inflating molecular weight; tautomer/charge duplicates; mixing IC50 and Ki; random splits; data leakage through near-duplicate molecules in train and test; using hydrogens-implicit molecules for 3-D work; deprecated API calls copied from old tutorials.

## Verify
Parse/standardization counts reported (input, failed, deduplicated) · splits described and leakage checked (max train–test similarity) · baseline metrics with uncertainty · a few structures drawn (`Draw.MolsToGridImage`) and Read for sanity · RDKit version recorded.
