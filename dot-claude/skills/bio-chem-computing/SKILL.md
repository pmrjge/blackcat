---
name: bio-chem-computing
description: Load for computational biology or chemistry — data-use and biosecurity rules, environments, provenance; module map from pipelines to QM.
---
# Computational biology and chemistry (hub)

## Scope
Workflows and analyses on sequencing data, cells, proteins, small molecules and molecular simulations. Statistics: `data-analysis`; deep models: the ML skills (`ml-experiment`, `training-debug`); clusters: `hpc-computing`; plots: `data-visualization`.

## Modules
| module | load when |
|---|---|
| `bio-pipelines` | Nextflow/nf-core, Snakemake, containers, pixi/bioconda environments, workflow testing |
| `bio-genomics` | reads to variants: QC, alignment, BAM/CRAM, variant calling, VCF, annotation, RNA-seq |
| `bio-single-cell` | scRNA-seq and multiome: AnnData/scanpy, Seurat, QC, integration, annotation |
| `bio-structures` | protein structures: PDB/mmCIF, AlphaFold 3, Boltz, docking, structure analysis |
| `chem-informatics` | RDKit: SMILES, standardization, descriptors, fingerprints, similarity, QSAR |
| `chem-md` | molecular dynamics: OpenMM, GROMACS, force fields, equilibration, analysis |
| `chem-qm` | quantum chemistry: PySCF, Psi4, xtb, ORCA; methods, basis sets, convergence |

## Data and ethics rules
- **Human data** (genomes, clinical metadata, anything under a data-use agreement — dbGaP, EGA, UK Biobank, hospital data) stays where the agreement allows: never upload it to web services, LLM APIs, external MCP servers or public repos; never include identifiers in queries to external APIs. Ask the user what the agreement permits when unsure.
- External database and API queries (NCBI, Ensembl, UniProt, PDB, ChEMBL, PubChem, a biomedical MCP server) send the query text outside: public identifiers (gene names, accessions) are fine; patient-level data is not. Respect rate limits and API keys from the user's store.
- **Biosecurity**: no help with enhancing pathogenicity, transmissibility or toxicity, synthesizing select agents or toxins, or evading screening. Dual-use requests are declined and reported to the user.
- Model and software licenses: AlphaFold 3 weights are under non-commercial terms granted per user; ORCA is free for academic use only; some force fields and tools have similar terms — check before use in commercial work.

## Engineering baseline
- Environments: pixi (`pixi.toml` + `pixi.lock`, channels `conda-forge` + `bioconda`) or containers for bioinformatics tools; uv for pure-Python analysis code. Bioconda's coverage on osx-arm64 is partial: fall back to linux-64 containers when a package is missing.
- Reference data versioned and recorded: genome build (GRCh38 vs T2T-CHM13, with or without alt contigs), annotation release (GENCODE/Ensembl number), database versions; never mix builds (`chr1` vs `1` naming is a symptom).
- Every result carries provenance: tool versions, parameters, reference versions, input checksums, commit.
- Heavy jobs (alignment of whole genomes, MD, structure prediction, QM on large systems) are announced, run in the background with logs, one accelerator job at a time; cluster submits follow `hpc-computing` consent rules.
- Small test datasets (downsampled reads, toy molecules) for every pipeline and analysis before full runs.

## Verify
Pipeline or analysis runs end to end on the test data · key numbers recomputed independently (e.g. `samtools flagstat`, cell counts, energies) · reference/build and tool versions reported · no restricted data left the allowed location.
